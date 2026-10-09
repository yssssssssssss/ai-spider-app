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
from worker.model_trace import read_model_calls
from worker.inspection_report import normalize_floor_reports


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
REPORT_FILENAMES = {
    "scroll_promo": "promotion_detections.json",
    "jd_new_floor_audit": "jd_new_floor_report.json",
}


@dataclass
class ExecutionResult:
    exit_code: int
    uploaded_count: int
    log_path: Path
    result_json: dict[str, Any] | None = None


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
    client_headers = getattr(client, "headers", {})
    env = _build_env(
        artifacts_dir,
        task_id,
        run_id,
        str(device["serial"]),
        task,
        worker_base_url=str(getattr(client, "base_url", "")),
        worker_token=str(client_headers.get("X-Worker-Token", "")),
    )
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

    report_filename = REPORT_FILENAMES.get(str(task.get("mode") or ""))
    report_path = artifacts_dir / report_filename if report_filename else None
    result_json = None
    if report_path and report_path.exists():
        try:
            import json

            result_json = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            with log_path.open("a", encoding="utf-8") as log_file:
                _write_log_line(log_file, f"result report read failed: {exc}")

    for artifact in tracker.scan_new(artifacts_dir):
        try:
            client.extend_lease(run_id, node_key)
            uploaded = client.upload_artifact(
                run_id,
                node_key,
                artifact.path,
                source_app=task.get("target_app"),
                scenario=task.get("target_scenario"),
            )
            if result_json:
                _attach_result_artifact(result_json, artifact.path.name, uploaded)
            tracker.mark_uploaded(artifact)
            uploaded_count += 1
        except Exception as exc:
            with log_path.open("a", encoding="utf-8") as log_file:
                _write_log_line(log_file, f"artifact upload failed {artifact.path}: {exc}")

    model_calls = read_model_calls(artifacts_dir)
    if model_calls:
        result_json = {**(result_json or {}), "model_calls": model_calls}
    if result_json:
        inspections = normalize_floor_reports(result_json, task, run_id, str(device["serial"]))
        if inspections:
            result_json["inspection_reports"] = inspections

    try:
        client.extend_lease(run_id, node_key)
        _upload_log_tail(client, run_id, node_key, log_path)
    except Exception as exc:
        with log_path.open("a", encoding="utf-8") as log_file:
            _write_log_line(log_file, f"log upload failed: {exc}")
    return ExecutionResult(
        exit_code=process.returncode or 0,
        uploaded_count=uploaded_count,
        log_path=log_path,
        result_json=result_json,
    )


def _attach_result_artifact(result_json: dict[str, Any], filename: str, uploaded: dict[str, Any]) -> None:
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            artifact_names = {
                value.get("filename"),
                value.get("raw_file"),
                value.get("annotated_file"),
            }
            if filename in artifact_names:
                value["image_id"] = uploaded.get("image_id")
                value["image_file_path"] = uploaded.get("file_path")
                value["oss_url"] = uploaded.get("oss_url")
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(result_json)


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
    if mode == "jd_new_floor_audit":
        app_name = str(task.get("target_app") or "京东")
        package = _target_app_package({"target_app": app_name})
        if not package:
            raise ValueError(f"unsupported target app for floor audit task: {app_name}")
        return [
            sys.executable,
            str(repo_root / "run_jd_new_floor_audit.py"),
            "--app", app_name,
            "--package", package,
            "--device-id", device_serial,
            "--output-dir", str(output_dir),
            "--target-tab", "新品",
            "--page-wait", os.getenv("JD_NEW_FLOOR_PAGE_WAIT_SECONDS", "5"),
        ]
    if mode == "scroll_promo":
        config = task.get("scroll_promo_config_json") or {}
        configured_app = str(config.get("target_app") or task.get("target_app") or "京东")
        package = _target_app_package({"target_app": configured_app})
        if not package:
            raise ValueError(f"unsupported target app for scroll promo task: {configured_app}")
        return [
            sys.executable,
            str(repo_root / "run_scroll_promo_chain.py"),
            "--app", configured_app,
            "--package", package,
            "--device-id", device_serial,
            "--output-dir", str(output_dir),
            "--swipes", os.getenv("SCROLL_PROMO_SWIPE_COUNT", "1"),
            "--max-frames", str(config.get("max_frames", 6)),
            "--fps", str(config.get("fps", 10)),
            "--target-tab", str(config.get("target_tab", "新品")),
            "--page-wait", str(config.get("page_wait_seconds", 5)),
            "--static-frames", str(config.get("static_frame_count", 3)),
            "--static-scroll-distance", str(config.get("static_scroll_distance_px", 600)),
            "--static-confidence", str(config.get("static_confidence_threshold", 0.75)),
            "--swipe-duration", str(config.get("dynamic_swipe_duration_seconds", 2)),
            "--motion-offset", str(config.get("motion_window_offset_seconds", 0.5)),
            "--motion-duration", str(config.get("motion_window_duration_seconds", 1)),
            "--collapse-ratio", str(config.get("collapse_width_ratio", 2 / 3)),
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


def _build_env(
    output_dir: Path,
    task_id: str,
    run_id: str,
    device_serial: str,
    task: dict[str, Any],
    *,
    worker_base_url: str = "",
    worker_token: str = "",
) -> dict[str, str]:
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
    if worker_base_url:
        env["WORKER_BASE_URL"] = worker_base_url
    if worker_token:
        env["WORKER_API_TOKEN"] = worker_token
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
