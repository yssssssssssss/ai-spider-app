from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db
from app.services.auth import data_scope_user_id, get_current_user
from app.services.jd_comparison import build_comparison_result

router = APIRouter(prefix="/comparison-groups", tags=["comparison-groups"])


def _get_visible_task(db: Session, task_id: UUID, user: models.User) -> models.Task:
    scope_user_id = data_scope_user_id(user)
    task = crud.get_task_for_user(db, task_id, scope_user_id) if scope_user_id else crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/by-task/{task_id}", response_model=schemas.ComparisonGroupResultOut)
def get_comparison_group_by_task(
    task_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _get_visible_task(db, task_id, user)
    group = crud.get_comparison_group_by_task(db, task_id)
    if not group:
        raise HTTPException(status_code=404, detail="Comparison group not found")
    return build_comparison_result(db, group)
