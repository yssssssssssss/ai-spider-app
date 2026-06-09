import uuid

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

DEFAULT_ANALYSIS_SKILLS = (
    (
        "设计维度",
        "# 设计维度\n从 UI 设计角度分析截图中的布局、配色、视觉层级、信息架构、组件密度、交互提示和可读性。请指出具体画面证据。",
    ),
    (
        "运营维度",
        "# 运营维度\n从运营策略角度分析截图中的促销机制、文案策略、价格策略、用户引导、转化路径、活动利益点和紧迫感营造。请指出具体画面证据。",
    ),
)


def _enable_pgvector(dbapi_conn, connection_record):
    with dbapi_conn.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")


event.listen(engine, "connect", _enable_pgvector)


def init_db():
    """导入模型并创建所有表，避免循环导入"""
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)


def _vector_dim_from_typmod(typmod):
    if typmod is None or typmod < 0:
        return None
    return typmod


def _ensure_embedding_vector_dim(conn):
    target_dim = settings.effective_embedding_dim()
    current = conn.execute(text("""
        SELECT atttypmod
        FROM pg_attribute
        WHERE attrelid = 'embeddings'::regclass
          AND attname = 'embedding'
          AND NOT attisdropped
    """)).first()
    if not current:
        return

    current_dim = _vector_dim_from_typmod(current[0])
    if current_dim == target_dim:
        return

    embedding_count = conn.execute(text("SELECT count(*) FROM embeddings")).scalar()
    if embedding_count:
        raise RuntimeError(
            "embeddings.embedding vector dimension is "
            f"{current_dim}, but configured dimension is {target_dim}. "
            "Back up or clear existing embeddings before changing models."
        )

    try:
        with conn.begin_nested():
            conn.execute(text(f"ALTER TABLE embeddings ALTER COLUMN embedding TYPE vector({target_dim})"))
    except SQLAlchemyError:
        conn.execute(text("ALTER TABLE embeddings DROP COLUMN embedding"))
        conn.execute(text(f"ALTER TABLE embeddings ADD COLUMN embedding vector({target_dim})"))


def _ensure_embedding_uniqueness(conn):
    conn.execute(text("""
        DELETE FROM embeddings e
        WHERE e.analysis_id IS NULL
           OR e.content_type IS NULL
           OR NOT EXISTS (
               SELECT 1 FROM analysis a WHERE a.id = e.analysis_id
           )
    """))
    conn.execute(text("""
        DELETE FROM embeddings e
        USING (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY analysis_id, content_type
                       ORDER BY id DESC
                   ) AS rn
            FROM embeddings
        ) ranked
        WHERE e.id = ranked.id
          AND ranked.rn > 1
    """))
    conn.execute(text("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_embeddings_analysis_content_type
        ON embeddings (analysis_id, content_type)
    """))
    conn.execute(text("ALTER TABLE embeddings ALTER COLUMN analysis_id SET NOT NULL"))
    conn.execute(text("ALTER TABLE embeddings ALTER COLUMN content_type SET NOT NULL"))


def _ensure_column(conn, inspector, table: str, column: str, ddl: str):
    exists = conn.execute(
        text("""
            SELECT 1
            FROM information_schema.columns
            WHERE table_name = :table_name
              AND column_name = :column_name
        """),
        {"table_name": table, "column_name": column},
    ).first()
    if not exists:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


def _ensure_default_users(conn):
    from app.services.auth import hash_password

    system = conn.execute(text("SELECT id FROM users WHERE username = 'system'")).first()
    if not system:
        system_id = str(uuid.uuid4())
        conn.execute(
            text("""
                INSERT INTO users (id, username, display_name, password_hash, role, status, created_at, updated_at)
                VALUES (:id, 'system', '系统用户', :password_hash, 'admin', 'disabled', now(), now())
            """),
            {"id": system_id, "password_hash": hash_password(str(uuid.uuid4()))},
        )
    else:
        system_id = str(system[0])

    admin = conn.execute(text("SELECT id FROM users WHERE username = :username"), {"username": settings.AUTH_DEFAULT_ADMIN_USERNAME}).first()
    if not admin:
        admin_id = str(uuid.uuid4())
        conn.execute(
            text("""
                INSERT INTO users (id, username, display_name, password_hash, role, status, created_at, updated_at)
                VALUES (:id, :username, :display_name, :password_hash, 'admin', 'active', now(), now())
            """),
            {
                "id": admin_id,
                "username": settings.AUTH_DEFAULT_ADMIN_USERNAME,
                "display_name": settings.AUTH_DEFAULT_ADMIN_DISPLAY_NAME,
                "password_hash": hash_password(settings.AUTH_DEFAULT_ADMIN_PASSWORD),
            },
        )
    else:
        admin_id = str(admin[0])

    conn.execute(
        text("UPDATE requests SET user_id = :system_id WHERE user_id IS NULL OR user_id = '' OR user_id = 'anonymous'"),
        {"system_id": system_id},
    )
    conn.execute(
        text("UPDATE tasks SET approved_by = :admin_id WHERE approved_by IS NULL AND admin_id IS NOT NULL"),
        {"admin_id": admin_id},
    )
    conn.execute(
        text("UPDATE tasks SET created_by = :system_id WHERE created_by IS NULL"),
        {"system_id": system_id},
    )
    conn.execute(
        text("UPDATE watch_plans SET created_by = :system_id WHERE created_by IS NULL"),
        {"system_id": system_id},
    )


def _default_invite_code():
    code = settings.AUTH_REGISTRATION_INVITE_CODE.strip()
    return code if len(code) == 4 and code.isdigit() else "1234"


def _ensure_default_app_settings(conn):
    from app.crud import REGISTRATION_INVITE_CODE_KEY

    existing = conn.execute(
        text("SELECT key FROM app_settings WHERE key = :key"),
        {"key": REGISTRATION_INVITE_CODE_KEY},
    ).first()
    if not existing:
        conn.execute(
            text("""
                INSERT INTO app_settings (key, value, updated_at)
                VALUES (:key, :value, now())
            """),
            {"key": REGISTRATION_INVITE_CODE_KEY, "value": _default_invite_code()},
        )


def _ensure_task_runs_backfill(conn):
    task_rows = conn.execute(text("""
        SELECT t.id
        FROM tasks t
        LEFT JOIN task_runs r ON r.task_id = t.id
        WHERE r.id IS NULL
          AND t.status = 'completed'
    """)).all()
    for row in task_rows:
        run_id = str(uuid.uuid4())
        task_id = str(row[0])
        conn.execute(
            text("""
                INSERT INTO task_runs (id, task_id, attempt_no, status, output_dir, log_path, created_at)
                VALUES (:id, :task_id, 1, 'completed', :output_dir, :log_path, now())
            """),
            {
                "id": run_id,
                "task_id": task_id,
                "output_dir": f"data/{task_id}",
                "log_path": f"logs/tasks/{task_id}.log",
            },
        )
        conn.execute(
            text("UPDATE images SET task_run_id = :run_id WHERE task_id = :task_id AND task_run_id IS NULL"),
            {"run_id": run_id, "task_id": task_id},
        )


def _ensure_default_analysis_skills(conn):
    for name, instruction_md in DEFAULT_ANALYSIS_SKILLS:
        conn.execute(
            text("""
                INSERT INTO analysis_skills (
                    id, name, instruction_md, owner_id, is_official, status, created_at, updated_at
                )
                VALUES (
                    :id, :name, :instruction_md, NULL, true, 'active', now(), now()
                )
                ON CONFLICT (name) WHERE is_official = true DO NOTHING
            """),
            {"id": str(uuid.uuid4()), "name": name, "instruction_md": instruction_md},
        )


def ensure_schema():
    """Create missing tables and add columns introduced after the first prototype."""
    init_db()
    with engine.begin() as conn:
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())
        if "tasks" in tables:
            _ensure_column(conn, inspector, "tasks", "mode", "VARCHAR DEFAULT 'uiautomator2'")
            _ensure_column(conn, inspector, "tasks", "generated_instruction", "TEXT")
            _ensure_column(conn, inspector, "tasks", "target_goals_json", "JSONB DEFAULT '[]'::jsonb")
            _ensure_column(conn, inspector, "tasks", "analysis_skill_snapshots_json", "JSONB DEFAULT '[]'::jsonb")
            _ensure_column(conn, inspector, "tasks", "scheduled_run_date", "DATE")
            _ensure_column(conn, inspector, "tasks", "created_by", "UUID")
            _ensure_column(conn, inspector, "tasks", "approved_by", "UUID")
            _ensure_column(conn, inspector, "tasks", "run_by", "UUID")
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tasks_created_by ON tasks(created_by)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tasks_request_scheduled_date ON tasks(request_id, scheduled_run_date)"))
        if "requests" in tables:
            _ensure_column(conn, inspector, "requests", "analysis_skill_snapshots_json", "JSONB DEFAULT '[]'::jsonb")
            _ensure_column(conn, inspector, "requests", "compare_jd_enabled", "BOOLEAN DEFAULT false")
            _ensure_column(conn, inspector, "requests", "comparison_config_json", "JSONB DEFAULT '{}'::jsonb")
            _ensure_column(conn, inspector, "requests", "schedule_enabled", "BOOLEAN DEFAULT false")
            _ensure_column(conn, inspector, "requests", "schedule_start_date", "DATE")
            _ensure_column(conn, inspector, "requests", "schedule_end_date", "DATE")
            _ensure_column(conn, inspector, "requests", "schedule_time", "TIME")
            _ensure_column(conn, inspector, "requests", "schedule_cycle", "VARCHAR")
            _ensure_column(conn, inspector, "requests", "approved_task_mode", "VARCHAR")
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_requests_user_id ON requests(user_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_requests_schedule_status ON requests(status, schedule_enabled)"))
        if "images" in tables:
            _ensure_column(conn, inspector, "images", "oss_url", "TEXT")
            _ensure_column(conn, inspector, "images", "oss_key", "TEXT")
            _ensure_column(conn, inspector, "images", "task_run_id", "UUID")
            _ensure_column(conn, inspector, "images", "device_id", "UUID")
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_images_task_id ON images(task_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_images_task_run_id ON images(task_run_id)"))
        if "analysis" in tables:
            _ensure_column(conn, inspector, "analysis", "custom_analysis_json", "JSONB DEFAULT '{}'::jsonb")
            _ensure_column(conn, inspector, "analysis", "embedding_status", "VARCHAR DEFAULT 'pending'")
            _ensure_column(conn, inspector, "analysis", "embedding_error", "TEXT")
        if "watch_plans" in tables:
            _ensure_column(conn, inspector, "watch_plans", "analysis_skill_snapshots_json", "JSONB DEFAULT '[]'::jsonb")
            _ensure_column(conn, inspector, "watch_plans", "schedule_start_date", "DATE")
            _ensure_column(conn, inspector, "watch_plans", "schedule_end_date", "DATE")
            _ensure_column(conn, inspector, "watch_plans", "schedule_cycle", "VARCHAR DEFAULT 'daily'")
            _ensure_column(conn, inspector, "watch_plans", "created_by", "UUID")
            _ensure_column(conn, inspector, "watch_plans", "updated_by", "UUID")
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_watch_plans_created_by ON watch_plans(created_by)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_watch_plans_schedule ON watch_plans(status, schedule_cycle, schedule_start_date, schedule_end_date)"))
        if "devices" in tables:
            _ensure_column(conn, inspector, "devices", "source", "VARCHAR DEFAULT 'local'")
            _ensure_column(conn, inspector, "devices", "worker_id", "UUID")
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_devices_serial ON devices(serial)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_devices_worker_id ON devices(worker_id)"))
        if "task_runs" in tables:
            _ensure_column(conn, inspector, "task_runs", "goal_validation_json", "JSONB DEFAULT '{}'::jsonb")
            _ensure_column(conn, inspector, "task_runs", "execution_mode", "VARCHAR DEFAULT 'local'")
            _ensure_column(conn, inspector, "task_runs", "worker_id", "UUID")
            _ensure_column(conn, inspector, "task_runs", "claimed_at", "TIMESTAMP")
            _ensure_column(conn, inspector, "task_runs", "heartbeat_at", "TIMESTAMP")
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_task_runs_task_attempt ON task_runs(task_id, attempt_no)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_task_runs_task_id ON task_runs(task_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_task_runs_worker_id ON task_runs(worker_id)"))
        if "workers" in tables:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_workers_node_key ON workers(node_key)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_workers_status ON workers(status)"))
        if "analysis_skills" in tables:
            conn.execute(text("""
                DELETE FROM analysis_skills s
                USING (
                    SELECT id,
                           row_number() OVER (
                               PARTITION BY name
                               ORDER BY created_at ASC NULLS LAST, id
                           ) AS rn
                    FROM analysis_skills
                    WHERE is_official = true
                ) ranked
                WHERE s.id = ranked.id
                  AND ranked.rn > 1
            """))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_skills_official_name ON analysis_skills(name) WHERE is_official = true"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_analysis_skills_owner_status ON analysis_skills(owner_id, status)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_analysis_skills_official_status ON analysis_skills(is_official, status)"))
            _ensure_default_analysis_skills(conn)
        if "blackboard_posts" in tables:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_blackboard_posts_task_id ON blackboard_posts(task_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_blackboard_posts_published_at ON blackboard_posts(published_at)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_blackboard_posts_published_by ON blackboard_posts(published_by)"))
        if "embeddings" in tables:
            _ensure_embedding_vector_dim(conn)
            _ensure_embedding_uniqueness(conn)
        if "users" in tables:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username ON users(username)"))
            _ensure_default_users(conn)
        if "app_settings" in tables:
            _ensure_default_app_settings(conn)
        if "task_runs" in tables and "tasks" in tables:
            _ensure_task_runs_backfill(conn)
        if "comparison_groups" in tables:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_comparison_groups_request_id ON comparison_groups(request_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_comparison_groups_jd_task_id ON comparison_groups(jd_task_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_comparison_groups_status ON comparison_groups(status)"))
        if "comparison_group_apps" in tables:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_comparison_group_apps_app ON comparison_group_apps(comparison_group_id, app_name)"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_comparison_group_apps_task ON comparison_group_apps(comparison_group_id, task_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_comparison_group_apps_group_id ON comparison_group_apps(comparison_group_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_comparison_group_apps_task_id ON comparison_group_apps(task_id)"))
        if "comparison_slots" in tables:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_comparison_slots_key ON comparison_slots(comparison_group_id, slot_key)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_comparison_slots_group_order ON comparison_slots(comparison_group_id, sort_order)"))
        if "comparison_slot_matches" in tables:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_comparison_slot_matches_image ON comparison_slot_matches(image_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_comparison_slot_matches_group_slot_app ON comparison_slot_matches(comparison_group_id, slot_id, app_name)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_comparison_slot_matches_task_id ON comparison_slot_matches(task_id)"))
        if "comparison_pair_analyses" in tables:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_comparison_pair_group_app_slot ON comparison_pair_analyses(comparison_group_app_id, slot_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_comparison_pair_analyses_slot_id ON comparison_pair_analyses(slot_id)"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
