import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.config import settings
from app.database import get_db


router = APIRouter(prefix="/blackboard", tags=["blackboard"])


def _is_visible_task_image(image) -> bool:
    return not os.path.basename(image.file_path).startswith("_temp_")


def _resolve_image_path(image_path: str) -> str:
    if os.path.isabs(image_path):
        return image_path
    return os.path.join(settings.PROJECT_ROOT, image_path)


def _user_name(db: Session, user_id: UUID | None) -> str | None:
    if not user_id:
        return None
    user = crud.get_user(db, user_id)
    if not user:
        return None
    return user.display_name or user.username


def _task_images(task: models.Task) -> list[models.Image]:
    return sorted(
        [image for image in (task.images or []) if _is_visible_task_image(image)],
        key=lambda image: image.created_at,
    )


def _blackboard_post_out(db: Session, post: models.BlackboardPost) -> schemas.BlackboardPostOut:
    task = post.task
    images = _task_images(task)
    return schemas.BlackboardPostOut(
        id=post.id,
        task_id=post.task_id,
        task_name=task.name,
        keyword=task.keyword,
        target_app=task.target_app,
        target_scenario=task.target_scenario,
        task_status=task.status,
        published_by=post.published_by,
        published_by_name=_user_name(db, post.published_by),
        published_at=post.published_at,
        completed_at=task.completed_at,
        preview_image_id=images[0].id if images else None,
        image_count=len(images),
    )


def _task_out(db: Session, task: models.Task) -> schemas.TaskOut:
    latest = crud.get_latest_task_run(db, task.id)
    data = schemas.TaskOut.model_validate(task).model_dump()
    data["latest_run_id"] = latest.id if latest else None
    data["attempt_count"] = crud.count_task_runs(db, task.id)
    data["failure_reason"] = latest.failure_reason if latest else None
    data["execution_mode"] = latest.execution_mode if latest else None
    data["created_by_name"] = _user_name(db, task.created_by)
    data["approved_by_name"] = _user_name(db, task.approved_by)
    data["run_by_name"] = _user_name(db, task.run_by)
    data["blackboard_post_id"] = task.blackboard_post.id if task.blackboard_post else None
    data["blackboard_published_at"] = task.blackboard_post.published_at if task.blackboard_post else None
    return schemas.TaskOut.model_validate(data)


def _get_published_post(db: Session, task_id: UUID) -> models.BlackboardPost:
    post = crud.get_blackboard_post_by_task(db, task_id)
    if not post:
        raise HTTPException(status_code=404, detail="Blackboard task not found")
    return post


@router.get("", response_model=list[schemas.BlackboardPostOut])
def list_blackboard(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return [_blackboard_post_out(db, post) for post in crud.list_blackboard_posts(db, skip=skip, limit=limit)]


@router.get("/tasks/{task_id}", response_model=schemas.BlackboardTaskDetailOut)
def get_blackboard_task(task_id: UUID, db: Session = Depends(get_db)):
    post = _get_published_post(db, task_id)
    return schemas.BlackboardTaskDetailOut(
        post=_blackboard_post_out(db, post),
        task=_task_out(db, post.task),
    )


@router.get("/tasks/{task_id}/runs", response_model=list[schemas.TaskRunOut])
def list_blackboard_task_runs(task_id: UUID, db: Session = Depends(get_db)):
    _get_published_post(db, task_id)
    return crud.list_task_runs(db, task_id)


@router.get("/tasks/{task_id}/images", response_model=list[schemas.SearchResult])
def list_blackboard_task_images(
    task_id: UUID,
    run_id: UUID | None = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    _get_published_post(db, task_id)
    return [
        schemas.SearchResult(
            image=schemas.ImageOut.model_validate(image),
            analysis=schemas.AnalysisOut.model_validate(image.analysis) if image.analysis else None,
            similarity=None,
        )
        for image in crud.list_images(db, skip=skip, limit=limit, task_id=task_id)
        if (run_id is None or image.task_run_id == run_id)
        if _is_visible_task_image(image)
    ]


@router.get("/images/{image_id}/file")
def get_blackboard_image_file(image_id: UUID, db: Session = Depends(get_db)):
    image = crud.get_blackboard_image(db, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    file_path = _resolve_image_path(image.file_path)
    if not os.path.exists(file_path):
        if image.oss_url:
            return RedirectResponse(image.oss_url, status_code=302)
        raise HTTPException(status_code=404, detail="Image file not found on disk")
    return FileResponse(file_path)
