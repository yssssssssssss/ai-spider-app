import os
import subprocess
import sys
from datetime import datetime, timezone

from app import crud
from app.config import settings
from app.database import SessionLocal
from app.services.collector_bridge import start_collection_watcher
from app.services.task_events import ensure_queue


def _safe_device_dir_name(device) -> str:
    if not device:
        return ""
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in device.serial)


def _prepare_run(task, task_run=None, created_by=None, device=None):
    db = SessionLocal()
    try:
        device_id = device.id if device else None
        run = task_run or crud.create_task_run(db, task.id, created_by=created_by, device_id=device_id)
        output_dir = os.path.join(settings.PROJECT_ROOT, "data", "tasks", str(task.id), "runs", str(run.id))
        if device:
            output_dir = os.path.join(output_dir, "devices", _safe_device_dir_name(device))
        log_path = os.path.join(settings.PROJECT_ROOT, "logs", "tasks", str(task.id), f"{run.id}.log")
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        run = crud.update_task_run(
            db,
            run.id,
            status="running",
            started_at=datetime.now(timezone.utc).replace(tzinfo=None),
            output_dir=os.path.relpath(output_dir, settings.PROJECT_ROOT),
            log_path=os.path.relpath(log_path, settings.PROJECT_ROOT),
            device_id=device_id,
        )
        return run, output_dir, log_path
    finally:
        db.close()


def start_task_process(task, prompt: str | None = None, *, task_run=None, created_by=None, device=None):
    project_root = settings.PROJECT_ROOT
    task_id = str(task.id)
    ensure_queue(task_id)
    process = None

    if task.mode == "autoglm":
        script_path = os.path.join(project_root, "run_autoglm.py")
        if not os.path.exists(script_path):
            raise FileNotFoundError("AutoGLM script not found")
        instruction = prompt or task.generated_instruction
        if not instruction:
            raise ValueError("AutoGLM prompt is required")
        run, output_dir, log_path = _prepare_run(
            task,
            task_run=task_run,
            created_by=created_by,
            device=device,
        )
        log_file = open(log_path, "a", encoding="utf-8")
        try:
            env = os.environ.copy()
            if device:
                env["PHONE_AGENT_DEVICE_ID"] = device.serial
            env["TASK_RUN_ID"] = str(run.id)
            process = subprocess.Popen(
                [
                    sys.executable,
                    script_path,
                    instruction,
                    "--task-id",
                    task_id,
                    "--task-run-id",
                    str(run.id),
                    *(["--device-id", device.serial, "--db-device-id", str(device.id)] if device else []),
                    "--output-dir",
                    output_dir,
                    "--source-app",
                    task.target_app or "",
                    "--max-steps",
                    str(settings.AUTOGLM_MAX_STEPS),
                ],
                cwd=project_root,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        finally:
            log_file.close()
    else:
        script_path = os.path.join(project_root, "run_workflow.py")
        if not os.path.exists(script_path):
            raise FileNotFoundError("Workflow script not found")
        run, output_dir, log_path = _prepare_run(
            task,
            task_run=task_run,
            created_by=created_by,
            device=device,
        )
        env = os.environ.copy()
        env["TB_KEYWORD"] = task.keyword or ""
        env["TASK_ID"] = task_id
        env["TASK_RUN_ID"] = str(run.id)
        env["TASK_OUTPUT_DIR"] = output_dir
        if device:
            env["PHONE_AGENT_DEVICE_ID"] = device.serial
        log_file = open(log_path, "a", encoding="utf-8")
        try:
            process = subprocess.Popen(
                [sys.executable, script_path],
                cwd=project_root,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        finally:
            log_file.close()

    start_collection_watcher(
        task_id,
        project_root,
        process=process,
        output_dir=output_dir,
        task_run_id=str(run.id),
        device_id=str(device.id) if device else None,
    )
    return process
