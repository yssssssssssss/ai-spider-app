import uuid
from datetime import UTC, datetime, time
from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID, ARRAY as PGArray
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.database import Base
from app.config import settings


def utc_now():
    return datetime.now(UTC).replace(tzinfo=None)


class Image(Base):
    __tablename__ = "images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_path = Column(Text, nullable=False)
    oss_url = Column(Text)
    oss_key = Column(Text)
    source_app = Column(Text)
    scenario = Column(Text)
    captured_at = Column(DateTime)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=True)
    task_run_id = Column(UUID(as_uuid=True), ForeignKey("task_runs.id"), nullable=True)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True)
    created_at = Column(DateTime, default=utc_now)

    task = relationship("Task", back_populates="images")
    task_run = relationship("TaskRun", back_populates="images")
    analysis = relationship("Analysis", back_populates="image", uselist=False)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        Index("ix_users_username", "username"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String, nullable=False)
    display_name = Column(Text)
    password_hash = Column(Text, nullable=False)
    role = Column(String, nullable=False, default="viewer")
    status = Column(String, nullable=False, default="active")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    last_login_at = Column(DateTime, nullable=True)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(Text, nullable=False)
    updated_by = Column(UUID(as_uuid=True), nullable=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class Analysis(Base):
    __tablename__ = "analysis"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id = Column(UUID(as_uuid=True), ForeignKey("images.id"), unique=True)
    design_analysis = Column(Text)
    ops_analysis = Column(Text)
    status = Column(String, default="pending")
    embedding_status = Column(String, default="pending")
    embedding_error = Column(Text)
    analyzed_at = Column(DateTime, nullable=True)

    image = relationship("Image", back_populates="analysis")
    embeddings = relationship("Embedding", back_populates="analysis", cascade="all, delete-orphan")


class Request(Base):
    __tablename__ = "requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Text, default="anonymous")
    target_app = Column(Text)
    target_scenario = Column(Text)
    keywords = Column(PGArray(Text))
    description = Column(Text)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=utc_now)

    tasks = relationship("Task", back_populates="request")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("requests.id"), nullable=True)
    name = Column(Text)
    keyword = Column(Text)
    target_app = Column(Text)
    target_scenario = Column(Text)
    mode = Column(String, default="uiautomator2")
    generated_instruction = Column(Text, nullable=True, comment="LLM生成的AutoGLM可执行指令")
    target_goals_json = Column(JSONB, default=list)
    status = Column(String, default="pending")
    admin_id = Column(Text, nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    approved_by = Column(UUID(as_uuid=True), nullable=True)
    run_by = Column(UUID(as_uuid=True), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    request = relationship("Request", back_populates="tasks")
    images = relationship("Image", back_populates="task")
    runs = relationship("TaskRun", back_populates="task", cascade="all, delete-orphan")
    watch_runs = relationship("WatchRun", back_populates="task")


class Device(Base):
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("serial", name="uq_devices_serial"),
        Index("ix_devices_status", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    serial = Column(Text, nullable=False)
    name = Column(Text)
    status = Column(String, nullable=False, default="offline")
    last_seen_at = Column(DateTime, nullable=True)
    current_task_run_id = Column(UUID(as_uuid=True), nullable=True)
    notes = Column(Text)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class TaskRun(Base):
    __tablename__ = "task_runs"
    __table_args__ = (
        UniqueConstraint("task_id", "attempt_no", name="uq_task_runs_task_attempt"),
        Index("ix_task_runs_task_id", "task_id"),
        Index("ix_task_runs_status", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False)
    attempt_no = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="pending")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    exit_code = Column(Integer, nullable=True)
    failure_reason = Column(Text)
    goal_validation_json = Column(JSONB, default=dict)
    log_path = Column(Text)
    output_dir = Column(Text)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=utc_now)

    task = relationship("Task", back_populates="runs")
    device = relationship("Device")
    images = relationship("Image", back_populates="task_run")


class Embedding(Base):
    __tablename__ = "embeddings"
    __table_args__ = (
        UniqueConstraint("analysis_id", "content_type", name="uq_embeddings_analysis_content_type"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(UUID(as_uuid=True), ForeignKey("analysis.id"), nullable=False)
    embedding = Column(Vector(settings.effective_embedding_dim()))
    content_type = Column(Text, nullable=False)

    analysis = relationship("Analysis", back_populates="embeddings")


class WatchPlan(Base):
    __tablename__ = "watch_plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    target_app = Column(Text, nullable=False)
    target_page = Column(Text, nullable=False)
    entry_instruction = Column(Text, nullable=False)
    focus_question = Column(Text)
    capture_scope = Column(String, nullable=False, default="first_screen")
    schedule_time = Column(Time, nullable=False, default=lambda: time(10, 0))
    status = Column(String, nullable=False, default="active")
    pause_reason = Column(Text)
    last_run_at = Column(DateTime, nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    updated_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    runs = relationship("WatchRun", back_populates="plan", cascade="all, delete-orphan")
    period_reports = relationship("WatchPeriodReport", back_populates="plan", cascade="all, delete-orphan")


class WatchRun(Base):
    __tablename__ = "watch_runs"
    __table_args__ = (
        UniqueConstraint("watch_plan_id", "run_date", name="uq_watch_runs_plan_date"),
        Index("ix_watch_runs_plan_date", "watch_plan_id", "run_date"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    watch_plan_id = Column(UUID(as_uuid=True), ForeignKey("watch_plans.id"), nullable=False)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=True)
    run_date = Column(Date, nullable=False)
    attempt_count = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default="pending")
    failure_reason = Column(Text)
    screenshot_count = Column(Integer, default=0)
    valid_snapshot_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)

    plan = relationship("WatchPlan", back_populates="runs")
    task = relationship("Task", back_populates="watch_runs")
    snapshots = relationship("WatchSnapshot", back_populates="run", cascade="all, delete-orphan")
    daily_summary = relationship("WatchDailySummary", back_populates="run", uselist=False, cascade="all, delete-orphan")


class WatchSnapshot(Base):
    __tablename__ = "watch_snapshots"
    __table_args__ = (
        UniqueConstraint("watch_run_id", "image_id", name="uq_watch_snapshots_run_image"),
        Index("ix_watch_snapshots_run_id", "watch_run_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    watch_run_id = Column(UUID(as_uuid=True), ForeignKey("watch_runs.id"), nullable=False)
    image_id = Column(UUID(as_uuid=True), ForeignKey("images.id"), nullable=False)
    is_primary = Column(Boolean, nullable=False, default=False)
    page_signature = Column(Text)
    created_at = Column(DateTime, default=datetime.now)

    run = relationship("WatchRun", back_populates="snapshots")
    image = relationship("Image")


class WatchDailySummary(Base):
    __tablename__ = "watch_daily_summaries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    watch_run_id = Column(UUID(as_uuid=True), ForeignKey("watch_runs.id"), nullable=False, unique=True)
    summary = Column(Text)
    design_summary = Column(Text)
    ops_summary = Column(Text)
    key_modules_json = Column(JSONB, default=list)
    promotions_json = Column(JSONB, default=list)
    changes_from_previous_json = Column(JSONB, default=dict)
    created_at = Column(DateTime, default=datetime.now)

    run = relationship("WatchRun", back_populates="daily_summary")


class WatchPeriodReport(Base):
    __tablename__ = "watch_period_reports"
    __table_args__ = (
        Index("ix_watch_period_reports_plan_period", "watch_plan_id", "period_days", "date_to"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    watch_plan_id = Column(UUID(as_uuid=True), ForeignKey("watch_plans.id"), nullable=False)
    period_days = Column(Integer, nullable=False)
    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=False)
    report = Column(Text)
    structured_json = Column(JSONB, default=dict)
    created_at = Column(DateTime, default=datetime.now)

    plan = relationship("WatchPlan", back_populates="period_reports")
