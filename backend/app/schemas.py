from datetime import date, datetime, time
from typing import Annotated, List, Literal, Optional
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field
from uuid import UUID

# 数据库旧记录 analysis_skill_ids 可能为 None，统一转为空列表
def _none_to_list(v):
    return v if v is not None else []

OptionalUUIDList = Annotated[List[UUID], BeforeValidator(_none_to_list)]


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
    status: str
    embedding_status: Optional[str] = None
    embedding_error: Optional[str] = None
    analyzed_at: Optional[datetime] = None
    skill_id: Optional[UUID] = None
    skill_key: Optional[str] = None
    result_json: dict | list | None = None

class RequestCreate(BaseModel):
    target_app: Optional[str] = None
    target_scenario: Optional[str] = None
    keywords: List[str] = []
    description: Optional[str] = None
    analysis_skill_ids: List[UUID] = Field(default_factory=list)


class LongImageIntentParseRequest(BaseModel):
    text: str = ""
    target_app: Optional[str] = None
    target_scenario: Optional[str] = None
    keywords: List[str] = []
    description: Optional[str] = None


class LongImageIntentOut(BaseModel):
    intent: str
    confidence: float
    scene_type: str
    apps: List[str] = []
    keyword: str = ""
    capture_count: int = 10
    selection_rule: str = "first_normal_product"
    exclude_entry_types: List[str] = []
    dedupe_overlap: bool = True
    stitch: bool = True
    keep_raw_images: bool = True
    missing_fields: List[str] = []


class RequestOut(OrmModel):
    id: UUID
    user_id: str
    user_display_name: Optional[str] = None
    target_app: Optional[str] = None
    target_scenario: Optional[str] = None
    keywords: List[str]
    description: Optional[str] = None
    status: str
    analysis_skill_ids: OptionalUUIDList = Field(default_factory=list)
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


class AnalysisSkillCreate(BaseModel):
    name: str
    description: Optional[str] = None
    prompt: str
    output_schema_json: dict | list | None = None
    scenario_tags_json: list[str] = Field(default_factory=list)
    profile: str = "default"
    skill_type: str = "analysis"
    status: str = "active"


class AnalysisSkillUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    prompt: Optional[str] = None
    output_schema_json: dict | list | None = None
    scenario_tags_json: Optional[list[str]] = None
    profile: Optional[str] = None
    skill_type: Optional[str] = None
    status: Optional[str] = None


class AnalysisSkillOut(OrmModel):
    id: UUID
    name: str
    description: Optional[str] = None
    prompt: str
    output_schema_json: dict | list | None = None
    scenario_tags_json: list | dict | None = None
    profile: str
    skill_type: str
    status: str
    version: int
    is_system: bool
    created_by: Optional[UUID] = None
    updated_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


class TaskOut(OrmModel):
    id: UUID
    request_id: Optional[UUID] = None
    name: Optional[str] = None
    keyword: Optional[str] = None
    target_app: Optional[str] = None
    target_scenario: Optional[str] = None
    mode: str = "uiautomator2"
    generated_instruction: Optional[str] = None
    target_goals_json: list | dict | None = None
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
    device_serial: Optional[str] = None
    approved_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    analysis_skill_ids: OptionalUUIDList = Field(default_factory=list)


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
    log_path: Optional[str] = None
    output_dir: Optional[str] = None
    device_id: Optional[UUID] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    worker_node_key: Optional[str] = None
    worker_claimed_at: Optional[datetime] = None
    worker_lease_expires_at: Optional[datetime] = None
    worker_error: Optional[str] = None
    artifact_count: int = 0


class WorkerClaimRequest(BaseModel):
    node_key: str
    device_serials: List[str] = Field(default_factory=list)
    capabilities: List[str] = Field(default_factory=list)


class WorkerTaskRunOut(TaskRunOut):
    pass


class WorkerClaimOut(BaseModel):
    claimed: bool
    poll_seconds: int
    run: Optional[WorkerTaskRunOut] = None
    task: Optional[TaskOut] = None
    device: Optional["DeviceOut"] = None


class WorkerRunHeartbeatRequest(BaseModel):
    node_key: str


class WorkerRunFinishRequest(BaseModel):
    node_key: str
    exit_code: int = 0
    screenshot_count: int = 0


class WorkerRunFailRequest(BaseModel):
    node_key: str
    exit_code: int = 1
    failure_reason: str


class WorkerArtifactOut(BaseModel):
    image_id: UUID
    file_path: str
    sha256: str
    duplicate: bool = False
    oss_url: Optional[str] = None


class ComparisonAssetCreate(BaseModel):
    image_id: UUID
    notes: Optional[str] = None


class ComparisonAssetOut(OrmModel):
    id: UUID
    source_type: str
    image_id: Optional[UUID] = None
    file_path: Optional[str] = None
    display_name: str
    source_app: Optional[str] = None
    scenario: Optional[str] = None
    notes: Optional[str] = None
    status: str
    created_by: Optional[UUID] = None
    created_at: datetime


class ComparisonBasketItemCreate(BaseModel):
    asset_id: UUID


class ComparisonBasketItemOut(OrmModel):
    id: UUID
    asset: ComparisonAssetOut
    created_at: datetime


class ComparisonSkillCreate(BaseModel):
    name: str
    description: Optional[str] = None
    scenario_tags_json: list[str] = Field(default_factory=list)
    prompt: str
    output_schema_json: dict | list | None = None
    status: str = "active"


class ComparisonSkillUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    scenario_tags_json: Optional[list[str]] = None
    prompt: Optional[str] = None
    output_schema_json: dict | list | None = None
    status: Optional[str] = None


class ComparisonSkillOut(OrmModel):
    id: UUID
    name: str
    description: Optional[str] = None
    scenario_tags_json: list | dict | None = None
    prompt: str
    output_schema_json: dict | list | None = None
    status: str
    version: int
    created_by: Optional[UUID] = None
    updated_by: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime


class ComparisonReportCreate(BaseModel):
    asset_ids: list[UUID] = Field(default_factory=list)
    skill_id: UUID
    focus_question: Optional[str] = None


class ComparisonReportOut(OrmModel):
    id: UUID
    asset_ids_json: list
    skill_id: UUID
    skill_name: str
    skill_version: int
    focus_question: Optional[str] = None
    report: Optional[str] = None
    status: str
    error: Optional[str] = None
    created_by: Optional[UUID] = None
    created_at: datetime
    completed_at: Optional[datetime] = None


class TaskUpdate(BaseModel):
    name: Optional[str] = None
    analysis_skill_ids: Optional[List[UUID]] = None


class RetryTaskRequest(BaseModel):
    device_id: Optional[UUID] = None


class RunTaskRequest(BaseModel):
    device_id: Optional[UUID] = None


class DeviceOut(OrmModel):
    id: UUID
    serial: str
    name: Optional[str] = None
    status: str
    last_seen_at: Optional[datetime] = None
    current_task_run_id: Optional[UUID] = None
    notes: Optional[str] = None


class DeviceRefreshOut(BaseModel):
    devices: List[DeviceOut]
    adb_available: bool = True

class SearchQuery(BaseModel):
    query: str
    limit: int = 20
    offset: int = 0

class SearchResult(BaseModel):
    image: ImageOut
    analysis: Optional[AnalysisOut] = None
    similarity: Optional[float] = None
    search_mode: Optional[str] = None

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
    schedule_cycle: Literal["daily", "weekly", "monthly"] = "daily"
    schedule_start_date: Optional[date] = None
    schedule_end_date: Optional[date] = None
    analysis_skill_ids: List[UUID] = Field(default_factory=list)


class WatchPlanUpdate(BaseModel):
    name: Optional[str] = None
    target_app: Optional[str] = None
    target_page: Optional[str] = None
    entry_instruction: Optional[str] = None
    focus_question: Optional[str] = None
    schedule_time: Optional[time] = None
    schedule_cycle: Optional[Literal["daily", "weekly", "monthly"]] = None
    schedule_start_date: Optional[date] = None
    schedule_end_date: Optional[date] = None
    status: Optional[str] = None
    analysis_skill_ids: Optional[List[UUID]] = None


class WatchPlanOut(OrmModel):
    id: UUID
    name: str
    target_app: str
    target_page: str
    entry_instruction: str
    focus_question: Optional[str] = None
    capture_scope: str
    schedule_time: time
    schedule_cycle: Literal["daily", "weekly", "monthly"] = "daily"
    schedule_start_date: Optional[date] = None
    schedule_end_date: Optional[date] = None
    status: str
    pause_reason: Optional[str] = None
    last_run_at: Optional[datetime] = None
    run_count: int = 0
    latest_run_status: Optional[str] = None
    latest_success_run_at: Optional[datetime] = None
    created_by: Optional[UUID] = None
    updated_by: Optional[UUID] = None
    created_by_name: Optional[str] = None
    updated_by_name: Optional[str] = None
    analysis_skill_ids: OptionalUUIDList = Field(default_factory=list)
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
