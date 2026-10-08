#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from worker.client import WorkerClient
from worker.executor import TARGET_APP_PACKAGES
from worker.jd_new_floor_audit import JdNewFloorAudit, JdNewFloorConfig


def package_for(app_name: str) -> str:
    for name in sorted(TARGET_APP_PACKAGES, key=len, reverse=True):
        if name in app_name:
            return TARGET_APP_PACKAGES[name]
    if "." in app_name and " " not in app_name:
        return app_name
    raise ValueError(f"Unsupported target app: {app_name}")


def parse_args():
    parser = argparse.ArgumentParser(description="Capture and audit the JD new-product floor")
    parser.add_argument("--app", default="京东")
    parser.add_argument("--package", default="")
    parser.add_argument("--device-id", default=os.getenv("PHONE_AGENT_DEVICE_ID") or "")
    parser.add_argument("--output-dir", default=os.getenv("TASK_OUTPUT_DIR") or "worker_runs/manual-jd-new-floor/artifacts")
    parser.add_argument("--target-tab", default="新品")
    parser.add_argument("--app-wait", type=float, default=6.0)
    parser.add_argument("--page-wait", type=float, default=5.0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.device_id:
        raise SystemExit("--device-id or PHONE_AGENT_DEVICE_ID is required")
    base_url = os.getenv("WORKER_BASE_URL") or os.getenv("AI_SPIDER_BASE_URL") or ""
    token = os.getenv("WORKER_API_TOKEN") or ""
    if not base_url or not token:
        raise SystemExit("WORKER_BASE_URL and WORKER_API_TOKEN are required")

    client = WorkerClient(base_url, token)
    try:
        result = JdNewFloorAudit(
            analyze=client.analyze_jd_new_floor,
            locate_secondary=client.locate_jd_secondary_tab,
            analyze_secondary=client.analyze_jd_secondary_tab,
        ).run(
            JdNewFloorConfig(
                app_name=args.app,
                package=args.package or package_for(args.app),
                device_serial=args.device_id,
                output_dir=Path(args.output_dir).resolve(),
                target_tab=args.target_tab,
                app_wait_seconds=max(0.0, min(args.app_wait, 60.0)),
                page_wait_seconds=max(0.0, min(args.page_wait, 60.0)),
            )
        )
        artifact_count = sum(1 for path in result.report_path.parent.iterdir() if path.suffix.lower() == ".png")
        print("JD_NEW_FLOOR_REPORT=" + json.dumps(result.report, ensure_ascii=False, separators=(",", ":")))
        print(json.dumps({"report_path": str(result.report_path), "artifact_count": artifact_count}, ensure_ascii=False))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
