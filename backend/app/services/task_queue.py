import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app import crud, models
from app.database import SessionLocal
from app.services.devices import refresh_devices
from app.services.task_events import push_event, task_event


TASK_STATUS_QUEUED = "queued"
TASK_STATUS_RUNNING = "running"
_queue_lock = threading.Lock()


class TaskQueueError(ValueError):
    pass


@dataclass
class TaskQueueDecision:
    status: str
    task: models.Task
    run: models.TaskRun | None = None


def _has_running_task(db: Session) -> bool:
    return db.query(models.Task.id).filter(models.Task.status == TASK_STATUS_RUNNING).first() is not None


def _queued_run_for_task(db: Session, task_id: UUID) -> models.TaskRun | None:
    return (
        db.query(models.TaskRun)
        .filter(models.TaskRun.task_id == task_id)
        .filter(models.TaskRun.status == TASK_STATUS_QUEUED)
        .order_by(models.TaskRun.created_at.desc(), models.TaskRun.attempt_no.desc())
        .first()
    )


def _next_queued_run(db: Session) -> models.TaskRun | None:
    return (
        db.query(models.TaskRun)
        .join(models.Task, models.TaskRun.task_id == models.Task.id)
        .filter(models.Task.status == TASK_STATUS_QUEUED)
        .filter(models.TaskRun.status == TASK_STATUS_QUEUED)
        .order_by(models.TaskRun.created_at.asc(), models.TaskRun.attempt_no.asc())
        .first()
    )


def _select_device(db: Session, task: models.Task, device_id: UUID | None):
    if task.mode not in ("autoglm", "uiautomator2") and not device_id:
        return None
    refresh_devices(db)
    return crud.acquire_device(db, device_id)


def _store_prompt_if_needed(db: Session, task: models.Task, prompt: str | None) -> models.Task:
    if prompt and task.mode == "autoglm" and not task.generated_instruction:
        crud.update_task_instruction(db, task.id, prompt)
        return crud.get_task(db, task.id)
    return task


def _enqueue_task(
    db: Session,
    task: models.Task,
    *,
    created_by: UUID | None,
    requested_device_id: UUID | None,
    prompt: str | None,
) -> models.TaskRun:
    task = _store_prompt_if_needed(db, task, prompt)
    existing = _queued_run_for_task(db, task.id)
    if existing:
        return existing
    run = crud.create_task_run(
        db,
        task.id,
        status=TASK_STATUS_QUEUED,
        device_id=requested_device_id,
        created_by=created_by,
    )
    crud.update_task_status(db, task.id, TASK_STATUS_QUEUED)
    crud.set_task_run_user(db, task.id, created_by)
    push_event(str(task.id), task_event("queued"))
    return run


def _start_task_run(
    db: Session,
    task: models.Task,
    *,
    run: models.TaskRun | None = None,
    created_by: UUID | None,
    requested_device_id: UUID | None,
    prompt: str | None,
) -> TaskQueueDecision:
    task = _store_prompt_if_needed(db, task, prompt)
    device_id = requested_device_id or (run.device_id if run else None)
    device = _select_device(db, task, device_id)
    if task.mode in ("autoglm", "uiautomator2") and not device:
        raise TaskQueueError("Selected device is unavailable" if device_id else "No available device")

    run = run or crud.create_task_run(db, task.id, device_id=device.id if device else None, created_by=created_by)
    if device and not crud.mark_device_busy(db, device.id, run.id):
        if run.status != TASK_STATUS_QUEUED:
            crud.update_task_run(db, run.id, status="failed", failure_reason="Device is busy")
        raise TaskQueueError("Device is busy")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    crud.update_task_run(
        db,
        run.id,
        status=TASK_STATUS_RUNNING,
        started_at=now,
        device_id=device.id if device else None,
    )
    crud.update_task_status(db, task.id, TASK_STATUS_RUNNING)
    crud.set_task_run_user(db, task.id, created_by)
    task = crud.get_task(db, task.id)
    run = crud.get_task_run(db, run.id)

    try:
        from app.services.task_runner import start_task_process

        start_task_process(task, prompt=prompt or task.generated_instruction, task_run=run, created_by=created_by, device=device)
    except Exception as exc:
        crud.update_task_status(db, task.id, "failed")
        crud.update_task_run(db, run.id, status="failed", failure_reason=str(exc))
        crud.release_device_for_run(db, run.id)
        raise
    return TaskQueueDecision(status=TASK_STATUS_RUNNING, task=task, run=run)


def start_or_enqueue_task(
    db: Session,
    task: models.Task,
    *,
    created_by: UUID | None,
    requested_device_id: UUID | None = None,
    prompt: str | None = None,
) -> TaskQueueDecision:
    with _queue_lock:
        if task.status == TASK_STATUS_RUNNING:
            raise TaskQueueError("Task is already running")
        if task.status == TASK_STATUS_QUEUED:
            return TaskQueueDecision(status=TASK_STATUS_QUEUED, task=task, run=_queued_run_for_task(db, task.id))
        if _has_running_task(db):
            run = _enqueue_task(
                db,
                task,
                created_by=created_by,
                requested_device_id=requested_device_id,
                prompt=prompt,
            )
            return TaskQueueDecision(status=TASK_STATUS_QUEUED, task=crud.get_task(db, task.id), run=run)
        return _start_task_run(
            db,
            task,
            created_by=created_by,
            requested_device_id=requested_device_id,
            prompt=prompt,
        )


def start_next_queued_task() -> TaskQueueDecision | None:
    with _queue_lock:
        db = SessionLocal()
        try:
            if _has_running_task(db):
                return None
            while True:
                run = _next_queued_run(db)
                if not run:
                    return None
                task = crud.get_task(db, run.task_id)
                if not task or task.status != TASK_STATUS_QUEUED:
                    crud.update_task_run(db, run.id, status="failed", failure_reason="Queued task no longer exists")
                    continue
                try:
                    decision = _start_task_run(
                        db,
                        task,
                        run=run,
                        created_by=run.created_by,
                        requested_device_id=run.device_id,
                        prompt=task.generated_instruction,
                    )
                    push_event(str(task.id), task_event("started"))
                    return decision
                except TaskQueueError as exc:
                    print(f"⚠️ 暂无法启动排队任务 {task.id}: {exc}")
                    return None
                except Exception as exc:
                    print(f"⚠️ 排队任务启动失败 {task.id}: {exc}")
                    push_event(str(task.id), task_event("error", message=str(exc)))
                    push_event(str(task.id), task_event("done", status="failed"))
                    continue
        finally:
            db.close()
