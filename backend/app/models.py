import uuid
from datetime import datetime, time, timezone
from sqlalchemy import Boolean, Column, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, Time, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID, ARRAY as PGArray
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.database import Base
from app.config import settings


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


class AnalysisSkill(Base):
    __tablename__ = "analysis_skills"
    __table_args__ = (
        Index("ix_analysis_skills_owner_status", "owner_id", "status"),
        Index("ix_analysis_skills_official_status", "is_official", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    instruction_md = Column(Text, nullable=False)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    is_official = Column(Boolean, nullable=False, default=False)
    status = Column(String, nullable=False, default="active")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    owner = relationship("User")


class Analysis(Base):
    __tablename__ = "analysis"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    image_id = Column(UUID(as_uuid=True), ForeignKey("images.id"), unique=True)
    design_analysis = Column(Text)
    ops_analysis = Column(Text)
    custom_analysis_json = Column(JSONB, default=dict)
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
    analysis_skill_snapshots_json = Column(JSONB, default=list)
    compare_jd_enabled = Column(Boolean, nullable=False, default=False)
    comparison_config_json = Column(JSONB, default=dict)
    schedule_enabled = Column(Boolean, nullable=False, default=False)
    schedule_start_date = Column(Date, nullable=True)
    schedule_end_date = Column(Date, nullable=True)
    schedule_time = Column(Time, nullable=True)
    schedule_cycle = Column(String, nullable=True)
    approved_task_mode = Column(String, nullable=True)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=utc_now)

    tasks = relationship("Task", back_populates="request")
    comparison_group = relationship("ComparisonGroup", back_populates="request", uselist=False)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("requests.id"), nullable=True)
    name = Column(Text)
    keyword = Column(Text)
    target_app = Column(Text)
    target_scenario = Column(Text)
    scheduled_run_date = Column(Date, nullable=True)
    mode = Column(String, default="uiautomator2")
    generated_instruction = Column(Text, nullable=True, comment="LLM生成的AutoGLM可执行指令")
    target_goals_json = Column(JSONB, default=list)
    analysis_skill_snapshots_json = Column(JSONB, default=list)
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
    blackboard_post = relationship("BlackboardPost", back_populates="task", uselist=False, cascade="all, delete-orphan")


class ComparisonGroup(Base):
    __tablename__ = "comparison_groups"
    __table_args__ = (
        Index("ix_comparison_groups_request_id", "request_id"),
        Index("ix_comparison_groups_jd_task_id", "jd_task_id"),
        Index("ix_comparison_groups_status", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    request_id = Column(UUID(as_uuid=True), ForeignKey("requests.id"), nullable=False)
    baseline_app = Column(Text, nullable=False, default="京东")
    jd_task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=True)
    jd_instruction = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    request = relationship("Request", back_populates="comparison_group")
    jd_task = relationship("Task", foreign_keys=[jd_task_id])
    apps = relationship("ComparisonGroupApp", back_populates="group", cascade="all, delete-orphan")
    slots = relationship("ComparisonSlot", back_populates="group", cascade="all, delete-orphan")


class ComparisonGroupApp(Base):
    __tablename__ = "comparison_group_apps"
    __table_args__ = (
        UniqueConstraint("comparison_group_id", "app_name", name="uq_comparison_group_apps_app"),
        UniqueConstraint("comparison_group_id", "task_id", name="uq_comparison_group_apps_task"),
        Index("ix_comparison_group_apps_group_id", "comparison_group_id"),
        Index("ix_comparison_group_apps_task_id", "task_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    comparison_group_id = Column(UUID(as_uuid=True), ForeignKey("comparison_groups.id"), nullable=False)
    app_name = Column(Text, nullable=False)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=True)
    status = Column(String, nullable=False, default="pending")
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    group = relationship("ComparisonGroup", back_populates="apps")
    task = relationship("Task")
    pair_analyses = relationship("ComparisonPairAnalysis", back_populates="group_app", cascade="all, delete-orphan")


class ComparisonSlot(Base):
    __tablename__ = "comparison_slots"
    __table_args__ = (
        UniqueConstraint("comparison_group_id", "slot_key", name="uq_comparison_slots_key"),
        Index("ix_comparison_slots_group_order", "comparison_group_id", "sort_order"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    comparison_group_id = Column(UUID(as_uuid=True), ForeignKey("comparison_groups.id"), nullable=False)
    slot_key = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    description = Column(Text, nullable=False)
    required = Column(Boolean, nullable=False, default=True)
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=utc_now)

    group = relationship("ComparisonGroup", back_populates="slots")
    matches = relationship("ComparisonSlotMatch", back_populates="slot")
    pair_analyses = relationship("ComparisonPairAnalysis", back_populates="slot")


class ComparisonSlotMatch(Base):
    __tablename__ = "comparison_slot_matches"
    __table_args__ = (
        UniqueConstraint("image_id", name="uq_comparison_slot_matches_image"),
        Index("ix_comparison_slot_matches_group_slot_app", "comparison_group_id", "slot_id", "app_name"),
        Index("ix_comparison_slot_matches_task_id", "task_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    comparison_group_id = Column(UUID(as_uuid=True), ForeignKey("comparison_groups.id"), nullable=False)
    slot_id = Column(UUID(as_uuid=True), ForeignKey("comparison_slots.id"), nullable=True)
    app_name = Column(Text, nullable=False)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False)
    image_id = Column(UUID(as_uuid=True), ForeignKey("images.id"), nullable=False)
    confidence = Column(Float, nullable=False, default=0.0)
    status = Column(String, nullable=False, default="unmatched")
    reason = Column(Text)
    created_at = Column(DateTime, default=utc_now)

    group = relationship("ComparisonGroup")
    slot = relationship("ComparisonSlot", back_populates="matches")
    task = relationship("Task")
    image = relationship("Image")


class ComparisonPairAnalysis(Base):
    __tablename__ = "comparison_pair_analyses"
    __table_args__ = (
        UniqueConstraint("comparison_group_app_id", "slot_id", name="uq_comparison_pair_group_app_slot"),
        Index("ix_comparison_pair_analyses_slot_id", "slot_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    comparison_group_app_id = Column(UUID(as_uuid=True), ForeignKey("comparison_group_apps.id"), nullable=False)
    slot_id = Column(UUID(as_uuid=True), ForeignKey("comparison_slots.id"), nullable=False)
    a_image_id = Column(UUID(as_uuid=True), ForeignKey("images.id"), nullable=False)
    jd_image_id = Column(UUID(as_uuid=True), ForeignKey("images.id"), nullable=False)
    custom_analysis_json = Column(JSONB, default=dict)
    status = Column(String, nullable=False, default="pending")
    error = Column(Text)
    analyzed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    group_app = relationship("ComparisonGroupApp", back_populates="pair_analyses")
    slot = relationship("ComparisonSlot", back_populates="pair_analyses")
    a_image = relationship("Image", foreign_keys=[a_image_id])
    jd_image = relationship("Image", foreign_keys=[jd_image_id])


class BlackboardPost(Base):
    __tablename__ = "blackboard_posts"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_blackboard_posts_task_id"),
        Index("ix_blackboard_posts_published_at", "published_at"),
        Index("ix_blackboard_posts_published_by", "published_by"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id = Column(UUID(as_uuid=True), ForeignKey("tasks.id"), nullable=False)
    published_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    published_at = Column(DateTime, default=utc_now)

    task = relationship("Task", back_populates="blackboard_post")
    publisher = relationship("User")


class Worker(Base):
    __tablename__ = "workers"
    __table_args__ = (
        UniqueConstraint("node_key", name="uq_workers_node_key"),
        Index("ix_workers_status", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    node_key = Column(String, nullable=False)
    name = Column(Text)
    status = Column(String, nullable=False, default="online")
    version = Column(Text)
    notes = Column(Text)
    last_seen_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    devices = relationship("Device", back_populates="worker")
    runs = relationship("TaskRun", back_populates="worker")


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
    source = Column(String, nullable=False, default="local")
    worker_id = Column(UUID(as_uuid=True), ForeignKey("workers.id"), nullable=True)
    last_seen_at = Column(DateTime, nullable=True)
    current_task_run_id = Column(UUID(as_uuid=True), nullable=True)
    notes = Column(Text)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    worker = relationship("Worker", back_populates="devices")


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
    execution_mode = Column(String, nullable=False, default="local")
    worker_id = Column(UUID(as_uuid=True), ForeignKey("workers.id"), nullable=True)
    claimed_at = Column(DateTime, nullable=True)
    heartbeat_at = Column(DateTime, nullable=True)
    log_path = Column(Text)
    output_dir = Column(Text)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=True)
    created_by = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, default=utc_now)

    task = relationship("Task", back_populates="runs")
    device = relationship("Device")
    worker = relationship("Worker", back_populates="runs")
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
    schedule_start_date = Column(Date, nullable=True)
    schedule_end_date = Column(Date, nullable=True)
    schedule_cycle = Column(String, nullable=False, default="daily")
    status = Column(String, nullable=False, default="active")
    analysis_skill_snapshots_json = Column(JSONB, default=list)
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
