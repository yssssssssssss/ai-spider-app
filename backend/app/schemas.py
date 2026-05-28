from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
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
