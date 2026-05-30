import os
import subprocess
import sys

from app.config import settings
from app.services.collector_bridge import start_collection_watcher
from app.services.task_events import ensure_queue


def _open_task_log(task_id: str):
    log_dir = os.path.join(settings.PROJECT_ROOT, "logs", "tasks")
    os.makedirs(log_dir, exist_ok=True)
    return open(os.path.join(log_dir, f"{task_id}.log"), "a", encoding="utf-8")


def start_task_process(task, prompt: str | None = None):
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
        log_file = _open_task_log(task_id)
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    script_path,
                    instruction,
                    "--task-id",
                    task_id,
                    "--max-steps",
                    str(settings.AUTOGLM_MAX_STEPS),
                ],
                cwd=project_root,
                env=os.environ.copy(),
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
        finally:
            log_file.close()
    else:
        script_path = os.path.join(project_root, "run_workflow.py")
        if not os.path.exists(script_path):
            raise FileNotFoundError("Workflow script not found")
        env = os.environ.copy()
        env["TB_KEYWORD"] = task.keyword or ""
        log_file = _open_task_log(task_id)
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

    start_collection_watcher(task_id, project_root, process=process)
    return process
