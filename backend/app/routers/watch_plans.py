from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import crud, schemas, models
from app.database import get_db
from app.services.auth import data_scope_user_id, get_current_user, require_at_least
from app.services import exporter
from app.services.watch_service import start_watch_run

router = APIRouter(prefix="/admin", tags=["watch-plans"])


def _search_result_for_image(image) -> schemas.SearchResult:
    return schemas.SearchResult(
        image=schemas.ImageOut.model_validate(image),
        analysis=schemas.AnalysisOut.model_validate(image.analysis) if image.analysis else None,
        similarity=None,
    )


def _get_owned_watch_plan(db: Session, plan_id: UUID, user: models.User) -> models.WatchPlan:
    scope_user_id = data_scope_user_id(user)
    plan = crud.get_watch_plan_for_user(db, plan_id, scope_user_id) if scope_user_id else crud.get_watch_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Watch plan not found")
    return plan


def _get_owned_watch_run(db: Session, run_id: UUID, user: models.User) -> models.WatchRun:
    scope_user_id = data_scope_user_id(user)
    run = crud.get_watch_run_for_user(db, run_id, scope_user_id) if scope_user_id else crud.get_watch_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Watch run not found")
    return run


def _watch_plan_out(plan, db: Session) -> schemas.WatchPlanOut:
    return schemas.WatchPlanOut.model_validate({
        "id": plan.id,
        "name": plan.name,
        "target_app": plan.target_app,
        "target_page": plan.target_page,
        "entry_instruction": plan.entry_instruction,
        "focus_question": plan.focus_question,
        "capture_scope": plan.capture_scope,
        "schedule_time": plan.schedule_time,
        "status": plan.status,
        "pause_reason": plan.pause_reason,
        "last_run_at": plan.last_run_at,
        "created_by": plan.created_by,
        "updated_by": plan.updated_by,
        "created_by_name": _user_name(db, plan.created_by),
        "updated_by_name": _user_name(db, plan.updated_by),
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
        **crud.get_watch_plan_stats(db, plan.id),
    })


def _detail(plan, db: Session) -> schemas.WatchPlanDetailOut:
    runs = crud.list_watch_runs(db, plan.id, limit=10)
    latest_run = runs[0] if runs else None
    latest_success_run = crud.get_latest_success_watch_run(db, plan.id)
    result_run = latest_success_run or latest_run
    latest_snapshot = None
    latest_summary = None
    if result_run:
        snapshots = crud.list_watch_snapshots(db, result_run.id)
        if snapshots:
            latest_snapshot = _search_result_for_image(snapshots[0].image)
        latest_summary = result_run.daily_summary
    reports = []
    for period_days in (7, 30):
        latest = crud.list_watch_period_reports(db, plan.id, period_days=period_days, limit=1)
        reports.extend(latest)
    return schemas.WatchPlanDetailOut(
        plan=_watch_plan_out(plan, db),
        latest_run=schemas.WatchRunOut.model_validate(latest_run) if latest_run else None,
        latest_success_run=schemas.WatchRunOut.model_validate(latest_success_run) if latest_success_run else None,
        latest_snapshot=latest_snapshot,
        latest_summary=schemas.WatchDailySummaryOut.model_validate(latest_summary) if latest_summary else None,
        period_reports=[schemas.WatchPeriodReportOut.model_validate(report) for report in reports],
        recent_runs=[schemas.WatchRunOut.model_validate(run) for run in runs],
    )


@router.get("/watch-plans", response_model=list[schemas.WatchPlanOut])
def list_watch_plans(status: str | None = None, skip: int = 0, limit: int = 100, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return [_watch_plan_out(plan, db) for plan in crud.list_watch_plans(db, status=status, skip=skip, limit=limit, user_id=data_scope_user_id(user))]


@router.post("/watch-plans", response_model=schemas.WatchPlanOut)
def create_watch_plan(body: schemas.WatchPlanCreate, db: Session = Depends(get_db), user: models.User = Depends(require_at_least("operator"))):
    return crud.create_watch_plan(db, body, created_by=user.id)


@router.get("/watch-plans/{plan_id}", response_model=schemas.WatchPlanDetailOut)
def get_watch_plan(plan_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    plan = _get_owned_watch_plan(db, plan_id, user)
    return _detail(plan, db)


@router.patch("/watch-plans/{plan_id}", response_model=schemas.WatchPlanOut)
def update_watch_plan(plan_id: UUID, body: schemas.WatchPlanUpdate, db: Session = Depends(get_db), user: models.User = Depends(require_at_least("operator"))):
    _get_owned_watch_plan(db, plan_id, user)
    plan = crud.update_watch_plan(db, plan_id, body, updated_by=user.id)
    if not plan:
        raise HTTPException(status_code=404, detail="Watch plan not found")
    return plan


@router.post("/watch-plans/{plan_id}/pause", response_model=schemas.WatchPlanOut)
def pause_watch_plan(plan_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(require_at_least("operator"))):
    _get_owned_watch_plan(db, plan_id, user)
    plan = crud.set_watch_plan_status(db, plan_id, "paused", pause_reason="用户手动暂停", updated_by=user.id)
    if not plan:
        raise HTTPException(status_code=404, detail="Watch plan not found")
    return plan


@router.post("/watch-plans/{plan_id}/resume", response_model=schemas.WatchPlanOut)
def resume_watch_plan(plan_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(require_at_least("operator"))):
    _get_owned_watch_plan(db, plan_id, user)
    plan = crud.set_watch_plan_status(db, plan_id, "active", updated_by=user.id)
    if not plan:
        raise HTTPException(status_code=404, detail="Watch plan not found")
    return plan


@router.post("/watch-plans/{plan_id}/run-now", response_model=schemas.WatchRunOut)
def run_watch_plan_now(plan_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(require_at_least("operator"))):
    plan = _get_owned_watch_plan(db, plan_id, user)

    today = datetime.now().date()
    run = crud.get_watch_run_by_date(db, plan_id, today)
    if run and run.status == "success":
        raise HTTPException(status_code=409, detail="Today's watch run already completed")
    if run and run.status == "running":
        return run
    if not run:
        run = crud.create_watch_run(db, plan_id, today)
    elif run.attempt_count >= 2:
        raise HTTPException(status_code=409, detail="Today's watch run already failed twice")

    return start_watch_run(db, run, user_id=user.id)


@router.get("/watch-plans/{plan_id}/runs", response_model=list[schemas.WatchRunOut])
def list_watch_runs(plan_id: UUID, skip: int = 0, limit: int = 30, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    _get_owned_watch_plan(db, plan_id, user)
    return crud.list_watch_runs(db, plan_id, skip=skip, limit=limit)


@router.get("/watch-runs/{run_id}", response_model=schemas.WatchRunOut)
def get_watch_run(run_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return _get_owned_watch_run(db, run_id, user)


@router.get("/watch-runs/{run_id}/snapshots", response_model=list[schemas.SearchResult])
def list_watch_snapshots(run_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    _get_owned_watch_run(db, run_id, user)
    return [_search_result_for_image(snapshot.image) for snapshot in crud.list_watch_snapshots(db, run_id)]


@router.get("/watch-plans/{plan_id}/reports", response_model=list[schemas.WatchPeriodReportOut])
def list_watch_reports(plan_id: UUID, period_days: int | None = None, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    _get_owned_watch_plan(db, plan_id, user)
    return crud.list_watch_period_reports(db, plan_id, period_days=period_days, limit=10)


@router.get("/watch-plans/{plan_id}/export")
def export_watch_plan(plan_id: UUID, format: str = "json", db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if format not in ("json", "xlsx"):
        raise HTTPException(status_code=400, detail="Unsupported export format")
    _get_owned_watch_plan(db, plan_id, user)
    payload = exporter.watch_plan_export_payload(db, plan_id, user_id=data_scope_user_id(user))
    if format == "json":
        content = exporter.json_bytes(payload)
        media_type = "application/json; charset=utf-8"
        filename = f"watch-plan-{plan_id}.json"
    else:
        content = exporter.excel_bytes(payload)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = f"watch-plan-{plan_id}.xlsx"
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _user_name(db: Session, user_id: UUID | None) -> str | None:
    if not user_id:
        return None
    user = crud.get_user(db, user_id)
    if not user:
        return None
    return user.display_name or user.username
