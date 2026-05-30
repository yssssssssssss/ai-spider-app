import uuid
from datetime import datetime, time
from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Index, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID, ARRAY as PGArray
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.database import Base
from app.config import settings


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
    created_at = Column(DateTime, default=datetime.utcnow)

    task = relationship("Task", back_populates="images")
    analysis = relationship("Analysis", back_populates="image", uselist=False)


class Analysis(Base):
    __tablename__ = "analysis"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id = Column(UUID(as_uuid=True), ForeignKey("images.id"), unique=True)
    design_analysis = Column(Text)
    ops_analysis = Column(Text)
    status = Column(String, default="pending")
    analyzed_at = Column(DateTime, nullable=True)

    image = relationship("Image", back_populates="analysis")
    embeddings = relationship("Embedding", back_populates="analysis")


class Request(Base):
    __tablename__ = "requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Text, default="anonymous")
    target_app = Column(Text)
    target_scenario = Column(Text)
    keywords = Column(PGArray(Text))
    description = Column(Text)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)

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
    status = Column(String, default="pending")
    admin_id = Column(Text, nullable=True)
    approved_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    request = relationship("Request", back_populates="tasks")
    images = relationship("Image", back_populates="task")
    watch_runs = relationship("WatchRun", back_populates="task")


class Embedding(Base):
    __tablename__ = "embeddings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    analysis_id = Column(UUID(as_uuid=True), ForeignKey("analysis.id"))
    embedding = Column(Vector(settings.EMBEDDING_DIM))
    content_type = Column(Text)

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
