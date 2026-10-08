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
    parser.add_argument("--target-tab", default=os.getenv("SCROLL_PROMO_TARGET_TAB", "新品"))
    parser.add_argument("--page-wait", type=float, default=float(os.getenv("SCROLL_PROMO_PAGE_WAIT_SECONDS", "5")))
    parser.add_argument("--static-frames", type=int, default=int(os.getenv("SCROLL_PROMO_STATIC_FRAMES", "3")))
    parser.add_argument("--static-scroll-distance", type=int, default=int(os.getenv("SCROLL_PROMO_STATIC_SCROLL_DISTANCE_PX", "600")))
    parser.add_argument("--static-confidence", type=float, default=float(os.getenv("SCROLL_PROMO_STATIC_CONFIDENCE", "0.75")))
    parser.add_argument("--swipe-duration", type=float, default=float(os.getenv("SCROLL_PROMO_SWIPE_DURATION_SECONDS", "2")))
    parser.add_argument("--motion-offset", type=float, default=float(os.getenv("SCROLL_PROMO_MOTION_OFFSET_SECONDS", "0.5")))
    parser.add_argument("--motion-duration", type=float, default=float(os.getenv("SCROLL_PROMO_MOTION_DURATION_SECONDS", "1")))
    parser.add_argument("--collapse-ratio", type=float, default=float(os.getenv("SCROLL_PROMO_COLLAPSE_WIDTH_RATIO", str(2 / 3))))
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
                target_tab=args.target_tab,
                page_wait_seconds=max(0.0, min(args.page_wait, 60.0)),
                static_frame_count=max(1, min(args.static_frames, 5)),
                static_scroll_distance_px=max(50, min(args.static_scroll_distance, 1200)),
                static_confidence_threshold=max(0.5, min(args.static_confidence, 0.99)),
                swipe_duration_ms=round(max(0.5, min(args.swipe_duration, 5.0)) * 1000),
                motion_window_offset_seconds=max(0.0, min(args.motion_offset, 4.0)),
                motion_window_duration_seconds=max(0.2, min(args.motion_duration, 3.0)),
                collapse_width_ratio=max(0.01, min(args.collapse_ratio, 0.99)),
            )
        )
        report = json.loads(result.report_path.read_text(encoding="utf-8"))
        print("PROMOTION_DETECTIONS_JSON=" + json.dumps(report, ensure_ascii=False, separators=(",", ":")))
        print(json.dumps({
            "capture_method": result.capture_method,
            "annotated_count": len(result.annotated_paths),
            "promo_detected_count": sum(bool(item.get("promo_present")) for item in result.detections),
            "collapsed_frame_count": report.get("summary", {}).get("collapsed_frame_count", 0),
            "report_path": str(result.report_path),
        }, ensure_ascii=False))
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
