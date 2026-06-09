from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.services.goal_validator import missing_goal_failure_reason, validate_task_run_goals


ACTIVE_STATUSES = {"pending", "queued", "running"}
TERMINAL_RUN_STATUSES = {"completed", "failed"}
TERMINAL_TASK_STATUSES = {"completed", "failed"}
LOCAL_RUN_IDLE_SECONDS = 60
LOCAL_RUN_COMPLETION_MARKERS = ("✅ 任务完成", "🎉", "Parsing action: finish")


def _latest_task_run(db: Session, task_id):
    return (
        db.query(models.TaskRun)
        .filter(models.TaskRun.task_id == task_id)
        .order_by(models.TaskRun.created_at.desc(), models.TaskRun.attempt_no.desc())
        .first()
    )


def _task_rows(
    db: Session,
    *,
    include_empty_tasks: bool = False,
    task_ids: list[UUID] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    query = db.query(models.Task).filter(models.Task.status.in_(ACTIVE_STATUSES))
    if task_ids:
        query = query.filter(models.Task.id.in_(task_ids))
    tasks = query.all()
    for task in tasks:
        latest = _latest_task_run(db, task.id)
        if not latest:
            if not include_empty_tasks:
                continue
            group = _active_comparison_group_for_task(db, task.id)
            if group and task.status == "pending":
                continue
            image_count = db.query(models.Image).filter(models.Image.task_id == task.id).count()
            if image_count:
                continue
            rows.append({
                "task_id": str(task.id),
                "old_status": task.status,
                "new_status": "failed",
                "latest_run_id": None,
                "latest_run_status": None,
                "target_app": task.target_app,
                "request_id": str(task.request_id) if task.request_id else None,
                "reason": "无运行记录且无截图",
            })
            continue
        if latest.status not in TERMINAL_RUN_STATUSES:
            continue
        rows.append({
            "task_id": str(task.id),
            "old_status": task.status,
            "new_status": latest.status,
            "latest_run_id": str(latest.id),
            "latest_run_status": latest.status,
            "target_app": task.target_app,
            "request_id": str(task.request_id) if task.request_id else None,
            "reason": "最新运行已终态",
        })
    return rows


def _active_comparison_group_for_task(db: Session, task_id: UUID):
    group = db.query(models.ComparisonGroup).filter(models.ComparisonGroup.jd_task_id == task_id).first()
    if group and group.status in ACTIVE_STATUSES:
        return group
    group = (
        db.query(models.ComparisonGroup)
        .join(models.ComparisonGroupApp, models.ComparisonGroupApp.comparison_group_id == models.ComparisonGroup.id)
        .filter(models.ComparisonGroupApp.task_id == task_id)
        .first()
    )
    if group and group.status in ACTIVE_STATUSES:
        return group
    return None


def _resolve_project_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = Path(settings.PROJECT_ROOT) / path
    return path


def _tail_text(path: Path, limit: int = 8192) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            return handle.read().decode("utf-8", errors="ignore")
    except OSError:
        return ""


def _local_run_finished_by_log(run: models.TaskRun) -> bool:
    log_path = _resolve_project_path(run.log_path)
    if not log_path or not log_path.exists():
        return False
    tail = _tail_text(log_path)
    return any(marker in tail for marker in LOCAL_RUN_COMPLETION_MARKERS)


def _local_run_idle_enough(images: list[models.Image], now: datetime) -> bool:
    latest = max(
        (
            image.created_at or image.captured_at
            for image in images
            if image.created_at or image.captured_at
        ),
        default=None,
    )
    if not latest:
        return False
    return latest <= now - timedelta(seconds=LOCAL_RUN_IDLE_SECONDS)


def _stale_local_run_rows(db: Session, *, task_ids: list[UUID] | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    now = datetime.now()
    query = (
        db.query(models.TaskRun)
        .join(models.Task, models.Task.id == models.TaskRun.task_id)
        .filter(models.TaskRun.execution_mode == "local")
        .filter(models.TaskRun.status.in_(ACTIVE_STATUSES))
        .filter(models.Task.status.in_(ACTIVE_STATUSES))
    )
    if task_ids:
        query = query.filter(models.TaskRun.task_id.in_(task_ids))
    for run in query.all():
        images = list(run.images)
        if not images:
            continue
        if not _local_run_idle_enough(images, now) or not _local_run_finished_by_log(run):
            continue
        task = run.task
        validation = validate_task_run_goals(task, images)
        failure_reason = missing_goal_failure_reason(validation)
        new_status = "failed" if failure_reason else "completed"
        rows.append({
            "run_id": str(run.id),
            "task_id": str(run.task_id),
            "old_run_status": run.status,
            "new_run_status": new_status,
            "old_task_status": task.status if task else None,
            "new_task_status": new_status,
            "target_app": task.target_app if task else None,
            "request_id": str(task.request_id) if task and task.request_id else None,
            "image_count": len(images),
            "reason": failure_reason or "本地运行日志已完成但 watcher 未收口",
            "goal_validation": validation,
        })
    return rows


def _comparison_tasks(group: models.ComparisonGroup) -> list[models.Task]:
    tasks: list[models.Task] = []
    seen = set()
    for app in group.apps:
        if app.task and app.task.id not in seen:
            tasks.append(app.task)
            seen.add(app.task.id)
    if group.jd_task and group.jd_task.id not in seen:
        tasks.append(group.jd_task)
    return tasks


def _group_terminal_status(tasks: list[models.Task]) -> str | None:
    if not tasks:
        return "failed"
    statuses = [task.status for task in tasks]
    if any(status in ACTIVE_STATUSES for status in statuses):
        return None
    if all(status in TERMINAL_TASK_STATUSES for status in statuses):
        return "failed" if any(status == "failed" for status in statuses) else "completed"
    return None


def _comparison_group_rows(
    db: Session,
    *,
    task_ids: list[UUID] | None = None,
    comparison_group_ids: list[UUID] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    query = db.query(models.ComparisonGroup).filter(models.ComparisonGroup.status.in_(ACTIVE_STATUSES))
    if comparison_group_ids:
        query = query.filter(models.ComparisonGroup.id.in_(comparison_group_ids))
    elif task_ids:
        app_group_ids = (
            db.query(models.ComparisonGroupApp.comparison_group_id)
            .filter(models.ComparisonGroupApp.task_id.in_(task_ids))
        )
        query = query.filter(or_(models.ComparisonGroup.jd_task_id.in_(task_ids), models.ComparisonGroup.id.in_(app_group_ids)))
    groups = query.all()
    for group in groups:
        new_status = _group_terminal_status(_comparison_tasks(group))
        if not new_status:
            continue
        rows.append({
            "comparison_group_id": str(group.id),
            "old_status": group.status,
            "new_status": new_status,
            "request_id": str(group.request_id),
            "jd_task_id": str(group.jd_task_id) if group.jd_task_id else None,
        })
    return rows


def _device_rows(db: Session) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    devices = (
        db.query(models.Device)
        .filter(models.Device.status == "busy")
        .filter(models.Device.current_task_run_id.isnot(None))
        .all()
    )
    for device in devices:
        run = (
            db.query(models.TaskRun)
            .filter(models.TaskRun.id == device.current_task_run_id)
            .first()
        )
        if not run:
            reason = "current task run is missing"
        elif run.status in TERMINAL_RUN_STATUSES:
            reason = "current task run is terminal"
        else:
            continue
        rows.append({
            "device_id": str(device.id),
            "serial": device.serial,
            "old_status": device.status,
            "new_status": "online",
            "current_task_run_id": str(device.current_task_run_id),
            "reason": reason,
        })
    return rows


def _maybe_start_completed_comparison_tasks(db: Session, task_ids: list[UUID]) -> None:
    if not task_ids:
        return
    from app.services.collector_bridge import _maybe_start_jd_comparison_task

    for task_id in task_ids:
        _maybe_start_jd_comparison_task(db, task_id, final_status="completed")


def reconcile_stale_statuses(
    db: Session,
    *,
    apply: bool = False,
    include_empty_tasks: bool = False,
    task_ids: list[UUID] | None = None,
    comparison_group_ids: list[UUID] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    local_runs = _stale_local_run_rows(db, task_ids=task_ids)
    completed_task_ids: list[UUID] = []
    if apply:
        now = datetime.now()
        for row in local_runs:
            run = db.query(models.TaskRun).filter(models.TaskRun.id == row["run_id"]).first()
            task = db.query(models.Task).filter(models.Task.id == row["task_id"]).first()
            if run:
                run.status = row["new_run_status"]
                run.completed_at = now
                run.exit_code = 0 if row["new_run_status"] == "completed" else run.exit_code
                run.failure_reason = "" if row["new_run_status"] == "completed" else row["reason"]
                run.goal_validation_json = row.get("goal_validation")
            if task:
                task.status = row["new_task_status"]
                if task.completed_at is None:
                    task.completed_at = now
                if row["new_task_status"] == "completed":
                    completed_task_ids.append(task.id)
        db.commit()
        _maybe_start_completed_comparison_tasks(db, completed_task_ids)

    tasks = _task_rows(db, include_empty_tasks=include_empty_tasks, task_ids=task_ids)
    if apply:
        now = datetime.now()
        for row in tasks:
            task = db.query(models.Task).filter(models.Task.id == row["task_id"]).first()
            if not task:
                continue
            task.status = row["new_status"]
            if task.status in TERMINAL_TASK_STATUSES and task.completed_at is None:
                task.completed_at = now
            if row["new_status"] == "completed":
                completed_task_ids.append(task.id)
        db.commit()
        _maybe_start_completed_comparison_tasks(db, completed_task_ids)

    comparison_groups = _comparison_group_rows(db, task_ids=task_ids, comparison_group_ids=comparison_group_ids)
    if apply:
        now = datetime.now()
        for row in comparison_groups:
            group = (
                db.query(models.ComparisonGroup)
                .filter(models.ComparisonGroup.id == row["comparison_group_id"])
                .first()
            )
            if not group:
                continue
            group.status = row["new_status"]
            group.updated_at = now
        db.commit()

    devices = _device_rows(db)
    if apply:
        now = datetime.now()
        for row in devices:
            device = db.query(models.Device).filter(models.Device.id == row["device_id"]).first()
            if not device:
                continue
            device.status = row["new_status"]
            device.current_task_run_id = None
            device.updated_at = now
        db.commit()

    return {
        "local_runs": local_runs,
        "tasks": tasks,
        "comparison_groups": comparison_groups,
        "devices": devices,
    }
