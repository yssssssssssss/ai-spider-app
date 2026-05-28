from sqlalchemy import create_engine, event, inspect, text
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


def ensure_schema():
    """Create missing tables and add columns introduced after the first prototype."""
    init_db()
    with engine.begin() as conn:
        inspector = inspect(conn)
        tables = set(inspector.get_table_names())
        if "tasks" in tables:
            task_columns = {col["name"] for col in inspector.get_columns("tasks")}
            if "mode" not in task_columns:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN mode VARCHAR DEFAULT 'uiautomator2'"))
            if "generated_instruction" not in task_columns:
                conn.execute(text("ALTER TABLE tasks ADD COLUMN generated_instruction TEXT"))
        if "images" in tables:
            image_columns = {col["name"] for col in inspector.get_columns("images")}
            if "oss_url" not in image_columns:
                conn.execute(text("ALTER TABLE images ADD COLUMN oss_url TEXT"))
            if "oss_key" not in image_columns:
                conn.execute(text("ALTER TABLE images ADD COLUMN oss_key TEXT"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_images_task_id ON images(task_id)"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
