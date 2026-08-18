from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from worker.artifacts import ArtifactTracker
from worker.client import WorkerClient


LEASE_HEARTBEAT_SECONDS = 30
LOG_CHUNK_BYTES = 200 * 1024
TARGET_APP_PACKAGES = {
    "淘宝闪购": "com.taobao.taobao",
    "京东秒送": "com.jingdong.app.mall",
    "拼多多": "com.xunmeng.pinduoduo",
    "小红书": "com.xingin.xhs",
    "淘宝": "com.taobao.taobao",
    "京东": "com.jingdong.app.mall",
    "天猫": "com.tmall.wireless",
    "抖音": "com.ss.android.ugc.aweme",
}


@dataclass
class ExecutionResult:
    exit_code: int
    uploaded_count: int
    log_path: Path


def execute_claim(repo_root: Path, client: WorkerClient, node_key: str, claim: dict[str, Any]) -> ExecutionResult:
    run = claim["run"]
    task = claim["task"]
    device = claim["device"]
    run_id = str(run["id"])
    task_id = str(task["id"])
    run_dir = repo_root / "worker_runs" / run_id
    artifacts_dir = run_dir / "artifacts"
    log_path = run_dir / "worker.log"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    command = _build_command(repo_root, task, run_id, task_id, str(device["serial"]), artifacts_dir)
    env = _build_env(artifacts_dir, task_id, run_id, str(device["serial"]), task)
    tracker = ArtifactTracker()
    uploaded_count = 0

    process = None
    try:
        with log_path.open("a", encoding="utf-8") as log_file:
            _write_log_line(log_file, f"worker command: {' '.join(command)}")
            process = subprocess.Popen(
                command,
                cwd=str(repo_root),
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
            last_heartbeat = 0.0
            while process.poll() is None:
                now = time.monotonic()
                if now - last_heartbeat >= LEASE_HEARTBEAT_SECONDS:
                    client.extend_lease(run_id, node_key)
                    last_heartbeat = now
                time.sleep(2)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        _force_stop_target_app(task, str(device["serial"]), log_path)

    for artifact in tracker.scan_new(artifacts_dir):
        try:
            client.upload_artifact(
                run_id,
                node_key,
                artifact.path,
                source_app=task.get("target_app"),
                scenario=task.get("target_scenario"),
            )
            tracker.mark_uploaded(artifact)
            uploaded_count += 1
        except Exception as exc:
            with log_path.open("a", encoding="utf-8") as log_file:
                _write_log_line(log_file, f"artifact upload failed {artifact.path}: {exc}")

    try:
        _upload_log_tail(client, run_id, node_key, log_path)
    except Exception as exc:
        with log_path.open("a", encoding="utf-8") as log_file:
            _write_log_line(log_file, f"log upload failed: {exc}")
    return ExecutionResult(exit_code=process.returncode or 0, uploaded_count=uploaded_count, log_path=log_path)


def _target_app_package(task: dict[str, Any]) -> str | None:
    app_name = str(task.get("target_app") or "").strip()
    if not app_name:
        return None
    for name in sorted(TARGET_APP_PACKAGES, key=len, reverse=True):
        if name in app_name:
            return TARGET_APP_PACKAGES[name]
    if "." in app_name and " " not in app_name:
        return app_name
    return None


def _force_stop_target_app(task: dict[str, Any], device_serial: str, log_path: Path) -> bool:
    app_name = str(task.get("target_app") or "").strip() or "<unknown>"
    package = _target_app_package(task)
    if not package:
        with log_path.open("a", encoding="utf-8") as log_file:
            _write_log_line(log_file, f"worker cleanup skipped: package not found for {app_name}")
        return False

    command = ["adb", "-s", device_serial, "shell", "am", "force-stop", package]
    try:
        subprocess.run(command, capture_output=True, text=True, timeout=10, check=True)
        with log_path.open("a", encoding="utf-8") as log_file:
            _write_log_line(log_file, f"worker cleanup: force-stopped {app_name} ({package})")
        return True
    except Exception as exc:
        with log_path.open("a", encoding="utf-8") as log_file:
            _write_log_line(log_file, f"worker cleanup failed for {app_name} ({package}): {exc}")
        return False


def _build_command(repo_root: Path, task: dict[str, Any], run_id: str, task_id: str, device_serial: str, output_dir: Path) -> list[str]:
    mode = task.get("mode") or "uiautomator2"
    if mode == "scroll_promo":
        package = _target_app_package(task)
        if not package:
            raise ValueError(f"unsupported target app for scroll promo task: {task.get('target_app')}")
        return [
            sys.executable,
            str(repo_root / "run_scroll_promo_chain.py"),
            "--app",
            str(task.get("target_app") or "京东"),
            "--package",
            package,
            "--device-id",
            device_serial,
            "--output-dir",
            str(output_dir),
            "--swipes",
            os.getenv("SCROLL_PROMO_SWIPE_COUNT", "1"),
            "--max-frames",
            os.getenv("SCROLL_PROMO_MAX_FRAMES", "6"),
            "--fps",
            os.getenv("SCROLL_PROMO_FPS", "10"),
        ]
    if mode == "autoglm":
        prompt = (
            task.get("generated_instruction")
            or task.get("keyword")
            or task.get("name")
            or "打开目标应用并完成截图任务"
        )
        return [
            sys.executable,
            str(repo_root / "run_autoglm.py"),
            str(prompt),
            "--task-id",
            task_id,
            "--task-run-id",
            run_id,
            "--device-id",
            device_serial,
            "--output-dir",
            str(output_dir),
        ]
    if mode == "uiautomator2":
        return [sys.executable, str(repo_root / "run_workflow.py")]
    raise ValueError(f"unsupported task mode: {mode}")


def _build_env(output_dir: Path, task_id: str, run_id: str, device_serial: str, task: dict[str, Any]) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "CAPTURE_SINK": "local_files",
            "TASK_OUTPUT_DIR": str(output_dir),
            "TASK_ID": task_id,
            "TASK_RUN_ID": run_id,
            "PHONE_AGENT_DEVICE_ID": device_serial,
            "WORKFLOW_TASK_NAME": _env_value(task.get("name")),
            "WORKFLOW_TASK_KEYWORD": _env_value(task.get("keyword")),
            "WORKFLOW_TARGET_APP": _env_value(task.get("target_app")),
            "WORKFLOW_TARGET_SCENARIO": _env_value(task.get("target_scenario")),
            "WORKFLOW_GENERATED_INSTRUCTION": _env_value(task.get("generated_instruction")),
            "DATABASE_URL": "",
            "JD_OSS_ACCESS_KEY_ID": "",
            "JD_OSS_SECRET_ACCESS_KEY": "",
        }
    )
    return env


def _env_value(value: Any) -> str:
    return "" if value is None else str(value)


def _write_log_line(log_file, text: str) -> None:
    log_file.write(text.rstrip() + "\n")
    log_file.flush()


def _upload_log_tail(client: WorkerClient, run_id: str, node_key: str, log_path: Path) -> None:
    if not log_path.exists():
        return
    data = log_path.read_bytes()
    if len(data) > LOG_CHUNK_BYTES:
        data = data[-LOG_CHUNK_BYTES:]
    if data:
        client.upload_log(run_id, node_key, data.decode("utf-8", errors="replace"))
