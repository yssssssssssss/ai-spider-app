from uuid import UUID
from typing import List, Optional
from datetime import date, datetime
from sqlalchemy.orm import Session
from sqlalchemy import String, func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app import models, schemas

REGISTRATION_INVITE_CODE_KEY = "registration_invite_code"

def create_image(db: Session, image: schemas.ImageCreate) -> models.Image:
    existing = get_image_by_file_and_task(db, image.file_path, image.task_id)
    if existing:
        data = image.model_dump()
        for field in ("oss_url", "oss_key", "source_app", "scenario", "captured_at", "task_run_id", "device_id"):
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


def get_image_for_user(db: Session, image_id: UUID, user_id: UUID) -> Optional[models.Image]:
    return (
        db.query(models.Image)
        .join(models.Task, models.Image.task_id == models.Task.id)
        .filter(models.Image.id == image_id)
        .filter(models.Task.created_by == user_id)
        .first()
    )

def get_image_by_file_and_task(db: Session, file_path: str, task_id: Optional[UUID]) -> Optional[models.Image]:
    q = db.query(models.Image).filter(models.Image.file_path == file_path)
    if task_id is None:
        q = q.filter(models.Image.task_id.is_(None))
    else:
        q = q.filter(models.Image.task_id == task_id)
    return q.first()

def list_images(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    task_id: Optional[UUID] = None,
    analysis_status: Optional[str] = None,
    embedding_status: Optional[str] = None,
    user_id: Optional[UUID] = None,
) -> List[models.Image]:
    q = db.query(models.Image)
    if user_id is not None:
        q = q.join(models.Task, models.Image.task_id == models.Task.id).filter(models.Task.created_by == user_id)
    if task_id is not None:
        q = q.filter(models.Image.task_id == task_id)
    if analysis_status or embedding_status:
        q = q.outerjoin(models.Analysis, models.Analysis.image_id == models.Image.id)
    if analysis_status:
        if analysis_status == "pending":
            q = q.filter(or_(models.Analysis.status == "pending", models.Analysis.id.is_(None)))
        else:
            q = q.filter(models.Analysis.status == analysis_status)
    if embedding_status:
        if embedding_status == "pending":
            q = q.filter(or_(models.Analysis.embedding_status == "pending", models.Analysis.id.is_(None)))
        else:
            q = q.filter(models.Analysis.embedding_status == embedding_status)
    return q.order_by(models.Image.created_at.desc()).offset(skip).limit(limit).all()

def create_analysis(
    db: Session,
    image_id: UUID,
    design: str,
    ops: str,
    status: str = "success",
    custom_analysis_json: Optional[dict] = None,
) -> models.Analysis:
    db_analysis = get_analysis_by_image(db, image_id)
    if db_analysis:
        db_analysis.design_analysis = design
        db_analysis.ops_analysis = ops
        db_analysis.custom_analysis_json = custom_analysis_json or {}
        db_analysis.status = status
        db_analysis.embedding_status = "pending"
        db_analysis.embedding_error = None
        db_analysis.analyzed_at = func.now()
    else:
        db_analysis = models.Analysis(
            image_id=image_id,
            design_analysis=design,
            ops_analysis=ops,
            custom_analysis_json=custom_analysis_json or {},
            status=status,
            embedding_status="pending",
            analyzed_at=func.now()
        )
        db.add(db_analysis)
    db.commit()
    db.refresh(db_analysis)
    return db_analysis


def update_embedding_status(
    db: Session,
    analysis_id: UUID,
    status: str,
    error: Optional[str] = None,
) -> Optional[models.Analysis]:
    analysis = db.query(models.Analysis).filter(models.Analysis.id == analysis_id).first()
    if not analysis:
        return None
    analysis.embedding_status = status
    analysis.embedding_error = error
    db.commit()
    db.refresh(analysis)
    return analysis


def get_analysis_by_image(db: Session, image_id: UUID) -> Optional[models.Analysis]:
    return db.query(models.Analysis).filter(models.Analysis.image_id == image_id).first()

def create_request(
    db: Session,
    req: schemas.RequestCreate,
    user_id: Optional[str] = None,
    analysis_skill_snapshots: Optional[list[dict]] = None,
    comparison_config: Optional[dict] = None,
) -> models.Request:
    data = req.model_dump()
    data.pop("analysis_skill_ids", None)
    data.pop("comparison", None)
    if user_id:
        data["user_id"] = user_id
    data["analysis_skill_snapshots_json"] = analysis_skill_snapshots or []
    data["comparison_config_json"] = comparison_config or {}
    data["compare_jd_enabled"] = bool(req.compare_jd_enabled and comparison_config)
    db_req = models.Request(**data)
    db.add(db_req)
    db.commit()
    db.refresh(db_req)
    return db_req

def get_request(db: Session, request_id: UUID) -> Optional[models.Request]:
    return db.query(models.Request).filter(models.Request.id == request_id).first()


def get_request_for_user(db: Session, request_id: UUID, user_id: UUID) -> Optional[models.Request]:
    return (
        db.query(models.Request)
        .filter(models.Request.id == request_id)
        .filter(models.Request.user_id == str(user_id))
        .first()
    )


def list_requests(
    db: Session,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    user_id: Optional[UUID] = None,
) -> List[models.Request]:
    q = db.query(models.Request)
    if user_id is not None:
        q = q.filter(models.Request.user_id == str(user_id))
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


def approve_request(db: Session, request_id: UUID, approved_task_mode: str) -> Optional[models.Request]:
    req = db.query(models.Request).filter(models.Request.id == request_id).first()
    if req:
        req.status = "approved"
        req.approved_task_mode = approved_task_mode
        db.commit()
        db.refresh(req)
    return req


def list_scheduled_requests(
    db: Session,
    *,
    status: str = "approved",
    limit: int = 1000,
) -> List[models.Request]:
    return (
        db.query(models.Request)
        .filter(models.Request.status == status)
        .filter(models.Request.schedule_enabled.is_(True))
        .order_by(models.Request.created_at.asc())
        .limit(limit)
        .all()
    )

def create_task(
    db: Session,
    name: str,
    keyword: str,
    target_app: Optional[str],
    target_scenario: Optional[str],
    request_id: Optional[UUID] = None,
    admin_id: Optional[str] = None,
    mode: str = "uiautomator2",
    scheduled_run_date: Optional[date] = None,
    created_by: Optional[UUID] = None,
    approved_by: Optional[UUID] = None,
    run_by: Optional[UUID] = None,
    target_goals_json: Optional[list | dict] = None,
    analysis_skill_snapshots: Optional[list[dict]] = None,
) -> models.Task:
    db_task = models.Task(
        name=name,
        keyword=keyword,
        target_app=target_app,
        target_scenario=target_scenario,
        scheduled_run_date=scheduled_run_date,
        mode=mode,
        request_id=request_id,
        admin_id=admin_id,
        created_by=created_by,
        approved_by=approved_by,
        run_by=run_by,
        target_goals_json=target_goals_json or [],
        analysis_skill_snapshots_json=analysis_skill_snapshots or [],
        status="pending",
        approved_at=func.now() if admin_id or approved_by else None
    )
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    return db_task


def create_comparison_group(
    db: Session,
    *,
    request_id: UUID,
    baseline_app: str,
    jd_instruction: str,
    status: str = "pending",
) -> models.ComparisonGroup:
    group = models.ComparisonGroup(
        request_id=request_id,
        baseline_app=baseline_app,
        jd_instruction=jd_instruction,
        status=status,
    )
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


def update_comparison_group_jd_task(
    db: Session,
    group_id: UUID,
    jd_task_id: UUID,
    *,
    status: Optional[str] = None,
) -> Optional[models.ComparisonGroup]:
    group = db.query(models.ComparisonGroup).filter(models.ComparisonGroup.id == group_id).first()
    if not group:
        return None
    group.jd_task_id = jd_task_id
    if status is not None:
        group.status = status
    group.updated_at = datetime.now()
    db.commit()
    db.refresh(group)
    return group


def create_comparison_group_app(
    db: Session,
    comparison_group_id: UUID,
    app_name: str,
    task_id: Optional[UUID],
    *,
    status: str = "pending",
) -> models.ComparisonGroupApp:
    row = models.ComparisonGroupApp(
        comparison_group_id=comparison_group_id,
        app_name=app_name,
        task_id=task_id,
        status=status,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def create_comparison_slot(
    db: Session,
    comparison_group_id: UUID,
    slot_key: str,
    name: str,
    description: str,
    required: bool,
    sort_order: int,
) -> models.ComparisonSlot:
    slot = models.ComparisonSlot(
        comparison_group_id=comparison_group_id,
        slot_key=slot_key,
        name=name,
        description=description,
        required=required,
        sort_order=sort_order,
    )
    db.add(slot)
    db.commit()
    db.refresh(slot)
    return slot


def get_comparison_group_by_request(db: Session, request_id: UUID) -> Optional[models.ComparisonGroup]:
    return db.query(models.ComparisonGroup).filter(models.ComparisonGroup.request_id == request_id).first()


def get_comparison_group_by_task(db: Session, task_id: UUID) -> Optional[models.ComparisonGroup]:
    group = db.query(models.ComparisonGroup).filter(models.ComparisonGroup.jd_task_id == task_id).first()
    if group:
        return group
    return (
        db.query(models.ComparisonGroup)
        .join(models.ComparisonGroupApp, models.ComparisonGroupApp.comparison_group_id == models.ComparisonGroup.id)
        .filter(models.ComparisonGroupApp.task_id == task_id)
        .first()
    )


def get_comparison_group_app_by_task(db: Session, task_id: UUID) -> Optional[models.ComparisonGroupApp]:
    return db.query(models.ComparisonGroupApp).filter(models.ComparisonGroupApp.task_id == task_id).first()


def list_comparison_group_apps(db: Session, group_id: UUID) -> List[models.ComparisonGroupApp]:
    return (
        db.query(models.ComparisonGroupApp)
        .filter(models.ComparisonGroupApp.comparison_group_id == group_id)
        .order_by(models.ComparisonGroupApp.app_name.asc())
        .all()
    )


def list_comparison_slots(db: Session, group_id: UUID) -> List[models.ComparisonSlot]:
    return (
        db.query(models.ComparisonSlot)
        .filter(models.ComparisonSlot.comparison_group_id == group_id)
        .order_by(models.ComparisonSlot.sort_order.asc(), models.ComparisonSlot.created_at.asc())
        .all()
    )


def create_comparison_slot_match(
    db: Session,
    comparison_group_id: UUID,
    slot_id: Optional[UUID],
    app_name: str,
    task_id: UUID,
    image_id: UUID,
    confidence: float,
    status: str,
    reason: Optional[str] = None,
) -> models.ComparisonSlotMatch:
    def delete_stale_pair_analyses(match: models.ComparisonSlotMatch) -> None:
        if not match.slot_id:
            return
        if match.app_name == "京东":
            app_ids = (
                db.query(models.ComparisonGroupApp.id)
                .filter(models.ComparisonGroupApp.comparison_group_id == match.comparison_group_id)
            )
            stale_pairs = (
                db.query(models.ComparisonPairAnalysis)
                .filter(models.ComparisonPairAnalysis.slot_id == match.slot_id)
                .filter(models.ComparisonPairAnalysis.comparison_group_app_id.in_(app_ids))
                .all()
            )
        else:
            group_app = (
                db.query(models.ComparisonGroupApp)
                .filter(models.ComparisonGroupApp.comparison_group_id == match.comparison_group_id)
                .filter(models.ComparisonGroupApp.app_name == match.app_name)
                .first()
            )
            stale_pairs = (
                db.query(models.ComparisonPairAnalysis)
                .filter(models.ComparisonPairAnalysis.slot_id == match.slot_id)
                .filter(models.ComparisonPairAnalysis.comparison_group_app_id == group_app.id)
                .all()
                if group_app else []
            )
        for pair in stale_pairs:
            db.delete(pair)

    existing_image = (
        db.query(models.ComparisonSlotMatch)
        .filter(models.ComparisonSlotMatch.image_id == image_id)
        .first()
    )
    if existing_image:
        return existing_image

    if status == "matched" and slot_id is not None:
        locked = (
            db.query(models.ComparisonSlotMatch)
            .filter(models.ComparisonSlotMatch.comparison_group_id == comparison_group_id)
            .filter(models.ComparisonSlotMatch.slot_id == slot_id)
            .filter(models.ComparisonSlotMatch.app_name == app_name)
            .filter(models.ComparisonSlotMatch.status == "matched")
            .order_by(models.ComparisonSlotMatch.confidence.desc(), models.ComparisonSlotMatch.created_at.asc())
            .first()
        )
        if locked:
            if confidence > locked.confidence:
                delete_stale_pair_analyses(locked)
                locked.task_id = task_id
                locked.image_id = image_id
                locked.confidence = confidence
                locked.reason = reason
                db.commit()
                db.refresh(locked)
            return locked

    match = models.ComparisonSlotMatch(
        comparison_group_id=comparison_group_id,
        slot_id=slot_id,
        app_name=app_name,
        task_id=task_id,
        image_id=image_id,
        confidence=confidence,
        status=status,
        reason=reason,
    )
    db.add(match)
    db.commit()
    db.refresh(match)
    return match


def list_comparison_slot_matches(db: Session, group_id: UUID) -> List[models.ComparisonSlotMatch]:
    return (
        db.query(models.ComparisonSlotMatch)
        .filter(models.ComparisonSlotMatch.comparison_group_id == group_id)
        .order_by(models.ComparisonSlotMatch.created_at.asc())
        .all()
    )


def get_comparison_pair_analysis(
    db: Session,
    comparison_group_app_id: UUID,
    slot_id: UUID,
) -> Optional[models.ComparisonPairAnalysis]:
    return (
        db.query(models.ComparisonPairAnalysis)
        .filter(models.ComparisonPairAnalysis.comparison_group_app_id == comparison_group_app_id)
        .filter(models.ComparisonPairAnalysis.slot_id == slot_id)
        .first()
    )


def create_comparison_pair_analysis(
    db: Session,
    comparison_group_app_id: UUID,
    slot_id: UUID,
    a_image_id: UUID,
    jd_image_id: UUID,
    custom_analysis_json: Optional[dict] = None,
    *,
    status: str = "pending",
    error: Optional[str] = None,
) -> models.ComparisonPairAnalysis:
    existing = get_comparison_pair_analysis(db, comparison_group_app_id, slot_id)
    if existing:
        return existing
    analysis = models.ComparisonPairAnalysis(
        comparison_group_app_id=comparison_group_app_id,
        slot_id=slot_id,
        a_image_id=a_image_id,
        jd_image_id=jd_image_id,
        custom_analysis_json=custom_analysis_json or {},
        status=status,
        error=error,
        analyzed_at=func.now() if status in ("success", "partial", "failed") else None,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return analysis


def update_comparison_pair_analysis(
    db: Session,
    pair_id: UUID,
    *,
    custom_analysis_json: Optional[dict] = None,
    status: Optional[str] = None,
    error: Optional[str] = None,
) -> Optional[models.ComparisonPairAnalysis]:
    pair = db.query(models.ComparisonPairAnalysis).filter(models.ComparisonPairAnalysis.id == pair_id).first()
    if not pair:
        return None
    if custom_analysis_json is not None:
        pair.custom_analysis_json = custom_analysis_json
    if status is not None:
        pair.status = status
    pair.error = error
    if status in ("success", "partial", "failed"):
        pair.analyzed_at = func.now()
    pair.updated_at = datetime.now()
    db.commit()
    db.refresh(pair)
    return pair


def get_scheduled_task_for_request_date(
    db: Session,
    request_id: UUID,
    run_date: date,
) -> Optional[models.Task]:
    return (
        db.query(models.Task)
        .filter(models.Task.request_id == request_id)
        .filter(models.Task.scheduled_run_date == run_date)
        .first()
    )

def get_task(db: Session, task_id: UUID) -> Optional[models.Task]:
    return db.query(models.Task).filter(models.Task.id == task_id).first()


def get_task_for_user(db: Session, task_id: UUID, user_id: UUID) -> Optional[models.Task]:
    return (
        db.query(models.Task)
        .filter(models.Task.id == task_id)
        .filter(models.Task.created_by == user_id)
        .first()
    )


def list_tasks(
    db: Session,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    user_id: Optional[UUID] = None,
) -> List[models.Task]:
    q = db.query(models.Task)
    if user_id is not None:
        q = q.filter(models.Task.created_by == user_id)
    if status:
        q = q.filter(models.Task.status == status)
    return q.order_by(
        models.Task.completed_at.desc().nullslast(),
        models.Task.approved_at.desc().nullslast(),
    ).offset(skip).limit(limit).all()


def publish_task_to_blackboard(db: Session, task_id: UUID, published_by: Optional[UUID]) -> Optional[models.BlackboardPost]:
    task = get_task(db, task_id)
    if not task:
        return None
    existing = db.query(models.BlackboardPost).filter(models.BlackboardPost.task_id == task_id).first()
    if existing:
        return existing
    post = models.BlackboardPost(task_id=task_id, published_by=published_by)
    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def unpublish_task_from_blackboard(db: Session, task_id: UUID) -> bool:
    post = db.query(models.BlackboardPost).filter(models.BlackboardPost.task_id == task_id).first()
    if not post:
        return False
    db.delete(post)
    db.commit()
    return True


def get_blackboard_post_by_task(db: Session, task_id: UUID) -> Optional[models.BlackboardPost]:
    return db.query(models.BlackboardPost).filter(models.BlackboardPost.task_id == task_id).first()


def list_blackboard_posts(db: Session, skip: int = 0, limit: int = 100) -> List[models.BlackboardPost]:
    return (
        db.query(models.BlackboardPost)
        .join(models.Task, models.BlackboardPost.task_id == models.Task.id)
        .order_by(models.BlackboardPost.published_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_blackboard_image(db: Session, image_id: UUID) -> Optional[models.Image]:
    return (
        db.query(models.Image)
        .join(models.Task, models.Image.task_id == models.Task.id)
        .join(models.BlackboardPost, models.BlackboardPost.task_id == models.Task.id)
        .filter(models.Image.id == image_id)
        .first()
    )

def update_task_status(db: Session, task_id: UUID, status: str) -> Optional[models.Task]:
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if task:
        task.status = status
        if status in ("completed", "failed"):
            task.completed_at = func.now()
        db.commit()
        db.refresh(task)
    return task


def set_task_run_user(db: Session, task_id: UUID, user_id: Optional[UUID]) -> Optional[models.Task]:
    task = db.query(models.Task).filter(models.Task.id == task_id).first()
    if task:
        task.run_by = user_id
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


def get_user(db: Session, user_id: UUID) -> Optional[models.User]:
    return db.query(models.User).filter(models.User.id == user_id).first()


def create_analysis_skill(
    db: Session,
    *,
    name: str,
    instruction_md: str,
    owner_id: Optional[UUID],
    is_official: bool = False,
    status: str = "active",
) -> models.AnalysisSkill:
    skill = models.AnalysisSkill(
        name=name,
        instruction_md=instruction_md,
        owner_id=owner_id,
        is_official=is_official,
        status=status,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def get_analysis_skill(db: Session, skill_id: UUID) -> Optional[models.AnalysisSkill]:
    return db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id == skill_id).first()


def get_official_analysis_skill_by_name(
    db: Session,
    name: str,
    exclude_id: Optional[UUID] = None,
) -> Optional[models.AnalysisSkill]:
    q = (
        db.query(models.AnalysisSkill)
        .filter(models.AnalysisSkill.name == name.strip())
        .filter(models.AnalysisSkill.is_official.is_(True))
    )
    if exclude_id is not None:
        q = q.filter(models.AnalysisSkill.id != exclude_id)
    return q.first()


def _analysis_skill_visibility_filter(user: models.User):
    visible = [
        models.AnalysisSkill.owner_id == user.id,
        models.AnalysisSkill.is_official.is_(True),
    ]
    if getattr(user, "role", "") == "admin":
        visible.append(models.AnalysisSkill.owner_id.is_(None))
    return or_(*visible)


def list_visible_analysis_skills(db: Session, user: models.User) -> List[models.AnalysisSkill]:
    return (
        db.query(models.AnalysisSkill)
        .filter(models.AnalysisSkill.status == "active")
        .filter(_analysis_skill_visibility_filter(user))
        .order_by(models.AnalysisSkill.is_official.desc(), models.AnalysisSkill.updated_at.desc().nullslast())
        .all()
    )


def list_all_analysis_skills(db: Session) -> List[models.AnalysisSkill]:
    return db.query(models.AnalysisSkill).order_by(models.AnalysisSkill.updated_at.desc().nullslast()).all()


def get_selectable_analysis_skills(
    db: Session,
    skill_ids: List[UUID],
    user: models.User,
) -> List[models.AnalysisSkill]:
    if not skill_ids:
        return []
    return (
        db.query(models.AnalysisSkill)
        .filter(models.AnalysisSkill.id.in_(skill_ids))
        .filter(models.AnalysisSkill.status == "active")
        .filter(_analysis_skill_visibility_filter(user))
        .all()
    )


def update_analysis_skill(
    db: Session,
    skill_id: UUID,
    *,
    name: Optional[str] = None,
    instruction_md: Optional[str] = None,
    status: Optional[str] = None,
    is_official: Optional[bool] = None,
) -> Optional[models.AnalysisSkill]:
    skill = get_analysis_skill(db, skill_id)
    if not skill:
        return None
    if name is not None:
        skill.name = name
    if instruction_md is not None:
        skill.instruction_md = instruction_md
    if status is not None:
        skill.status = status
    if is_official is not None:
        skill.is_official = is_official
    skill.updated_at = datetime.now()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise
    db.refresh(skill)
    return skill


def get_user_by_username(db: Session, username: str) -> Optional[models.User]:
    return db.query(models.User).filter(models.User.username == username).first()


def list_users(db: Session, skip: int = 0, limit: int = 100) -> List[models.User]:
    return db.query(models.User).order_by(models.User.created_at.desc()).offset(skip).limit(limit).all()


def create_user(
    db: Session,
    *,
    username: str,
    password_hash: str,
    display_name: Optional[str] = None,
    role: str = "viewer",
    status: str = "active",
) -> models.User:
    user = models.User(
        username=username,
        display_name=display_name or username,
        password_hash=password_hash,
        role=role,
        status=status,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_user(
    db: Session,
    user_id: UUID,
    *,
    display_name: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    password_hash: Optional[str] = None,
) -> Optional[models.User]:
    user = get_user(db, user_id)
    if not user:
        return None
    if display_name is not None:
        user.display_name = display_name
    if role is not None:
        user.role = role
    if status is not None:
        user.status = status
    if password_hash is not None:
        user.password_hash = password_hash
    user.updated_at = datetime.now()
    db.commit()
    db.refresh(user)
    return user


def record_login(db: Session, user: models.User) -> models.User:
    user.last_login_at = datetime.now()
    db.commit()
    db.refresh(user)
    return user


def get_app_setting(db: Session, key: str) -> Optional[models.AppSetting]:
    return db.query(models.AppSetting).filter(models.AppSetting.key == key).first()


def set_app_setting(
    db: Session,
    key: str,
    value: str,
    updated_by: Optional[UUID] = None,
) -> models.AppSetting:
    setting = get_app_setting(db, key)
    if setting:
        setting.value = value
        setting.updated_by = updated_by
        setting.updated_at = datetime.now()
    else:
        setting = models.AppSetting(key=key, value=value, updated_by=updated_by)
        db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting


def get_registration_invite_code(db: Session) -> str:
    setting = get_app_setting(db, REGISTRATION_INVITE_CODE_KEY)
    return setting.value if setting else "1234"


def set_registration_invite_code(
    db: Session,
    invite_code: str,
    updated_by: Optional[UUID] = None,
) -> models.AppSetting:
    return set_app_setting(db, REGISTRATION_INVITE_CODE_KEY, invite_code, updated_by=updated_by)


def create_task_run(
    db: Session,
    task_id: UUID,
    *,
    status: str = "pending",
    execution_mode: str = "local",
    output_dir: Optional[str] = None,
    log_path: Optional[str] = None,
    device_id: Optional[UUID] = None,
    worker_id: Optional[UUID] = None,
    created_by: Optional[UUID] = None,
) -> models.TaskRun:
    last_attempt = (
        db.query(func.max(models.TaskRun.attempt_no))
        .filter(models.TaskRun.task_id == task_id)
        .scalar()
        or 0
    )
    run = models.TaskRun(
        task_id=task_id,
        attempt_no=last_attempt + 1,
        status=status,
        execution_mode=execution_mode,
        output_dir=output_dir,
        log_path=log_path,
        device_id=device_id,
        worker_id=worker_id,
        created_by=created_by,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_task_run(db: Session, run_id: UUID) -> Optional[models.TaskRun]:
    return db.query(models.TaskRun).filter(models.TaskRun.id == run_id).first()


def get_task_run_for_user(db: Session, run_id: UUID, user_id: UUID) -> Optional[models.TaskRun]:
    return (
        db.query(models.TaskRun)
        .join(models.Task, models.TaskRun.task_id == models.Task.id)
        .filter(models.TaskRun.id == run_id)
        .filter(models.Task.created_by == user_id)
        .first()
    )


def get_latest_task_run(db: Session, task_id: UUID) -> Optional[models.TaskRun]:
    return (
        db.query(models.TaskRun)
        .filter(models.TaskRun.task_id == task_id)
        .order_by(models.TaskRun.attempt_no.desc())
        .first()
    )


def list_task_runs(db: Session, task_id: UUID) -> List[models.TaskRun]:
    return (
        db.query(models.TaskRun)
        .filter(models.TaskRun.task_id == task_id)
        .order_by(models.TaskRun.attempt_no.desc())
        .all()
    )


def update_task_run(
    db: Session,
    run_id: UUID,
    *,
    status: Optional[str] = None,
    started_at: Optional[datetime] = None,
    completed_at: Optional[datetime] = None,
    exit_code: Optional[int] = None,
    failure_reason: Optional[str] = None,
    goal_validation_json: Optional[dict | list] = None,
    execution_mode: Optional[str] = None,
    worker_id: Optional[UUID] = None,
    claimed_at: Optional[datetime] = None,
    heartbeat_at: Optional[datetime] = None,
    output_dir: Optional[str] = None,
    log_path: Optional[str] = None,
    device_id: Optional[UUID] = None,
) -> Optional[models.TaskRun]:
    run = get_task_run(db, run_id)
    if not run:
        return None
    if status is not None:
        run.status = status
    if started_at is not None:
        run.started_at = started_at
    if completed_at is not None:
        run.completed_at = completed_at
    if exit_code is not None:
        run.exit_code = exit_code
    if failure_reason is not None:
        run.failure_reason = failure_reason
    if goal_validation_json is not None:
        run.goal_validation_json = goal_validation_json
    if execution_mode is not None:
        run.execution_mode = execution_mode
    if worker_id is not None:
        run.worker_id = worker_id
    if claimed_at is not None:
        run.claimed_at = claimed_at
    if heartbeat_at is not None:
        run.heartbeat_at = heartbeat_at
    if output_dir is not None:
        run.output_dir = output_dir
    if log_path is not None:
        run.log_path = log_path
    if device_id is not None:
        run.device_id = device_id
    db.commit()
    db.refresh(run)
    return run


def count_task_runs(db: Session, task_id: UUID) -> int:
    return db.query(func.count(models.TaskRun.id)).filter(models.TaskRun.task_id == task_id).scalar() or 0


def get_device(db: Session, device_id: UUID) -> Optional[models.Device]:
    return db.query(models.Device).filter(models.Device.id == device_id).first()


def get_device_by_serial(db: Session, serial: str) -> Optional[models.Device]:
    return db.query(models.Device).filter(models.Device.serial == serial).first()


def get_worker(db: Session, worker_id: UUID) -> Optional[models.Worker]:
    return db.query(models.Worker).filter(models.Worker.id == worker_id).first()


def get_worker_by_node_key(db: Session, node_key: str) -> Optional[models.Worker]:
    return db.query(models.Worker).filter(models.Worker.node_key == node_key).first()


def upsert_worker(
    db: Session,
    *,
    node_key: str,
    name: Optional[str] = None,
    status: str = "online",
    version: Optional[str] = None,
    notes: Optional[str] = None,
) -> models.Worker:
    now = datetime.now()
    worker = get_worker_by_node_key(db, node_key)
    if not worker:
        worker = models.Worker(node_key=node_key, name=name or node_key, created_at=now)
        db.add(worker)
    worker.name = name or worker.name or node_key
    worker.status = status
    if version is not None:
        worker.version = version
    if notes is not None:
        worker.notes = notes
    worker.last_seen_at = now
    worker.updated_at = now
    db.commit()
    db.refresh(worker)
    return worker


def list_workers(db: Session) -> List[models.Worker]:
    return db.query(models.Worker).order_by(models.Worker.status.asc(), models.Worker.node_key.asc()).all()


def upsert_device(
    db: Session,
    *,
    serial: str,
    status: str,
    name: Optional[str] = None,
    source: str = "local",
    worker_id: Optional[UUID] = None,
    last_seen_at: Optional[datetime] = None,
    notes: Optional[str] = None,
) -> models.Device:
    device = get_device_by_serial(db, serial)
    if not device:
        device = models.Device(serial=serial, name=name or serial)
        db.add(device)
    device.status = status
    device.name = name or device.name or serial
    device.source = source
    device.worker_id = worker_id
    device.last_seen_at = last_seen_at
    device.notes = notes
    device.updated_at = datetime.now()
    db.commit()
    db.refresh(device)
    return device


def list_devices(db: Session) -> List[models.Device]:
    return db.query(models.Device).order_by(models.Device.status.asc(), models.Device.serial.asc()).all()


def acquire_device(db: Session, device_id: Optional[UUID] = None) -> Optional[models.Device]:
    q = db.query(models.Device).filter(
        models.Device.status == "online",
        models.Device.source == "local",
    )
    if device_id is not None:
        q = q.filter(models.Device.id == device_id)
    return q.order_by(models.Device.last_seen_at.desc().nullslast(), models.Device.serial.asc()).first()


def acquire_worker_device(db: Session, worker_id: UUID, device_id: Optional[UUID] = None) -> Optional[models.Device]:
    q = db.query(models.Device).filter(
        models.Device.worker_id == worker_id,
        models.Device.status == "online",
    )
    if device_id is not None:
        q = q.filter(models.Device.id == device_id)
    return q.order_by(models.Device.last_seen_at.desc().nullslast(), models.Device.serial.asc()).first()


def mark_device_busy(db: Session, device_id: UUID, task_run_id: UUID) -> Optional[models.Device]:
    device = get_device(db, device_id)
    if not device or device.status != "online":
        return None
    device.status = "busy"
    device.current_task_run_id = task_run_id
    device.updated_at = datetime.now()
    db.commit()
    db.refresh(device)
    return device


def release_device_for_run(db: Session, task_run_id: UUID) -> Optional[models.Device]:
    device = db.query(models.Device).filter(models.Device.current_task_run_id == task_run_id).first()
    if not device:
        return None
    device.status = "online"
    device.current_task_run_id = None
    device.updated_at = datetime.now()
    db.commit()
    db.refresh(device)
    return device


def claim_next_worker_task_run(db: Session, worker_id: UUID) -> Optional[models.TaskRun]:
    run = (
        db.query(models.TaskRun)
        .join(models.Task, models.TaskRun.task_id == models.Task.id)
        .outerjoin(models.Device, models.TaskRun.device_id == models.Device.id)
        .filter(models.TaskRun.execution_mode == "worker")
        .filter(models.TaskRun.status == "queued")
        .filter(or_(models.TaskRun.device_id.is_(None), models.Device.worker_id == worker_id))
        .order_by(models.TaskRun.created_at.asc())
        .first()
    )
    if not run:
        return None

    device = acquire_worker_device(db, worker_id, run.device_id)
    if not device:
        return None
    run.device_id = device.id
    device.status = "busy"
    device.current_task_run_id = run.id
    device.updated_at = datetime.now()
    run.worker_id = worker_id
    run.status = "running"
    run.claimed_at = datetime.now()
    run.heartbeat_at = run.claimed_at
    task = get_task(db, run.task_id)
    if task:
        task.status = "running"
    db.commit()
    db.refresh(run)
    return run

def create_embedding(db: Session, analysis_id: UUID, vector: List[float], content_type: str) -> models.Embedding:
    db_emb = db.query(models.Embedding).filter(
        models.Embedding.analysis_id == analysis_id,
        models.Embedding.content_type == content_type,
    ).first()
    if db_emb:
        db_emb.embedding = vector
    else:
        db_emb = models.Embedding(
            analysis_id=analysis_id,
            embedding=vector,
            content_type=content_type
        )
        db.add(db_emb)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    db.refresh(db_emb)
    return db_emb


def replace_embeddings(db: Session, analysis_id: UUID, vectors: dict[str, List[float]]) -> List[models.Embedding]:
    db.query(models.Embedding).filter(models.Embedding.analysis_id == analysis_id).delete()
    rows = [
        models.Embedding(
            analysis_id=analysis_id,
            embedding=vector,
            content_type=content_type,
        )
        for content_type, vector in vectors.items()
    ]
    db.add_all(rows)
    try:
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        raise
    for row in rows:
        db.refresh(row)
    return rows


def search_by_embedding(
    db: Session,
    vector: List[float],
    limit: int = 20,
    offset: int = 0,
    user_id: Optional[UUID] = None,
) -> List:
    """通过向量相似度搜索，返回 (embedding, analysis, image) 结果"""
    rows = db.query(models.Embedding, models.Analysis, models.Image).join(
        models.Analysis, models.Embedding.analysis_id == models.Analysis.id
    ).join(
        models.Image, models.Analysis.image_id == models.Image.id
    )
    if user_id is not None:
        rows = rows.join(models.Task, models.Image.task_id == models.Task.id).filter(models.Task.created_by == user_id)
    rows = rows.order_by(models.Embedding.embedding.l2_distance(vector)).limit(limit + offset + 50).all()

    results = []
    seen_analysis_ids = set()
    for embedding, analysis, image in rows:
        if analysis.id in seen_analysis_ids:
            continue
        seen_analysis_ids.add(analysis.id)
        results.append((embedding, analysis, image))
    return results[offset:offset + limit]

def search_by_text(
    db: Session,
    query: str,
    limit: int = 20,
    offset: int = 0,
    user_id: Optional[UUID] = None,
) -> List:
    """向量服务不可用时的文本兜底搜索，返回 (analysis, image) 结果。"""
    normalized = query.strip()
    q = db.query(models.Analysis, models.Image).join(
        models.Image, models.Analysis.image_id == models.Image.id
    )
    if user_id is not None:
        q = q.join(models.Task, models.Image.task_id == models.Task.id).filter(models.Task.created_by == user_id)
    if normalized:
        pattern = f"%{normalized}%"
        q = q.filter(or_(
            models.Analysis.design_analysis.ilike(pattern),
            models.Analysis.ops_analysis.ilike(pattern),
            func.cast(models.Analysis.custom_analysis_json, String).ilike(pattern),
            models.Image.source_app.ilike(pattern),
            models.Image.scenario.ilike(pattern),
            models.Image.file_path.ilike(pattern),
        ))
    return q.order_by(models.Analysis.analyzed_at.desc().nullslast()).offset(offset).limit(limit).all()


def create_watch_plan(
    db: Session,
    plan: schemas.WatchPlanCreate,
    created_by: Optional[UUID] = None,
    analysis_skill_snapshots: Optional[list[dict]] = None,
) -> models.WatchPlan:
    now = datetime.now()
    data = plan.model_dump()
    data.pop("analysis_skill_ids", None)
    db_plan = models.WatchPlan(
        **data,
        status="active",
        capture_scope="first_screen",
        analysis_skill_snapshots_json=analysis_skill_snapshots or [],
        created_by=created_by,
        updated_by=created_by,
        created_at=now,
        updated_at=now,
    )
    db.add(db_plan)
    db.commit()
    db.refresh(db_plan)
    return db_plan


def list_watch_plans(
    db: Session,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    user_id: Optional[UUID] = None,
) -> List[models.WatchPlan]:
    q = db.query(models.WatchPlan)
    if user_id is not None:
        q = q.filter(models.WatchPlan.created_by == user_id)
    if status:
        q = q.filter(models.WatchPlan.status == status)
    return q.order_by(models.WatchPlan.updated_at.desc().nullslast()).offset(skip).limit(limit).all()


def get_watch_plan_stats(db: Session, plan_id: UUID) -> dict:
    run_count = (
        db.query(func.count(models.WatchRun.id))
        .filter(models.WatchRun.watch_plan_id == plan_id)
        .scalar()
        or 0
    )
    latest_run = (
        db.query(models.WatchRun)
        .filter(models.WatchRun.watch_plan_id == plan_id)
        .order_by(models.WatchRun.run_date.desc(), models.WatchRun.created_at.desc())
        .first()
    )
    latest_success = get_latest_success_watch_run(db, plan_id)
    return {
        "run_count": run_count,
        "latest_run_status": latest_run.status if latest_run else None,
        "latest_success_run_at": latest_success.completed_at if latest_success else None,
    }


def get_watch_plan(db: Session, plan_id: UUID) -> Optional[models.WatchPlan]:
    return db.query(models.WatchPlan).filter(models.WatchPlan.id == plan_id).first()


def get_watch_plan_for_user(db: Session, plan_id: UUID, user_id: UUID) -> Optional[models.WatchPlan]:
    return (
        db.query(models.WatchPlan)
        .filter(models.WatchPlan.id == plan_id)
        .filter(models.WatchPlan.created_by == user_id)
        .first()
    )


def update_watch_plan(db: Session, plan_id: UUID, patch: schemas.WatchPlanUpdate, updated_by: Optional[UUID] = None) -> Optional[models.WatchPlan]:
    plan = get_watch_plan(db, plan_id)
    if not plan:
        return None
    data = patch.model_dump(exclude_unset=True)
    for field, value in data.items():
        if value is not None:
            setattr(plan, field, value)
    plan.updated_at = datetime.now()
    if updated_by:
        plan.updated_by = updated_by
    db.commit()
    db.refresh(plan)
    return plan


def set_watch_plan_status(
    db: Session,
    plan_id: UUID,
    status: str,
    pause_reason: Optional[str] = None,
    updated_by: Optional[UUID] = None,
) -> Optional[models.WatchPlan]:
    plan = get_watch_plan(db, plan_id)
    if not plan:
        return None
    plan.status = status
    plan.pause_reason = pause_reason if status == "paused" else None
    plan.updated_at = datetime.now()
    if updated_by:
        plan.updated_by = updated_by
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


def get_watch_run_for_user(db: Session, run_id: UUID, user_id: UUID) -> Optional[models.WatchRun]:
    return (
        db.query(models.WatchRun)
        .join(models.WatchPlan, models.WatchRun.watch_plan_id == models.WatchPlan.id)
        .filter(models.WatchRun.id == run_id)
        .filter(models.WatchPlan.created_by == user_id)
        .first()
    )


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


def get_latest_success_watch_run(db: Session, plan_id: UUID) -> Optional[models.WatchRun]:
    return (
        db.query(models.WatchRun)
        .filter(models.WatchRun.watch_plan_id == plan_id)
        .filter(models.WatchRun.status == "success")
        .order_by(models.WatchRun.run_date.desc(), models.WatchRun.created_at.desc())
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
