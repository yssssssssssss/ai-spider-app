import os
from datetime import datetime, timezone

from app import crud
from app.config import settings
from app.services.task_runner import start_task_process


def execution_mode() -> str:
    mode = (settings.EXECUTION_MODE or "local").strip().lower()
    return "worker" if mode == "worker" else "local"


class LocalTaskExecutor:
    def run(self, task, *, prompt: str | None, task_run, created_by=None, device=None):
        return start_task_process(task, prompt=prompt, task_run=task_run, created_by=created_by, device=device)


class WorkerTaskExecutor:
    def run(self, task, *, prompt: str | None, task_run, created_by=None, device=None):
        from app.database import SessionLocal

        db = SessionLocal()
        try:
            output_dir = os.path.join("data", "tasks", str(task.id), "runs", str(task_run.id), "worker")
            log_path = os.path.join("logs", "tasks", str(task.id), f"{task_run.id}.log")
            os.makedirs(os.path.join(settings.PROJECT_ROOT, output_dir), exist_ok=True)
            os.makedirs(os.path.dirname(os.path.join(settings.PROJECT_ROOT, log_path)), exist_ok=True)
            return crud.update_task_run(
                db,
                task_run.id,
                status="queued",
                execution_mode="worker",
                output_dir=output_dir,
                log_path=log_path,
                device_id=device.id if device else None,
                heartbeat_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        finally:
            db.close()


def task_executor():
    if execution_mode() == "worker":
        return WorkerTaskExecutor()
    return LocalTaskExecutor()
