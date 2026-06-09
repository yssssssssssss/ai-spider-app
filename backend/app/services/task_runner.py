import os
import re
import subprocess
import sys
from datetime import UTC, datetime

from app import crud
from app.config import settings
from app.database import SessionLocal
from app.services.collector_bridge import start_collection_watcher
from app.services.task_events import ensure_queue


LONG_CAPTURE_MODE = "product_detail_long_image"
LONG_CAPTURE_TRIGGERS = ("长图", "拼接", "拼长图", "滚动", "多屏", "每一屏", "全页")
PRODUCT_DETAIL_TRIGGERS = ("商品详情", "详情页", "商品页")
LONG_CAPTURE_NAVIGATION_RULE = (
    "执行约束：你只负责进入商品详情页首屏并停留结束；"
    "不要滚动详情页，不要执行多屏截图，不要尝试拼接长图；"
    "后续滚动截图、重复区域裁切和长图拼接由平台自动处理。"
)


def _task_request_description(task) -> str:
    request = getattr(task, "request", None)
    return getattr(request, "description", "") if request else ""


def _task_capture_text(task, prompt: str | None) -> str:
    parts = [
        getattr(task, "name", ""),
        getattr(task, "keyword", ""),
        getattr(task, "target_scenario", ""),
        getattr(task, "generated_instruction", ""),
        prompt or "",
        _task_request_description(task),
    ]
    return " ".join(str(part or "") for part in parts)


def product_detail_long_capture_count(task, prompt: str | None = None) -> int | None:
    text = _task_capture_text(task, prompt)
    if not any(marker in text for marker in PRODUCT_DETAIL_TRIGGERS):
        return None
    if not any(marker in text for marker in LONG_CAPTURE_TRIGGERS):
        return None

    match = re.search(r"(\d{1,2})\s*(?:屏|页|张)", text)
    count = int(match.group(1)) if match else 10
    return max(1, min(count, 30))


def apply_product_detail_long_capture_rule(instruction: str) -> str:
    if LONG_CAPTURE_NAVIGATION_RULE in instruction:
        return instruction
    return f"{instruction.rstrip('。')}。{LONG_CAPTURE_NAVIGATION_RULE}"


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
            started_at=datetime.now(UTC).replace(tzinfo=None),
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
        long_capture_count = product_detail_long_capture_count(task, instruction)
        if long_capture_count:
            instruction = apply_product_detail_long_capture_rule(instruction)
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
            command = [
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
                "--max-steps",
                str(settings.AUTOGLM_MAX_STEPS),
            ]
            if long_capture_count:
                command.extend([
                    "--post-capture-mode",
                    LONG_CAPTURE_MODE,
                    "--long-screenshot-count",
                    str(long_capture_count),
                    "--no-capture",
                ])
            process = subprocess.Popen(
                command,
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
