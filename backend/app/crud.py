from uuid import UUID
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from pgvector.sqlalchemy import L2Distance
from app import models, schemas

def create_image(db: Session, image: schemas.ImageCreate) -> models.Image:
    db_image = models.Image(**image.model_dump())
    db.add(db_image)
    db.commit()
    db.refresh(db_image)
    return db_image

def get_image(db: Session, image_id: UUID) -> Optional[models.Image]:
    return db.query(models.Image).filter(models.Image.id == image_id).first()

def list_images(db: Session, skip: int = 0, limit: int = 100) -> List[models.Image]:
    return db.query(models.Image).offset(skip).limit(limit).all()

def create_analysis(db: Session, image_id: UUID, design: str, ops: str) -> models.Analysis:
    db_analysis = models.Analysis(
        image_id=image_id,
        design_analysis=design,
        ops_analysis=ops,
        status="success",
        analyzed_at=func.now()
    )
    db.add(db_analysis)
    db.commit()
    db.refresh(db_analysis)
    return db_analysis

def get_analysis_by_image(db: Session, image_id: UUID) -> Optional[models.Analysis]:
    return db.query(models.Analysis).filter(models.Analysis.image_id == image_id).first()

def create_request(db: Session, req: schemas.RequestCreate) -> models.Request:
    db_req = models.Request(**req.model_dump())
    db.add(db_req)
    db.commit()
    db.refresh(db_req)
    return db_req

def get_request(db: Session, request_id: UUID) -> Optional[models.Request]:
    return db.query(models.Request).filter(models.Request.id == request_id).first()

def list_requests(db: Session, status: Optional[str] = None, skip: int = 0, limit: int = 100) -> List[models.Request]:
    q = db.query(models.Request)
    if status:
        q = q.filter(models.Request.status == status)
    return q.offset(skip).limit(limit).all()

def update_request_status(db: Session, request_id: UUID, status: str) -> Optional[models.Request]:
    req = db.query(models.Request).filter(models.Request.id == request_id).first()
    if req:
        req.status = status
        db.commit()
        db.refresh(req)
    return req

def create_task(db: Session, name: str, keyword: str, target_app: Optional[str], target_scenario: Optional[str], request_id: Optional[UUID] = None, admin_id: Optional[str] = None) -> models.Task:
    db_task = models.Task(
        name=name,
        keyword=keyword,
        target_app=target_app,
        target_scenario=target_scenario,
        request_id=request_id,
        admin_id=admin_id,
        status="pending",
        approved_at=func.now() if admin_id else None
    )
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task

def get_task(db: Session, task_id: UUID) -> Optional[models.Task]:
    return db.query(models.Task).filter(models.Task.id == task_id).first()

def list_tasks(db: Session, status: Optional[str] = None, skip: int = 0, limit: int = 100) -> List[models.Task]:
    q = db.query(models.Task)
    if status:
        q = q.filter(models.Task.status == status)
    return q.offset(skip).limit(limit).all()

def update_task_status(db: Session, task_id: UUID, status: str) -> Optional[models.Task]:
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if task:
        task.status = status
        if status == "completed":
            task.completed_at = func.now()
        db.commit()
        db.refresh(task)
    return task

def create_embedding(db: Session, analysis_id: UUID, vector: List[float], content_type: str) -> models.Embedding:
    db_emb = models.Embedding(
        analysis_id=analysis_id,
        embedding=vector,
        content_type=content_type
    )
    db.add(db_emb)
    db.commit()
    db.refresh(db_emb)
    return db_emb

def search_by_embedding(db: Session, vector: List[float], limit: int = 20, offset: int = 0) -> List:
    """通过向量相似度搜索，返回 (embedding, analysis, image) 结果"""
    results = db.query(models.Embedding, models.Analysis, models.Image).join(
        models.Analysis, models.Embedding.analysis_id == models.Analysis.id
    ).join(
        models.Image, models.Analysis.image_id == models.Image.id
    ).order_by(
        L2Distance(models.Embedding.embedding, vector)
    ).offset(offset).limit(limit).all()
    return results
