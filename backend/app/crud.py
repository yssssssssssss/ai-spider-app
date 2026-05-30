from uuid import UUID
from typing import List, Optional
from datetime import date, datetime
from sqlalchemy.orm import Session
from sqlalchemy import func, or_

from app import models, schemas

def create_image(db: Session, image: schemas.ImageCreate) -> models.Image:
    existing = get_image_by_file_and_task(db, image.file_path, image.task_id)
    if existing:
        data = image.model_dump()
        for field in ("oss_url", "oss_key", "source_app", "scenario", "captured_at"):
            value = data.get(field)
            if value is not None and getattr(existing, field) != value:
                setattr(existing, field, value)
        db.commit()
        db.refresh(existing)
        return existing
    db_image = models.Image(**image.model_dump())
    db.add(db_image)
    db.commit()
    db.refresh(db_image)
    return db_image

def get_image(db: Session, image_id: UUID) -> Optional[models.Image]:
    return db.query(models.Image).filter(models.Image.id == image_id).first()

def get_image_by_file_and_task(db: Session, file_path: str, task_id: Optional[UUID]) -> Optional[models.Image]:
    q = db.query(models.Image).filter(models.Image.file_path == file_path)
    if task_id is None:
        q = q.filter(models.Image.task_id.is_(None))
    else:
        q = q.filter(models.Image.task_id == task_id)
    return q.first()

def list_images(db: Session, skip: int = 0, limit: int = 100, task_id: Optional[UUID] = None) -> List[models.Image]:
    q = db.query(models.Image)
    if task_id is not None:
        q = q.filter(models.Image.task_id == task_id)
    return q.order_by(models.Image.created_at.desc()).offset(skip).limit(limit).all()

def create_analysis(db: Session, image_id: UUID, design: str, ops: str, status: str = "success") -> models.Analysis:
    db_analysis = get_analysis_by_image(db, image_id)
    if db_analysis:
        db_analysis.design_analysis = design
        db_analysis.ops_analysis = ops
        db_analysis.status = status
        db_analysis.analyzed_at = func.now()
    else:
        db_analysis = models.Analysis(
            image_id=image_id,
            design_analysis=design,
            ops_analysis=ops,
            status=status,
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

def create_task(db: Session, name: str, keyword: str, target_app: Optional[str], target_scenario: Optional[str], request_id: Optional[UUID] = None, admin_id: Optional[str] = None, mode: str = "uiautomator2") -> models.Task:
    db_task = models.Task(
        name=name,
        keyword=keyword,
        target_app=target_app,
        target_scenario=target_scenario,
        mode=mode,
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
    return q.order_by(
        models.Task.completed_at.desc().nullslast(),
        models.Task.approved_at.desc().nullslast(),
    ).offset(skip).limit(limit).all()

def update_task_status(db: Session, task_id: UUID, status: str) -> Optional[models.Task]:
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if task:
        task.status = status
        if status == "completed":
            task.completed_at = func.now()
        db.commit()
        db.refresh(task)
    return task

def update_task_instruction(db: Session, task_id: UUID, instruction: str) -> Optional[models.Task]:
    """更新任务的 LLM 生成指令"""
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if task:
        task.generated_instruction = instruction
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
        models.Embedding.embedding.l2_distance(vector)
    ).offset(offset).limit(limit).all()
    return results

def search_by_text(db: Session, query: str, limit: int = 20, offset: int = 0) -> List:
    """向量服务不可用时的文本兜底搜索，返回 (analysis, image) 结果。"""
    normalized = query.strip()
    q = db.query(models.Analysis, models.Image).join(
        models.Image, models.Analysis.image_id == models.Image.id
    )
    if normalized:
        pattern = f"%{normalized}%"
        q = q.filter(or_(
            models.Analysis.design_analysis.ilike(pattern),
            models.Analysis.ops_analysis.ilike(pattern),
            models.Image.source_app.ilike(pattern),
            models.Image.scenario.ilike(pattern),
            models.Image.file_path.ilike(pattern),
        ))
    return q.order_by(models.Analysis.analyzed_at.desc().nullslast()).offset(offset).limit(limit).all()


def create_watch_plan(db: Session, plan: schemas.WatchPlanCreate) -> models.WatchPlan:
    now = datetime.now()
    db_plan = models.WatchPlan(
        **plan.model_dump(),
        status="active",
        capture_scope="first_screen",
        created_at=now,
        updated_at=now,
    )
    db.add(db_plan)
    db.commit()
    db.refresh(db_plan)
    return db_plan


def list_watch_plans(db: Session, status: Optional[str] = None, skip: int = 0, limit: int = 100) -> List[models.WatchPlan]:
    q = db.query(models.WatchPlan)
    if status:
        q = q.filter(models.WatchPlan.status == status)
    return q.order_by(models.WatchPlan.updated_at.desc().nullslast()).offset(skip).limit(limit).all()


def get_watch_plan(db: Session, plan_id: UUID) -> Optional[models.WatchPlan]:
    return db.query(models.WatchPlan).filter(models.WatchPlan.id == plan_id).first()


def update_watch_plan(db: Session, plan_id: UUID, patch: schemas.WatchPlanUpdate) -> Optional[models.WatchPlan]:
    plan = get_watch_plan(db, plan_id)
    if not plan:
        return None
    data = patch.model_dump(exclude_unset=True)
    for field, value in data.items():
        if value is not None:
            setattr(plan, field, value)
    plan.updated_at = datetime.now()
    db.commit()
    db.refresh(plan)
    return plan


def set_watch_plan_status(db: Session, plan_id: UUID, status: str, pause_reason: Optional[str] = None) -> Optional[models.WatchPlan]:
    plan = get_watch_plan(db, plan_id)
    if not plan:
        return None
    plan.status = status
    plan.pause_reason = pause_reason if status == "paused" else None
    plan.updated_at = datetime.now()
    db.commit()
    db.refresh(plan)
    return plan


def get_watch_run_by_date(db: Session, plan_id: UUID, run_date: date) -> Optional[models.WatchRun]:
    return (
        db.query(models.WatchRun)
        .filter(models.WatchRun.watch_plan_id == plan_id)
        .filter(models.WatchRun.run_date == run_date)
        .first()
    )


def create_watch_run(db: Session, plan_id: UUID, run_date: date, attempt_count: int = 1) -> models.WatchRun:
    existing = get_watch_run_by_date(db, plan_id, run_date)
    if existing:
        return existing
    db_run = models.WatchRun(
        watch_plan_id=plan_id,
        run_date=run_date,
        attempt_count=attempt_count,
        status="pending",
    )
    db.add(db_run)
    db.commit()
    db.refresh(db_run)
    return db_run


def get_watch_run(db: Session, run_id: UUID) -> Optional[models.WatchRun]:
    return db.query(models.WatchRun).filter(models.WatchRun.id == run_id).first()


def list_watch_runs(db: Session, plan_id: UUID, skip: int = 0, limit: int = 30) -> List[models.WatchRun]:
    return (
        db.query(models.WatchRun)
        .filter(models.WatchRun.watch_plan_id == plan_id)
        .order_by(models.WatchRun.run_date.desc(), models.WatchRun.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def update_watch_run(
    db: Session,
    run_id: UUID,
    *,
    status: Optional[str] = None,
    task_id: Optional[UUID] = None,
    attempt_count: Optional[int] = None,
    failure_reason: Optional[str] = None,
    screenshot_count: Optional[int] = None,
    valid_snapshot_count: Optional[int] = None,
    completed_at: Optional[datetime] = None,
) -> Optional[models.WatchRun]:
    run = get_watch_run(db, run_id)
    if not run:
        return None
    if status is not None:
        run.status = status
    if task_id is not None:
        run.task_id = task_id
    if attempt_count is not None:
        run.attempt_count = attempt_count
    if failure_reason is not None:
        run.failure_reason = failure_reason
    if screenshot_count is not None:
        run.screenshot_count = screenshot_count
    if valid_snapshot_count is not None:
        run.valid_snapshot_count = valid_snapshot_count
    if completed_at is not None:
        run.completed_at = completed_at
    db.commit()
    db.refresh(run)
    return run


def create_watch_snapshot(
    db: Session,
    run_id: UUID,
    image_id: UUID,
    *,
    is_primary: bool = False,
    page_signature: Optional[str] = None,
) -> models.WatchSnapshot:
    existing = (
        db.query(models.WatchSnapshot)
        .filter(models.WatchSnapshot.watch_run_id == run_id)
        .filter(models.WatchSnapshot.image_id == image_id)
        .first()
    )
    if existing:
        existing.is_primary = is_primary or existing.is_primary
        existing.page_signature = page_signature or existing.page_signature
        db.commit()
        db.refresh(existing)
        return existing
    snapshot = models.WatchSnapshot(
        watch_run_id=run_id,
        image_id=image_id,
        is_primary=is_primary,
        page_signature=page_signature,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def list_watch_snapshots(db: Session, run_id: UUID) -> List[models.WatchSnapshot]:
    return (
        db.query(models.WatchSnapshot)
        .filter(models.WatchSnapshot.watch_run_id == run_id)
        .order_by(models.WatchSnapshot.is_primary.desc(), models.WatchSnapshot.created_at.asc())
        .all()
    )


def create_watch_daily_summary(
    db: Session,
    run_id: UUID,
    *,
    summary: str,
    design_summary: str,
    ops_summary: str,
    key_modules_json,
    promotions_json,
    changes_from_previous_json,
) -> models.WatchDailySummary:
    existing = db.query(models.WatchDailySummary).filter(models.WatchDailySummary.watch_run_id == run_id).first()
    if existing:
        existing.summary = summary
        existing.design_summary = design_summary
        existing.ops_summary = ops_summary
        existing.key_modules_json = key_modules_json
        existing.promotions_json = promotions_json
        existing.changes_from_previous_json = changes_from_previous_json
        db.commit()
        db.refresh(existing)
        return existing
    daily = models.WatchDailySummary(
        watch_run_id=run_id,
        summary=summary,
        design_summary=design_summary,
        ops_summary=ops_summary,
        key_modules_json=key_modules_json,
        promotions_json=promotions_json,
        changes_from_previous_json=changes_from_previous_json,
    )
    db.add(daily)
    db.commit()
    db.refresh(daily)
    return daily


def get_latest_success_watch_run_before(db: Session, plan_id: UUID, before_date: date) -> Optional[models.WatchRun]:
    return (
        db.query(models.WatchRun)
        .filter(models.WatchRun.watch_plan_id == plan_id)
        .filter(models.WatchRun.run_date < before_date)
        .filter(models.WatchRun.status == "success")
        .order_by(models.WatchRun.run_date.desc())
        .first()
    )


def list_watch_daily_summaries(db: Session, plan_id: UUID, limit: int) -> List[models.WatchDailySummary]:
    return (
        db.query(models.WatchDailySummary)
        .join(models.WatchRun, models.WatchDailySummary.watch_run_id == models.WatchRun.id)
        .filter(models.WatchRun.watch_plan_id == plan_id)
        .filter(models.WatchRun.status == "success")
        .order_by(models.WatchRun.run_date.desc())
        .limit(limit)
        .all()
    )


def create_watch_period_report(
    db: Session,
    plan_id: UUID,
    *,
    period_days: int,
    date_from: date,
    date_to: date,
    report: str,
    structured_json,
) -> models.WatchPeriodReport:
    existing = (
        db.query(models.WatchPeriodReport)
        .filter(models.WatchPeriodReport.watch_plan_id == plan_id)
        .filter(models.WatchPeriodReport.period_days == period_days)
        .filter(models.WatchPeriodReport.date_to == date_to)
        .first()
    )
    if existing:
        existing.date_from = date_from
        existing.report = report
        existing.structured_json = structured_json
        existing.created_at = datetime.now()
        db.commit()
        db.refresh(existing)
        return existing
    period = models.WatchPeriodReport(
        watch_plan_id=plan_id,
        period_days=period_days,
        date_from=date_from,
        date_to=date_to,
        report=report,
        structured_json=structured_json,
    )
    db.add(period)
    db.commit()
    db.refresh(period)
    return period


def list_watch_period_reports(
    db: Session,
    plan_id: UUID,
    period_days: Optional[int] = None,
    limit: int = 10,
) -> List[models.WatchPeriodReport]:
    q = db.query(models.WatchPeriodReport).filter(models.WatchPeriodReport.watch_plan_id == plan_id)
    if period_days is not None:
        q = q.filter(models.WatchPeriodReport.period_days == period_days)
    return q.order_by(models.WatchPeriodReport.date_to.desc(), models.WatchPeriodReport.created_at.desc()).limit(limit).all()
