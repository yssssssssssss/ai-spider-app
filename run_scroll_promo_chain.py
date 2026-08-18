#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from worker.client import WorkerClient
from worker.executor import TARGET_APP_PACKAGES
from worker.scroll_promo_chain import ScrollPromoChain, ScrollPromoConfig


def package_for(app_name: str) -> str:
    for name in sorted(TARGET_APP_PACKAGES, key=len, reverse=True):
        if name in app_name:
            return TARGET_APP_PACKAGES[name]
    if "." in app_name and " " not in app_name:
        return app_name
    raise ValueError(f"Unsupported target app: {app_name}")


def parse_args():
    parser = argparse.ArgumentParser(description="Open an app, capture in-motion swipe frames, detect promotion overlays and draw red boxes")
    parser.add_argument("--app", default=os.getenv("WORKFLOW_TARGET_APP") or "京东")
    parser.add_argument("--package", default="")
    parser.add_argument("--device-id", default=os.getenv("PHONE_AGENT_DEVICE_ID") or "")
    parser.add_argument("--output-dir", default=os.getenv("TASK_OUTPUT_DIR") or "worker_runs/manual-scroll-promo/artifacts")
    parser.add_argument("--swipes", type=int, default=int(os.getenv("SCROLL_PROMO_SWIPE_COUNT", "1")))
    parser.add_argument("--max-frames", type=int, default=int(os.getenv("SCROLL_PROMO_MAX_FRAMES", "6")))
    parser.add_argument("--fps", type=int, default=int(os.getenv("SCROLL_PROMO_FPS", "10")))
    parser.add_argument("--app-wait", type=float, default=float(os.getenv("SCROLL_PROMO_APP_WAIT_SECONDS", "6")))
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
        chain = ScrollPromoChain(detect=client.detect_promotion)
        result = chain.run(
            ScrollPromoConfig(
                app_name=args.app,
                package=args.package or package_for(args.app),
                device_serial=args.device_id,
                output_dir=Path(args.output_dir).resolve(),
                swipe_count=max(1, min(args.swipes, 10)),
                max_frames=max(1, min(args.max_frames, 10)),
                fps=max(1, min(args.fps, 30)),
                app_wait_seconds=max(0.0, min(args.app_wait, 60.0)),
            )
        )
        report = json.loads(result.report_path.read_text(encoding="utf-8"))
        print("PROMOTION_DETECTIONS_JSON=" + json.dumps(report, ensure_ascii=False, separators=(",", ":")))
        print(json.dumps({
            "capture_method": result.capture_method,
            "annotated_count": len(result.annotated_paths),
            "promo_detected_count": sum(bool(item.get("promo_present")) for item in result.detections),
            "report_path": str(result.report_path),
        }, ensure_ascii=False))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
