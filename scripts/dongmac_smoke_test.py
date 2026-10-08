#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.services.dongmac_client import (  # noqa: E402
    DongMacApiError,
    DongMacClient,
    DongMacCredentials,
    build_trigger_payload,
)


DEFAULT_BASE_URL = "http://service-test-dmtc.jdtest.net"
SENSITIVE_KEY_PARTS = ("token", "password", "secret", "accesskey")


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _env_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    return int(value) if value else None


def _json_object(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"invalid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("extra params must be a JSON object")
    return parsed


def _redact_sensitive_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "<redacted>"
            if any(part in key.lower() for part in SENSITIVE_KEY_PARTS)
            else _redact_sensitive_values(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_values(item) for item in value]
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create one DongMAC test task through the documented HTTP API.",
    )
    parser.add_argument("--execute", action="store_true", help="Send requests. Without this flag, only print the sanitized payload.")
    parser.add_argument("--allow-http", action="store_true", help="Allow credentials over an HTTP URL. Use only on a trusted internal network.")
    parser.add_argument("--base-url", default=os.getenv("DONGMAC_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--business-name", default=os.getenv("DONGMAC_BUSINESS_NAME", ""))
    parser.add_argument("--workspace-token", default=os.getenv("DONGMAC_WORKSPACE_TOKEN", ""))
    parser.add_argument("--template-id", type=int, default=_env_int("DONGMAC_TEMPLATE_ID"))
    parser.add_argument("--operator", default=os.getenv("DONGMAC_OPERATOR", ""), help="ERP/operator recorded by DongMAC")
    parser.add_argument("--name", default="本地 API 云真机测试")
    parser.add_argument("--description", default="由 ai-spider-app 本地 smoke test 触发")
    parser.add_argument("--platform", choices=("android", "ios", "harmony"), default="android")
    parser.add_argument("--device-serial", default=os.getenv("DONGMAC_DEVICE_SERIAL", ""))
    parser.add_argument(
        "--instruction-id",
        action="append",
        type=int,
        default=[],
        help="UI_Genie instruction ID configured on DongMAC; repeat for multiple instructions",
    )
    parser.add_argument("--callback-url", default=os.getenv("DONGMAC_CALLBACK_URL", ""))
    parser.add_argument("--callback-token", default=os.getenv("DONGMAC_CALLBACK_TOKEN", ""))
    parser.add_argument("--target-url", default="", help="Passed to the template as repoConfig.extraParams.targetUrl")
    parser.add_argument("--instruction", default="", help="Passed to the template as repoConfig.extraParams.instruction")
    parser.add_argument("--extra-params", type=_json_object, default={}, help="Additional repoConfig.extraParams JSON object")
    parser.add_argument("--timeout", type=float, default=30.0)
    return parser.parse_args()


def _required(value: Any, name: str) -> Any:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"{name} is required")
    return value


def main() -> int:
    _load_env_file(PROJECT_ROOT / ".env.dongmac.local")
    args = parse_args()

    template_id = _required(args.template_id, "DONGMAC_TEMPLATE_ID / --template-id")
    operator = _required(args.operator, "DONGMAC_OPERATOR / --operator")
    extra_params = dict(args.extra_params)
    if args.target_url:
        extra_params["targetUrl"] = args.target_url
    if args.instruction:
        extra_params["instruction"] = args.instruction

    payload = build_trigger_payload(
        template_id=template_id,
        operator=operator,
        name=args.name,
        description=args.description,
        platform=args.platform,
        device_serial=args.device_serial,
        callback_url=args.callback_url,
        callback_token=args.callback_token,
        instruction_ids=args.instruction_id,
        extra_params=extra_params,
    )

    preview = {
        "mode": "execute" if args.execute else "dry-run",
        "baseUrl": args.base_url.rstrip("/"),
        "authRequest": {
            "businessName": args.business_name or "<required for --execute>",
            "workspaceToken": "<redacted>",
        },
        "triggerRequest": _redact_sensitive_values(payload),
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))

    if not args.execute:
        print("\nDry run only. Add --execute after checking the payload.")
        return 0

    parsed_url = urlparse(args.base_url)
    if parsed_url.scheme != "https" and not args.allow_http:
        raise ValueError("Refusing to send credentials over HTTP. Use HTTPS or add --allow-http on a trusted internal network.")

    credentials = DongMacCredentials(
        business_name=_required(args.business_name, "DONGMAC_BUSINESS_NAME / --business-name"),
        workspace_token=_required(args.workspace_token, "DONGMAC_WORKSPACE_TOKEN / --workspace-token"),
    )
    with DongMacClient(args.base_url, timeout=args.timeout) as client:
        access_token = client.get_access_token(credentials)
        task_record_id = client.trigger_task(access_token, payload)

    print(json.dumps({
        "success": True,
        "taskRecordId": task_record_id,
        "message": "DongMAC accepted the test task. Check the platform task record or configured callback for completion.",
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, DongMacApiError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
