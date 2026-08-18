import uuid
import json

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

engine = create_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


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


def _migrate_analysis_skills_table(conn, inspector):
    """迁移 analysis_skills 表：从旧结构（instruction_md/is_official/owner_id）到新结构（description/prompt/profile/skill_type/version/is_system）"""
    columns = {row["name"] for row in inspector.get_columns("analysis_skills")}
    # 新增列
    new_columns = {
        "description": "TEXT",
        "prompt": "TEXT",
        "output_schema_json": "JSONB DEFAULT '{}'::jsonb",
        "scenario_tags_json": "JSONB DEFAULT '[]'::jsonb",
        "profile": "VARCHAR DEFAULT 'default'",
        "skill_type": "VARCHAR DEFAULT 'analysis'",
        "version": "INTEGER DEFAULT 1",
        "is_system": "BOOLEAN DEFAULT false",
        "created_by": "UUID",
        "updated_by": "UUID",
    }
    for col, ddl in new_columns.items():
        if col not in columns:
            conn.execute(text(f"ALTER TABLE analysis_skills ADD COLUMN {col} {ddl}"))

    # 从旧列迁移数据
    if "instruction_md" in columns and "prompt" not in columns:
        conn.execute(text("UPDATE analysis_skills SET prompt = instruction_md WHERE prompt IS NULL"))
    if "is_official" in columns:
        conn.execute(text("UPDATE analysis_skills SET is_system = is_official WHERE is_system IS NULL OR is_system = false"))

    # 删除旧唯一约束和索引
    for constraint in inspector.get_unique_constraints("analysis_skills"):
        conn.execute(text(f"ALTER TABLE analysis_skills DROP CONSTRAINT IF EXISTS {constraint['name']}"))
    for index in inspector.get_indexes("analysis_skills"):
        if not index.get("unique") and index["name"] != "analysis_skills_pkey":
            conn.execute(text(f"DROP INDEX IF EXISTS {index['name']}"))

    # 删除旧列（如果已迁移完成）
    for old_col in ["instruction_md", "is_official", "owner_id"]:
        if old_col in columns:
            try:
                conn.execute(text(f"ALTER TABLE analysis_skills DROP COLUMN IF EXISTS {old_col}"))
            except Exception:
                pass  # 有 FK 或依赖时跳过


def _ensure_default_analysis_skills(conn):
    """确保系统内置分析 skill 存在"""
    from app.services.analysis_skills import SYSTEM_SKILL_DEFAULTS
    count = conn.execute(text("SELECT count(*) FROM analysis_skills")).scalar()
    if count:
        return
    for default in SYSTEM_SKILL_DEFAULTS:
        # 检查是否已存在同名系统 skill
        existing = conn.execute(
            text("SELECT id FROM analysis_skills WHERE name = :name AND is_system = true"),
            {"name": default["name"]},
        ).first()
        if not existing:
            conn.execute(
                text("""
                    INSERT INTO analysis_skills
                        (id, name, description, prompt, output_schema_json, scenario_tags_json,
                         profile, skill_type, status, version, is_system, created_at, updated_at)
                    VALUES
                        (:id, :name, :description, :prompt, '{}'::jsonb, '[]'::jsonb,
                         :profile, :skill_type, 'active', 1, true, now(), now())
                """),
                {
                    "id": str(uuid.uuid4()),
                    "name": default["name"],
                    "description": default["description"],
                    "prompt": default["prompt"],
                    "profile": default["profile"],
                    "skill_type": default["skill_type"],
                },
            )


def _ensure_default_comparison_skills(conn):
    count = conn.execute(text("SELECT count(*) FROM comparison_skills")).scalar()
    if count:
        return
    defaults = [
        (
            "商品详情页对比",
            "比较商品详情页的首屏卖点、价格表达、CTA、信任背书和转化路径。",
            ["商品详情页"],
            "你是电商竞品分析专家。请对所选商品详情页截图进行对比，重点分析首屏卖点、价格表达、CTA、信任背书、信息层级和可借鉴改版建议。输出一句话结论、差异表、证据引用和优先级建议。",
        ),
        (
            "搜索结果页对比",
            "比较搜索结果页的信息密度、商品卡片、筛选排序和广告位。",
            ["搜索结果页"],
            "你是电商搜索体验分析专家。请比较所选搜索结果页截图，重点分析商品卡片信息、排序筛选、广告/运营位、价格利益点、可扫读性和转化机会。输出关键差异、证据和优化建议。",
        ),
        (
            "综合竞品诊断",
            "从设计、运营、转化三个方向给出综合竞品结论。",
            ["综合"],
            "你是资深竞品分析顾问。请从设计表现、运营表达、转化路径、用户决策成本四个维度对所选截图进行综合诊断，给出可执行改进建议，并标注每条结论对应的图片证据。",
        ),
    ]
    for name, description, tags, prompt in defaults:
        conn.execute(
            text("""
                INSERT INTO comparison_skills
                    (id, name, description, scenario_tags_json, prompt, output_schema_json, status, version, created_at, updated_at)
                VALUES
                    (:id, :name, :description, CAST(:tags AS jsonb), :prompt, '{}'::jsonb, 'active', 1, now(), now())
            """),
            {
                "id": str(uuid.uuid4()),
                "name": name,
                "description": description,
                "tags": json.dumps(tags, ensure_ascii=False),
                "prompt": prompt,
            },
        )


def _ensure_task_runs_backfill(conn):
    task_rows = conn.execute(text("""
        SELECT t.id
        FROM tasks t
        LEFT JOIN task_runs r ON r.task_id = t.id
        WHERE r.id IS NULL
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
            _ensure_column(conn, inspector, "tasks", "created_by", "UUID")
            _ensure_column(conn, inspector, "tasks", "approved_by", "UUID")
            _ensure_column(conn, inspector, "tasks", "run_by", "UUID")
            _ensure_column(conn, inspector, "tasks", "analysis_skill_ids", "UUID[]")
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tasks_created_by ON tasks(created_by)"))
        if "requests" in tables:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_requests_user_id ON requests(user_id)"))
            _ensure_column(conn, inspector, "requests", "analysis_skill_ids", "UUID[]")
        if "images" in tables:
            _ensure_column(conn, inspector, "images", "oss_url", "TEXT")
            _ensure_column(conn, inspector, "images", "oss_key", "TEXT")
            _ensure_column(conn, inspector, "images", "task_run_id", "UUID")
            _ensure_column(conn, inspector, "images", "device_id", "UUID")
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_images_task_id ON images(task_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_images_task_run_id ON images(task_run_id)"))
        if "analysis" in tables:
            _ensure_column(conn, inspector, "analysis", "embedding_status", "VARCHAR DEFAULT 'pending'")
            _ensure_column(conn, inspector, "analysis", "embedding_error", "TEXT")
            _ensure_column(conn, inspector, "analysis", "skill_id", "UUID")
            _ensure_column(conn, inspector, "analysis", "skill_key", "VARCHAR")
            _ensure_column(conn, inspector, "analysis", "result_json", "JSONB")
            # 移除旧的 image_id unique 约束（同一图片可有多个 skill 的分析）
            try:
                conn.execute(text("ALTER TABLE analysis DROP CONSTRAINT IF EXISTS analysis_image_id_key"))
            except Exception:
                pass
            conn.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_image_skill
                ON analysis (image_id, skill_id)
            """))
        if "watch_plans" in tables:
            _ensure_column(conn, inspector, "watch_plans", "created_by", "UUID")
            _ensure_column(conn, inspector, "watch_plans", "updated_by", "UUID")
            _ensure_column(conn, inspector, "watch_plans", "schedule_cycle", "VARCHAR DEFAULT 'daily'")
            _ensure_column(conn, inspector, "watch_plans", "schedule_start_date", "DATE")
            _ensure_column(conn, inspector, "watch_plans", "schedule_end_date", "DATE")
            _ensure_column(conn, inspector, "watch_plans", "analysis_skill_ids", "UUID[]")
            conn.execute(text("UPDATE watch_plans SET schedule_cycle = 'daily' WHERE schedule_cycle IS NULL OR schedule_cycle = ''"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_watch_plans_created_by ON watch_plans(created_by)"))
        if "devices" in tables:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_devices_serial ON devices(serial)"))
        if "task_runs" in tables:
            _ensure_column(conn, inspector, "task_runs", "goal_validation_json", "JSONB DEFAULT '{}'::jsonb")
            _ensure_column(conn, inspector, "task_runs", "worker_node_key", "VARCHAR")
            _ensure_column(conn, inspector, "task_runs", "worker_claimed_at", "TIMESTAMP")
            _ensure_column(conn, inspector, "task_runs", "worker_lease_expires_at", "TIMESTAMP")
            _ensure_column(conn, inspector, "task_runs", "worker_error", "TEXT")
            _ensure_column(conn, inspector, "task_runs", "artifact_count", "INTEGER DEFAULT 0")
            conn.execute(text("UPDATE task_runs SET artifact_count = 0 WHERE artifact_count IS NULL"))
            conn.execute(text("ALTER TABLE task_runs ALTER COLUMN artifact_count SET DEFAULT 0"))
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_task_runs_task_attempt ON task_runs(task_id, attempt_no)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_task_runs_task_id ON task_runs(task_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_task_runs_worker_lease ON task_runs(worker_lease_expires_at)"))
        if "embeddings" in tables:
            _ensure_embedding_vector_dim(conn)
            _ensure_embedding_uniqueness(conn)
        if "users" in tables:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_users_username ON users(username)"))
            _ensure_default_users(conn)
        if "app_settings" in tables:
            _ensure_default_app_settings(conn)
        if "comparison_assets" in tables:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_comparison_assets_created_by ON comparison_assets(created_by)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_comparison_assets_image_id ON comparison_assets(image_id)"))
        if "comparison_basket_items" in tables:
            conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_comparison_basket_user_asset ON comparison_basket_items(user_id, asset_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_comparison_basket_user_id ON comparison_basket_items(user_id)"))
        if "comparison_skills" in tables:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_comparison_skills_status ON comparison_skills(status)"))
            _ensure_default_comparison_skills(conn)
        if "analysis_skills" in tables:
            _migrate_analysis_skills_table(conn, inspector)
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_analysis_skills_status ON analysis_skills(status)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_analysis_skills_profile_status ON analysis_skills(profile, status)"))
            _ensure_default_analysis_skills(conn)
        if "comparison_reports" in tables:
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_comparison_reports_created_by ON comparison_reports(created_by)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_comparison_reports_status ON comparison_reports(status)"))
        if "task_runs" in tables and "tasks" in tables:
            _ensure_task_runs_backfill(conn)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
