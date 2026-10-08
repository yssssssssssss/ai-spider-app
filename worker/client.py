from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import Any

import httpx


ARTIFACT_UPLOAD_TIMEOUT_SECONDS = 180.0
PROMOTION_DETECTION_TIMEOUT_SECONDS = 180.0
FLOOR_ANALYSIS_TIMEOUT_SECONDS = 420.0


class WorkerClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        if not base_url.strip():
            raise ValueError("base_url is required")
        if not token.strip():
            raise ValueError("worker token is required")
        self.base_url = self._worker_base_url(base_url)
        self.headers = {"X-Worker-Token": token}
        self.client = httpx.Client(timeout=timeout)

    @staticmethod
    def _worker_base_url(base_url: str) -> str:
        url = base_url.strip().rstrip("/")
        if url.endswith("/api/worker"):
            return url
        if url.endswith("/api"):
            return f"{url}/worker"
        return f"{url}/api/worker"

    def close(self) -> None:
        self.client.close()

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.post(f"{self.base_url}{path}", json=payload, headers=self.headers)
        response.raise_for_status()
        return response.json()

    def register(self, node_key: str, name: str | None = None, version: str | None = None) -> dict[str, Any]:
        return self._post_json("/register", {"node_key": node_key, "name": name, "version": version})

    def heartbeat(self, node_key: str, status: str = "online") -> dict[str, Any]:
        return self._post_json("/heartbeat", {"node_key": node_key, "status": status})

    def report_devices(self, node_key: str, devices: list[dict[str, str]]) -> dict[str, Any]:
        return self._post_json("/devices", {"node_key": node_key, "devices": devices})

    def claim(self, node_key: str, device_serials: list[str], capabilities: list[str]) -> dict[str, Any]:
        return self._post_json(
            "/task-runs/claim",
            {"node_key": node_key, "device_serials": device_serials, "capabilities": capabilities},
        )

    def extend_lease(self, run_id: str, node_key: str) -> dict[str, Any]:
        return self._post_json(f"/task-runs/{run_id}/heartbeat", {"node_key": node_key})

    def upload_result(self, run_id: str, node_key: str, result_json: dict[str, Any]) -> dict[str, Any]:
        return self._post_json(
            f"/task-runs/{run_id}/result",
            {"node_key": node_key, "result_json": result_json},
        )

    def finish(self, run_id: str, node_key: str, exit_code: int, screenshot_count: int) -> dict[str, Any]:
        return self._post_json(
            f"/task-runs/{run_id}/finish",
            {"node_key": node_key, "exit_code": exit_code, "screenshot_count": screenshot_count},
        )

    def fail(self, run_id: str, node_key: str, exit_code: int, failure_reason: str) -> dict[str, Any]:
        return self._post_json(
            f"/task-runs/{run_id}/fail",
            {"node_key": node_key, "exit_code": exit_code, "failure_reason": failure_reason},
        )

    def detect_promotion(self, path: Path) -> dict[str, Any]:
        with path.open("rb") as handle:
            response = self.client.post(
                f"{self.base_url}/promotion-detect",
                files={"file": (path.name, handle, _guess_mime(path))},
                headers=self.headers,
                timeout=PROMOTION_DETECTION_TIMEOUT_SECONDS,
            )
        response.raise_for_status()
        return response.json()

    def analyze_jd_new_floor(self, path: Path) -> dict[str, Any]:
        with path.open("rb") as handle:
            response = self.client.post(
                f"{self.base_url}/jd-new-floor-analyze",
                files={"file": (path.name, handle, _guess_mime(path))},
                headers=self.headers,
                timeout=FLOOR_ANALYSIS_TIMEOUT_SECONDS,
            )
        response.raise_for_status()
        return response.json()

    def locate_jd_secondary_tab(self, path: Path) -> dict[str, Any]:
        with path.open("rb") as handle:
            response = self.client.post(
                f"{self.base_url}/jd-secondary-tab-locate",
                files={"file": (path.name, handle, _guess_mime(path))},
                headers=self.headers,
                timeout=FLOOR_ANALYSIS_TIMEOUT_SECONDS,
            )
        response.raise_for_status()
        return response.json()

    def analyze_jd_secondary_tab(self, paths: dict[str, Path], z1_bbox: list[int]) -> dict[str, Any]:
        required = (
            "z1_before",
            "z1_after_left",
            "z2_before",
            "z2_after_left",
            "z3_before",
        )
        missing = [key for key in required if key not in paths]
        if missing:
            raise ValueError("missing secondary Tab frames: " + ", ".join(missing))
        with ExitStack() as stack:
            files = {
                key: (
                    paths[key].name,
                    stack.enter_context(paths[key].open("rb")),
                    _guess_mime(paths[key]),
                )
                for key in required
            }
            response = self.client.post(
                f"{self.base_url}/jd-secondary-tab-analyze",
                data={"z1_top": str(z1_bbox[1]), "z1_bottom": str(z1_bbox[3])},
                files=files,
                headers=self.headers,
                timeout=FLOOR_ANALYSIS_TIMEOUT_SECONDS,
            )
        response.raise_for_status()
        return response.json()

    def upload_log(self, run_id: str, node_key: str, text: str) -> dict[str, Any]:
        response = self.client.post(
            f"{self.base_url}/task-runs/{run_id}/logs",
            params={"node_key": node_key},
            content=text.encode("utf-8", errors="replace"),
            headers={**self.headers, "Content-Type": "text/plain; charset=utf-8"},
        )
        response.raise_for_status()
        return response.json()

    def upload_artifact(
        self,
        run_id: str,
        node_key: str,
        path: Path,
        *,
        source_app: str | None = None,
        scenario: str | None = None,
    ) -> dict[str, Any]:
        with path.open("rb") as handle:
            files = {"file": (path.name, handle, _guess_mime(path))}
            data = {"node_key": node_key}
            if source_app:
                data["source_app"] = source_app
            if scenario:
                data["scenario"] = scenario
            response = self.client.post(
                f"{self.base_url}/task-runs/{run_id}/artifacts",
                data=data,
                files=files,
                headers=self.headers,
                timeout=ARTIFACT_UPLOAD_TIMEOUT_SECONDS,
            )
        response.raise_for_status()
        return response.json()


def _guess_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in (".jpg", ".jpeg"):
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"
