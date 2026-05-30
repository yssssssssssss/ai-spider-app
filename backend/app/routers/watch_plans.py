from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import crud, schemas
from app.database import get_db
from app.services.watch_service import start_watch_run

router = APIRouter(prefix="/admin", tags=["watch-plans"])


def _search_result_for_image(image) -> schemas.SearchResult:
    return schemas.SearchResult(
        image=schemas.ImageOut.model_validate(image),
        analysis=schemas.AnalysisOut.model_validate(image.analysis) if image.analysis else None,
        similarity=None,
    )


def _detail(plan, db: Session) -> schemas.WatchPlanDetailOut:
    runs = crud.list_watch_runs(db, plan.id, limit=10)
    latest_run = runs[0] if runs else None
    latest_snapshot = None
    latest_summary = None
    if latest_run:
        snapshots = crud.list_watch_snapshots(db, latest_run.id)
        if snapshots:
            latest_snapshot = _search_result_for_image(snapshots[0].image)
        latest_summary = latest_run.daily_summary
    reports = []
    for period_days in (7, 30):
        latest = crud.list_watch_period_reports(db, plan.id, period_days=period_days, limit=1)
        reports.extend(latest)
    return schemas.WatchPlanDetailOut(
        plan=schemas.WatchPlanOut.model_validate(plan),
        latest_run=schemas.WatchRunOut.model_validate(latest_run) if latest_run else None,
        latest_snapshot=latest_snapshot,
        latest_summary=schemas.WatchDailySummaryOut.model_validate(latest_summary) if latest_summary else None,
        period_reports=[schemas.WatchPeriodReportOut.model_validate(report) for report in reports],
        recent_runs=[schemas.WatchRunOut.model_validate(run) for run in runs],
    )


@router.get("/watch-plans", response_model=list[schemas.WatchPlanOut])
def list_watch_plans(status: str | None = None, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.list_watch_plans(db, status=status, skip=skip, limit=limit)


@router.post("/watch-plans", response_model=schemas.WatchPlanOut)
def create_watch_plan(body: schemas.WatchPlanCreate, db: Session = Depends(get_db)):
    return crud.create_watch_plan(db, body)


@router.get("/watch-plans/{plan_id}", response_model=schemas.WatchPlanDetailOut)
def get_watch_plan(plan_id: UUID, db: Session = Depends(get_db)):
    plan = crud.get_watch_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Watch plan not found")
    return _detail(plan, db)


@router.patch("/watch-plans/{plan_id}", response_model=schemas.WatchPlanOut)
def update_watch_plan(plan_id: UUID, body: schemas.WatchPlanUpdate, db: Session = Depends(get_db)):
    plan = crud.update_watch_plan(db, plan_id, body)
    if not plan:
        raise HTTPException(status_code=404, detail="Watch plan not found")
    return plan


@router.post("/watch-plans/{plan_id}/pause", response_model=schemas.WatchPlanOut)
def pause_watch_plan(plan_id: UUID, db: Session = Depends(get_db)):
    plan = crud.set_watch_plan_status(db, plan_id, "paused", pause_reason="用户手动暂停")
    if not plan:
        raise HTTPException(status_code=404, detail="Watch plan not found")
    return plan


@router.post("/watch-plans/{plan_id}/resume", response_model=schemas.WatchPlanOut)
def resume_watch_plan(plan_id: UUID, db: Session = Depends(get_db)):
    plan = crud.set_watch_plan_status(db, plan_id, "active")
    if not plan:
        raise HTTPException(status_code=404, detail="Watch plan not found")
    return plan


@router.post("/watch-plans/{plan_id}/run-now", response_model=schemas.WatchRunOut)
def run_watch_plan_now(plan_id: UUID, db: Session = Depends(get_db)):
    plan = crud.get_watch_plan(db, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Watch plan not found")

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

    return start_watch_run(db, run)


@router.get("/watch-plans/{plan_id}/runs", response_model=list[schemas.WatchRunOut])
def list_watch_runs(plan_id: UUID, skip: int = 0, limit: int = 30, db: Session = Depends(get_db)):
    if not crud.get_watch_plan(db, plan_id):
        raise HTTPException(status_code=404, detail="Watch plan not found")
    return crud.list_watch_runs(db, plan_id, skip=skip, limit=limit)


@router.get("/watch-runs/{run_id}", response_model=schemas.WatchRunOut)
def get_watch_run(run_id: UUID, db: Session = Depends(get_db)):
    run = crud.get_watch_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Watch run not found")
    return run


@router.get("/watch-runs/{run_id}/snapshots", response_model=list[schemas.SearchResult])
def list_watch_snapshots(run_id: UUID, db: Session = Depends(get_db)):
    run = crud.get_watch_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Watch run not found")
    return [_search_result_for_image(snapshot.image) for snapshot in crud.list_watch_snapshots(db, run_id)]


@router.get("/watch-plans/{plan_id}/reports", response_model=list[schemas.WatchPeriodReportOut])
def list_watch_reports(plan_id: UUID, period_days: int | None = None, db: Session = Depends(get_db)):
    if not crud.get_watch_plan(db, plan_id):
        raise HTTPException(status_code=404, detail="Watch plan not found")
    return crud.list_watch_period_reports(db, plan_id, period_days=period_days, limit=10)
