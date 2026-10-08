from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


SUCCESS_CODE = 2000


class DongMacApiError(RuntimeError):
    """Raised when DongMAC rejects a request or returns an invalid response."""


@dataclass(frozen=True)
class DongMacCredentials:
    business_name: str
    workspace_token: str


def build_trigger_payload(
    *,
    template_id: int,
    operator: str,
    name: str = "本地 API 云真机测试",
    description: str = "由 ai-spider-app 本地 smoke test 触发",
    platform: str = "android",
    device_serial: str | None = None,
    callback_url: str | None = None,
    callback_token: str | None = None,
    instruction_ids: list[int] | None = None,
    extra_params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if template_id <= 0:
        raise ValueError("template_id must be a positive integer")
    operator = operator.strip()
    if not operator:
        raise ValueError("operator is required")

    payload: dict[str, Any] = {
        "templateId": template_id,
        "operator": operator,
        "name": name.strip() or "本地 API 云真机测试",
        "description": description.strip(),
        "platform": platform,
    }

    if extra_params:
        payload["repoConfig"] = {"extraParams": extra_params}

    if device_serial and device_serial.strip():
        payload["deviceStrategy"] = {
            "selectMode": "specify",
            "specifyDevices": [device_serial.strip()],
            "strategy": "separate",
        }

    if callback_url and callback_url.strip():
        callback: dict[str, Any] = {
            "callbackUrl": callback_url.strip(),
            "enabled": True,
        }
        if callback_token and callback_token.strip():
            callback["headers"] = {"X-DongMAC-Callback-Token": callback_token.strip()}
        payload["callbackConfigs"] = [callback]

    if instruction_ids:
        if any(instruction_id <= 0 for instruction_id in instruction_ids):
            raise ValueError("instruction_ids must contain positive integers")
        payload["caseConfig"] = {
            "uiGenieCase": {"instructionIds": instruction_ids},
        }

    return payload


class DongMacClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        client: httpx.Client | None = None,
    ):
        base_url = base_url.strip().rstrip("/")
        if not base_url:
            raise ValueError("base_url is required")
        self.base_url = base_url
        self._owns_client = client is None
        self.client = client or httpx.Client(timeout=timeout)

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> "DongMacClient":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def get_access_token(self, credentials: DongMacCredentials) -> str:
        business_name = credentials.business_name.strip()
        workspace_token = credentials.workspace_token.strip()
        if not business_name or not workspace_token:
            raise ValueError("business_name and workspace_token are required")

        payload = self._post(
            "/api/v1/auth/access-token",
            json={
                "businessName": business_name,
                "workspaceToken": workspace_token,
            },
        )
        data = payload.get("data") or {}
        access_token = str(data.get("accessToken") or "").strip()
        if not access_token:
            raise DongMacApiError("DongMAC response did not contain accessToken")
        return access_token

    def trigger_task(self, access_token: str, payload: dict[str, Any]) -> int:
        token = access_token.strip()
        if not token:
            raise ValueError("access_token is required")
        response = self._post(
            "/api/v1/task/ci/trigger",
            json=payload,
            headers={"accessToken": token},
        )
        task_record_id = response.get("data")
        if not isinstance(task_record_id, int):
            raise DongMacApiError("DongMAC response did not contain an integer task record ID")
        return task_record_id

    def _post(
        self,
        path: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self.client.post(
                f"{self.base_url}{path}",
                json=json,
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise DongMacApiError(f"DongMAC request failed: {exc}") from exc

        if not isinstance(payload, dict):
            raise DongMacApiError("DongMAC returned a non-object response")
        if payload.get("code") != SUCCESS_CODE or payload.get("success") is not True:
            message = str(payload.get("message") or "unknown DongMAC error")
            raise DongMacApiError(message)
        return payload
