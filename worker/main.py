import argparse
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def parse_adb_devices(output: str) -> list[dict[str, str]]:
    devices = []
    for line in output.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        devices.append({
            "serial": serial,
            "status": "online" if state == "device" else "offline",
            "notes": state,
        })
    return devices


def adb_devices() -> list[dict[str, str]]:
    try:
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    return parse_adb_devices(result.stdout)


def _request_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        response = exc.response
        body = response.text[:300].replace("\n", " ")
        return f"HTTP {response.status_code}: {body}"
    return f"{type(exc).__name__}: {exc}"


def _log(message: str):
    print(message, flush=True)


class WorkerClient:
    def __init__(self, server: str, token: str, node_key: str):
        self.server = server.rstrip("/")
        self.node_key = node_key
        self.client = httpx.Client(headers={"X-Worker-Token": token}, timeout=60)

    def post(self, path: str, **kwargs):
        return self.client.post(f"{self.server}/api/worker{path}", **kwargs)

    def register(self, name: str, version: str):
        response = self.post("/register", json={"node_key": self.node_key, "name": name, "version": version})
        response.raise_for_status()
        return response.json()

    def heartbeat(self):
        response = self.post("/heartbeat", json={"node_key": self.node_key, "status": "online"})
        response.raise_for_status()

    def report_devices(self, devices: list[dict[str, str]]):
        response = self.post("/devices", json={"node_key": self.node_key, "devices": devices})
        response.raise_for_status()
        return response.json()

    def claim(self):
        response = self.post("/task-runs/claim", json={"node_key": self.node_key})
        if response.status_code == 204:
            return None
        response.raise_for_status()
        return response.json()

    def upload_log(self, run_id: str, content: str):
        if not content:
            return
        response = self.post(f"/task-runs/{run_id}/logs", json={"node_key": self.node_key, "content": content})
        response.raise_for_status()

    def upload_image(self, run_id: str, path: Path):
        with path.open("rb") as fh:
            response = self.post(
                f"/task-runs/{run_id}/images",
                data={"node_key": self.node_key},
                files={"file": (path.name, fh, _mime_type(path))},
            )
        response.raise_for_status()

    def finish(self, run_id: str, status: str, exit_code: int | None, failure_reason: str | None = None):
        response = self.post(
            f"/task-runs/{run_id}/finish",
            json={
                "node_key": self.node_key,
                "status": status,
                "exit_code": exit_code,
                "failure_reason": failure_reason,
            },
        )
        response.raise_for_status()


def _mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _image_files(output_dir: Path) -> list[Path]:
    if not output_dir.exists():
        return []
    return sorted(
        path
        for path in output_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES and not path.name.startswith("_temp_")
    )


def _run_claimed_task(claim: dict, work_root: Path) -> tuple[int, str, Path]:
    run = claim["run"]
    task = claim["task"]
    prompt = claim.get("prompt") or ""
    device_serial = claim.get("device_serial")
    run_id = run["id"]
    task_id = task["id"]
    output_dir = work_root / task_id / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "worker.log"
    env = os.environ.copy()
    env["TASK_ID"] = task_id
    env["TASK_RUN_ID"] = run_id
    env["TASK_OUTPUT_DIR"] = str(output_dir)
    if device_serial:
        env["PHONE_AGENT_DEVICE_ID"] = device_serial

    if task.get("mode") == "autoglm":
        if not prompt:
            return 1, "AutoGLM prompt is empty", output_dir
        cmd = [
            sys.executable,
            str(PROJECT_ROOT / "run_autoglm.py"),
            prompt,
            "--task-id",
            task_id,
            "--task-run-id",
            run_id,
            "--output-dir",
            str(output_dir),
            "--max-steps",
            str(claim.get("max_steps") or 10),
        ]
        if task.get("target_app"):
            cmd.extend(["--source-app", task["target_app"]])
        if device_serial:
            cmd.extend(["--device-id", device_serial])
    else:
        env["TB_KEYWORD"] = task.get("keyword") or ""
        cmd = [sys.executable, str(PROJECT_ROOT / "run_workflow.py")]

    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env, stdout=log_file, stderr=subprocess.STDOUT)
    return process.returncode, log_path.read_text(encoding="utf-8", errors="replace"), output_dir


def _register_until_ready(client: WorkerClient, args):
    while True:
        try:
            client.register(args.name, args.version)
            _log(f"Worker registered: node_key={args.node_key} server={client.server}")
            return
        except (httpx.HTTPError, OSError) as exc:
            _log(f"Worker register failed, retrying in {args.poll_interval}s: {_request_error(exc)}")
            time.sleep(args.poll_interval)


def _handle_claimed_task(client: WorkerClient, claim: dict, work_root: Path):
    run_id = claim["run"]["id"]
    try:
        exit_code, logs, output_dir = _run_claimed_task(claim, work_root)
        client.upload_log(run_id, logs)
        for image_path in _image_files(output_dir):
            client.upload_image(run_id, image_path)
        status = "completed" if exit_code == 0 else "failed"
        reason = None if exit_code == 0 else f"process exited with {exit_code}"
        client.finish(run_id, status, exit_code, reason)
    except Exception as exc:
        details = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        _log(f"Worker task failed for run {run_id}: {_request_error(exc)}")
        try:
            client.upload_log(run_id, f"\nWorker error:\n{details}\n")
        except Exception as upload_exc:
            _log(f"Worker failed to upload failure log for run {run_id}: {_request_error(upload_exc)}")
        try:
            client.finish(run_id, "failed", 1, str(exc))
        except Exception as finish_exc:
            _log(f"Worker failed to mark run failed for run {run_id}: {_request_error(finish_exc)}")


def run_loop(args):
    client = WorkerClient(args.server, args.token, args.node_key)
    work_root = Path(args.work_dir).resolve()
    _register_until_ready(client, args)
    while True:
        try:
            devices = adb_devices()
            client.heartbeat()
            client.report_devices(devices)
            claim = client.claim()
        except (httpx.HTTPError, OSError) as exc:
            _log(f"Worker poll failed, retrying in {args.poll_interval}s: {_request_error(exc)}")
            time.sleep(args.poll_interval)
            continue
        if not claim:
            time.sleep(args.poll_interval)
            continue

        _handle_claimed_task(client, claim, work_root)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Local Android device worker for the competitor analysis platform.")
    parser.add_argument("--server", required=True, help="Cloud server base URL, for example https://example.com")
    parser.add_argument("--token", default=os.getenv("WORKER_API_TOKEN"), help="Worker API token configured on the cloud server")
    parser.add_argument("--node-key", default=os.uname().nodename, help="Stable worker node key")
    parser.add_argument("--name", default=os.uname().nodename, help="Worker display name")
    parser.add_argument("--version", default="dev", help="Worker version label")
    parser.add_argument("--work-dir", default=str(PROJECT_ROOT / "worker_runs"), help="Local worker output directory")
    parser.add_argument("--poll-interval", type=int, default=5, help="Seconds between queue polls")
    args = parser.parse_args(argv)
    if not args.token:
        parser.error("--token or WORKER_API_TOKEN is required")
    return args


if __name__ == "__main__":
    run_loop(parse_args())
