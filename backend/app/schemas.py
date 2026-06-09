from datetime import date, datetime, time
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from uuid import UUID


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)

class ImageBase(BaseModel):
    file_path: str
    oss_url: Optional[str] = None
    oss_key: Optional[str] = None
    source_app: Optional[str] = None
    scenario: Optional[str] = None
    captured_at: Optional[datetime] = None

class ImageCreate(ImageBase):
    task_id: Optional[UUID] = None
    task_run_id: Optional[UUID] = None
    device_id: Optional[UUID] = None

class ImageOut(ImageBase, OrmModel):
    id: UUID
    task_id: Optional[UUID] = None
    task_run_id: Optional[UUID] = None
    device_id: Optional[UUID] = None
    created_at: datetime

class AnalysisOut(OrmModel):
    id: UUID
    image_id: UUID
    design_analysis: Optional[str] = None
    ops_analysis: Optional[str] = None
    custom_analysis_json: dict | list | None = None
    status: str
    embedding_status: Optional[str] = None
    embedding_error: Optional[str] = None
    analyzed_at: Optional[datetime] = None


class ComparisonSlotInput(BaseModel):
    slot_key: Optional[str] = None
    name: str
    description: str
    required: bool = True


class ComparisonConfigInput(BaseModel):
    a_apps: List[str] = Field(default_factory=list)
    jd_instruction: str
    slots: List[ComparisonSlotInput] = Field(default_factory=list)


class RequestCreate(BaseModel):
    target_app: Optional[str] = None
    target_scenario: Optional[str] = None
    keywords: List[str] = []
    description: Optional[str] = None
    analysis_skill_ids: List[UUID] = Field(default_factory=list)
    compare_jd_enabled: bool = False
    comparison: Optional[ComparisonConfigInput] = None
    schedule_enabled: bool = False
    schedule_start_date: Optional[date] = None
    schedule_end_date: Optional[date] = None
    schedule_time: Optional[time] = None
    schedule_cycle: Optional[str] = None

    @field_validator("schedule_cycle")
    @classmethod
    def validate_schedule_cycle(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = value.strip().lower()
        if normalized not in {"daily", "weekly", "monthly"}:
            raise ValueError("schedule_cycle must be daily, weekly, or monthly")
        return normalized

    @model_validator(mode="after")
    def validate_schedule(self):
        if not self.schedule_enabled:
            self.schedule_start_date = None
            self.schedule_end_date = None
            self.schedule_time = None
            self.schedule_cycle = None
            return self
        if not self.schedule_start_date:
            raise ValueError("schedule_start_date is required when schedule_enabled is true")
        if not self.schedule_end_date:
            raise ValueError("schedule_end_date is required when schedule_enabled is true")
        if self.schedule_end_date < self.schedule_start_date:
            raise ValueError("schedule_end_date cannot be earlier than schedule_start_date")
        if not self.schedule_time:
            raise ValueError("schedule_time is required when schedule_enabled is true")
        if not self.schedule_cycle:
            raise ValueError("schedule_cycle is required when schedule_enabled is true")
        return self


class RequestInterpretIn(BaseModel):
    natural_language: str


class RequestInterpretOut(BaseModel):
    target_app: Optional[str] = None
    target_scenario: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    a_apps: List[str] = Field(default_factory=list)
    comparison_slots: List[ComparisonSlotInput] = Field(default_factory=list)
    jd_instruction: Optional[str] = None


class RequestOut(OrmModel):
    id: UUID
    user_id: str
    user_display_name: Optional[str] = None
    target_app: Optional[str] = None
    target_scenario: Optional[str] = None
    keywords: List[str]
    description: Optional[str] = None
    analysis_skill_snapshots_json: list | dict | None = None
    compare_jd_enabled: bool = False
    comparison_config_json: list | dict | None = None
    schedule_enabled: bool = False
    schedule_start_date: Optional[date] = None
    schedule_end_date: Optional[date] = None
    schedule_time: Optional[time] = None
    schedule_cycle: Optional[str] = None
    approved_task_mode: Optional[str] = None
    status: str
    created_at: datetime

class UserOut(OrmModel):
    id: UUID
    username: str
    display_name: Optional[str] = None
    role: str
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class RegisterRequest(BaseModel):
    username: str
    password: str
    invite_code: str


class UserCreate(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    role: str = "viewer"


class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    role: Optional[str] = None
    status: Optional[str] = None
    password: Optional[str] = None


class RegistrationInviteCodeOut(BaseModel):
    invite_code: str


class RegistrationInviteCodeUpdate(BaseModel):
    invite_code: str


class AnalysisSkillBase(BaseModel):
    name: str
    instruction_md: str


class AnalysisSkillCreate(AnalysisSkillBase):
    pass


class AnalysisSkillUpdate(BaseModel):
    name: Optional[str] = None
    instruction_md: Optional[str] = None
    status: Optional[str] = None


class AnalysisSkillOut(AnalysisSkillBase, OrmModel):
    id: UUID
    owner_id: Optional[UUID] = None
    owner_name: Optional[str] = None
    is_official: bool
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class AnalysisSkillUploadOut(BaseModel):
    name: str
    instruction_md: str


class AnalysisSkillOfficialUpdate(BaseModel):
    is_official: bool


class TaskOut(OrmModel):
    id: UUID
    request_id: Optional[UUID] = None
    name: Optional[str] = None
    keyword: Optional[str] = None
    target_app: Optional[str] = None
    target_scenario: Optional[str] = None
    scheduled_run_date: Optional[date] = None
    mode: str = "uiautomator2"
    generated_instruction: Optional[str] = None
    target_goals_json: list | dict | None = None
    analysis_skill_snapshots_json: list | dict | None = None
    status: str
    admin_id: Optional[str] = None
    created_by: Optional[UUID] = None
    approved_by: Optional[UUID] = None
    run_by: Optional[UUID] = None
    created_by_name: Optional[str] = None
    approved_by_name: Optional[str] = None
    run_by_name: Optional[str] = None
    latest_run_id: Optional[UUID] = None
    attempt_count: int = 0
    failure_reason: Optional[str] = None
    execution_mode: Optional[str] = None
    device_serial: Optional[str] = None
    worker_name: Optional[str] = None
    blackboard_post_id: Optional[UUID] = None
    blackboard_published_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TaskRunOut(OrmModel):
    id: UUID
    task_id: UUID
    attempt_no: int
    status: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    exit_code: Optional[int] = None
    failure_reason: Optional[str] = None
    goal_validation_json: dict | list | None = None
    execution_mode: str = "local"
    worker_id: Optional[UUID] = None
    claimed_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    log_path: Optional[str] = None
    output_dir: Optional[str] = None
    device_id: Optional[UUID] = None
    created_by: Optional[UUID] = None
    created_at: datetime


class BlackboardPostOut(BaseModel):
    id: UUID
    task_id: UUID
    task_name: Optional[str] = None
    keyword: Optional[str] = None
    target_app: Optional[str] = None
    target_scenario: Optional[str] = None
    task_status: str
    published_by: Optional[UUID] = None
    published_by_name: Optional[str] = None
    published_at: datetime
    completed_at: Optional[datetime] = None
    preview_image_id: Optional[UUID] = None
    image_count: int = 0


class BlackboardTaskDetailOut(BaseModel):
    post: BlackboardPostOut
    task: TaskOut


class RetryTaskRequest(BaseModel):
    device_id: Optional[UUID] = None


class RunTaskRequest(BaseModel):
    device_id: Optional[UUID] = None


class DeviceOut(OrmModel):
    id: UUID
    serial: str
    name: Optional[str] = None
    status: str
    source: str = "local"
    worker_id: Optional[UUID] = None
    worker_name: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    current_task_run_id: Optional[UUID] = None
    notes: Optional[str] = None


class DeviceRefreshOut(BaseModel):
    devices: List[DeviceOut]
    adb_available: bool = True


class WorkerOut(OrmModel):
    id: UUID
    node_key: str
    name: Optional[str] = None
    status: str
    version: Optional[str] = None
    notes: Optional[str] = None
    last_seen_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class WorkerRegisterRequest(BaseModel):
    node_key: str
    name: Optional[str] = None
    version: Optional[str] = None
    notes: Optional[str] = None


class WorkerHeartbeatRequest(BaseModel):
    node_key: str
    status: str = "online"
    version: Optional[str] = None
    notes: Optional[str] = None


class WorkerDeviceIn(BaseModel):
    serial: str
    name: Optional[str] = None
    status: str = "online"
    notes: Optional[str] = None


class WorkerDeviceReportRequest(BaseModel):
    node_key: str
    devices: List[WorkerDeviceIn] = []


class WorkerDeviceReportOut(BaseModel):
    worker: WorkerOut
    devices: List[DeviceOut]


class WorkerClaimRequest(BaseModel):
    node_key: str


class WorkerClaimOut(BaseModel):
    run: TaskRunOut
    task: TaskOut
    prompt: Optional[str] = None
    device_serial: Optional[str] = None
    max_steps: int = 10


class WorkerLogAppendRequest(BaseModel):
    node_key: str
    content: str


class WorkerFinishRequest(BaseModel):
    node_key: str
    status: str
    exit_code: Optional[int] = None
    failure_reason: Optional[str] = None

class SearchQuery(BaseModel):
    query: str
    limit: int = 20
    offset: int = 0

class SearchResult(BaseModel):
    image: ImageOut
    analysis: Optional[AnalysisOut] = None
    similarity: Optional[float] = None
    search_mode: Optional[str] = None


class ComparisonPairAnalysisOut(BaseModel):
    id: Optional[UUID] = None
    status: str
    custom_analysis_json: dict | list | None = None
    error: Optional[str] = None
    analyzed_at: Optional[datetime] = None


class ComparisonMatchOut(BaseModel):
    image: ImageOut
    analysis: Optional[AnalysisOut] = None
    confidence: float
    reason: Optional[str] = None


class ComparisonUnmatchedOut(ComparisonMatchOut):
    status: str


class ComparisonSlotResultOut(BaseModel):
    slot_id: UUID
    slot_key: str
    name: str
    description: str
    status: str
    a_match: Optional[ComparisonMatchOut] = None
    jd_match: Optional[ComparisonMatchOut] = None
    pair_analysis: Optional[ComparisonPairAnalysisOut] = None


class ComparisonAppResultOut(BaseModel):
    id: UUID
    app_name: str
    task_id: Optional[UUID] = None
    status: str
    slots: List[ComparisonSlotResultOut] = Field(default_factory=list)
    unmatched: List[ComparisonUnmatchedOut] = Field(default_factory=list)


class ComparisonGroupResultOut(BaseModel):
    group_id: UUID
    request_id: UUID
    baseline_app: str
    jd_task_id: Optional[UUID] = None
    status: str
    apps: List[ComparisonAppResultOut] = Field(default_factory=list)

class ApproveRequest(BaseModel):
    admin_id: Optional[str] = None
    keyword: Optional[str] = None
    target_app: Optional[str] = None
    target_scenario: Optional[str] = None
    mode: str = "uiautomator2"  # "uiautomator2" | "autoglm"

class RejectRequest(BaseModel):
    admin_id: Optional[str] = None
    reason: Optional[str] = None


class WatchPlanCreate(BaseModel):
    name: str
    target_app: str
    target_page: str
    entry_instruction: str
    focus_question: Optional[str] = None
    schedule_time: time = time(10, 0)
    schedule_start_date: Optional[date] = None
    schedule_end_date: Optional[date] = None
    schedule_cycle: str = "daily"
    analysis_skill_ids: List[UUID] = Field(default_factory=list)

    @field_validator("schedule_cycle")
    @classmethod
    def validate_schedule_cycle(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"daily", "weekly", "monthly"}:
            raise ValueError("schedule_cycle must be daily, weekly, or monthly")
        return normalized

    @model_validator(mode="after")
    def validate_schedule_range(self):
        if self.schedule_start_date and self.schedule_end_date and self.schedule_end_date < self.schedule_start_date:
            raise ValueError("schedule_end_date cannot be earlier than schedule_start_date")
        return self


class WatchPlanUpdate(BaseModel):
    name: Optional[str] = None
    target_app: Optional[str] = None
    target_page: Optional[str] = None
    entry_instruction: Optional[str] = None
    focus_question: Optional[str] = None
    schedule_time: Optional[time] = None
    schedule_start_date: Optional[date] = None
    schedule_end_date: Optional[date] = None
    schedule_cycle: Optional[str] = None
    status: Optional[str] = None

    @field_validator("schedule_cycle")
    @classmethod
    def validate_schedule_cycle(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        normalized = value.strip().lower()
        if normalized not in {"daily", "weekly", "monthly"}:
            raise ValueError("schedule_cycle must be daily, weekly, or monthly")
        return normalized


class WatchPlanOut(OrmModel):
    id: UUID
    name: str
    target_app: str
    target_page: str
    entry_instruction: str
    focus_question: Optional[str] = None
    capture_scope: str
    schedule_time: time
    schedule_start_date: Optional[date] = None
    schedule_end_date: Optional[date] = None
    schedule_cycle: str = "daily"
    status: str
    analysis_skill_snapshots_json: list | dict | None = None
    pause_reason: Optional[str] = None
    last_run_at: Optional[datetime] = None
    run_count: int = 0
    latest_run_status: Optional[str] = None
    latest_success_run_at: Optional[datetime] = None
    created_by: Optional[UUID] = None
    updated_by: Optional[UUID] = None
    created_by_name: Optional[str] = None
    updated_by_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class WatchRunOut(OrmModel):
    id: UUID
    watch_plan_id: UUID
    task_id: Optional[UUID] = None
    run_date: date
    attempt_count: int
    status: str
    failure_reason: Optional[str] = None
    screenshot_count: Optional[int] = 0
    valid_snapshot_count: Optional[int] = 0
    created_at: datetime
    completed_at: Optional[datetime] = None


class WatchSnapshotOut(OrmModel):
    id: UUID
    watch_run_id: UUID
    image_id: UUID
    is_primary: bool
    page_signature: Optional[str] = None
    created_at: datetime


class WatchDailySummaryOut(OrmModel):
    id: UUID
    watch_run_id: UUID
    summary: Optional[str] = None
    design_summary: Optional[str] = None
    ops_summary: Optional[str] = None
    key_modules_json: list | dict | None = None
    promotions_json: list | dict | None = None
    changes_from_previous_json: dict | list | None = None
    created_at: datetime


class WatchPeriodReportOut(OrmModel):
    id: UUID
    watch_plan_id: UUID
    period_days: int
    date_from: date
    date_to: date
    report: Optional[str] = None
    structured_json: dict | list | None = None
    created_at: datetime


class WatchPlanDetailOut(BaseModel):
    plan: WatchPlanOut
    latest_run: Optional[WatchRunOut] = None
    latest_success_run: Optional[WatchRunOut] = None
    latest_snapshot: Optional[SearchResult] = None
    latest_summary: Optional[WatchDailySummaryOut] = None
    period_reports: List[WatchPeriodReportOut] = Field(default_factory=list)
    recent_runs: List[WatchRunOut] = Field(default_factory=list)
