from datetime import date, datetime, time
from typing import List, Optional
from pydantic import BaseModel, Field
from uuid import UUID

class ImageBase(BaseModel):
    file_path: str
    oss_url: Optional[str] = None
    oss_key: Optional[str] = None
    source_app: Optional[str] = None
    scenario: Optional[str] = None
    captured_at: Optional[datetime] = None

class ImageCreate(ImageBase):
    task_id: Optional[UUID] = None

class ImageOut(ImageBase):
    id: UUID
    task_id: Optional[UUID] = None
    created_at: datetime
    class Config:
        from_attributes = True

class AnalysisOut(BaseModel):
    id: UUID
    image_id: UUID
    design_analysis: Optional[str] = None
    ops_analysis: Optional[str] = None
    status: str
    analyzed_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class RequestCreate(BaseModel):
    target_app: Optional[str] = None
    target_scenario: Optional[str] = None
    keywords: List[str] = []
    description: Optional[str] = None

class RequestOut(BaseModel):
    id: UUID
    user_id: str
    target_app: Optional[str] = None
    target_scenario: Optional[str] = None
    keywords: List[str]
    description: Optional[str] = None
    status: str
    created_at: datetime
    class Config:
        from_attributes = True

class TaskOut(BaseModel):
    id: UUID
    request_id: Optional[UUID] = None
    name: Optional[str] = None
    keyword: Optional[str] = None
    target_app: Optional[str] = None
    target_scenario: Optional[str] = None
    mode: str = "uiautomator2"
    generated_instruction: Optional[str] = None
    status: str
    admin_id: Optional[str] = None
    approved_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    class Config:
        from_attributes = True

class SearchQuery(BaseModel):
    query: str
    limit: int = 20
    offset: int = 0

class SearchResult(BaseModel):
    image: ImageOut
    analysis: Optional[AnalysisOut] = None
    similarity: Optional[float] = None

class ApproveRequest(BaseModel):
    admin_id: str
    keyword: Optional[str] = None
    target_app: Optional[str] = None
    target_scenario: Optional[str] = None
    mode: str = "uiautomator2"  # "uiautomator2" | "autoglm"

class RejectRequest(BaseModel):
    admin_id: str
    reason: Optional[str] = None


class WatchPlanCreate(BaseModel):
    name: str
    target_app: str
    target_page: str
    entry_instruction: str
    focus_question: Optional[str] = None
    schedule_time: time = time(10, 0)


class WatchPlanUpdate(BaseModel):
    name: Optional[str] = None
    target_app: Optional[str] = None
    target_page: Optional[str] = None
    entry_instruction: Optional[str] = None
    focus_question: Optional[str] = None
    schedule_time: Optional[time] = None
    status: Optional[str] = None


class WatchPlanOut(BaseModel):
    id: UUID
    name: str
    target_app: str
    target_page: str
    entry_instruction: str
    focus_question: Optional[str] = None
    capture_scope: str
    schedule_time: time
    status: str
    pause_reason: Optional[str] = None
    last_run_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    class Config:
        from_attributes = True


class WatchRunOut(BaseModel):
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
    class Config:
        from_attributes = True


class WatchSnapshotOut(BaseModel):
    id: UUID
    watch_run_id: UUID
    image_id: UUID
    is_primary: bool
    page_signature: Optional[str] = None
    created_at: datetime
    class Config:
        from_attributes = True


class WatchDailySummaryOut(BaseModel):
    id: UUID
    watch_run_id: UUID
    summary: Optional[str] = None
    design_summary: Optional[str] = None
    ops_summary: Optional[str] = None
    key_modules_json: list | dict | None = None
    promotions_json: list | dict | None = None
    changes_from_previous_json: dict | list | None = None
    created_at: datetime
    class Config:
        from_attributes = True


class WatchPeriodReportOut(BaseModel):
    id: UUID
    watch_plan_id: UUID
    period_days: int
    date_from: date
    date_to: date
    report: Optional[str] = None
    structured_json: dict | list | None = None
    created_at: datetime
    class Config:
        from_attributes = True


class WatchPlanDetailOut(BaseModel):
    plan: WatchPlanOut
    latest_run: Optional[WatchRunOut] = None
    latest_snapshot: Optional[SearchResult] = None
    latest_summary: Optional[WatchDailySummaryOut] = None
    period_reports: List[WatchPeriodReportOut] = Field(default_factory=list)
    recent_runs: List[WatchRunOut] = Field(default_factory=list)
