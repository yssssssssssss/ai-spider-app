from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from pathlib import Path

import httpx

from worker.adb_devices import list_adb_devices
from worker.client import WorkerClient
from worker.executor import execute_claim


VERSION = "2026.08.17"


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    client = WorkerClient(args.base_url, args.token)
    capabilities = [item.strip() for item in args.capabilities.split(",") if item.strip()]

    try:
        client.register(args.node_key, name=args.name, version=VERSION)
        print(f"✅ worker registered: {args.node_key}")
        while True:
            try:
                client.heartbeat(args.node_key)
                devices = list_adb_devices()
                client.report_devices(args.node_key, devices)
                online_serials = [item["serial"] for item in devices if item.get("status") == "online"]
                claim = client.claim(args.node_key, online_serials, capabilities)
                if claim.get("claimed"):
                    run_id = claim["run"]["id"]
                    print(f"🎯 claimed run {run_id} on {claim['device']['serial']}")
                    try:
                        result = execute_claim(repo_root, client, args.node_key, claim)
                        if result.result_json:
                            client.extend_lease(run_id, args.node_key)
                            client.upload_result(run_id, args.node_key, result.result_json)
                        if result.exit_code == 0:
                            client.extend_lease(run_id, args.node_key)
                            client.finish(run_id, args.node_key, result.exit_code, result.uploaded_count)
                            print(f"✅ finished run {run_id}, uploaded={result.uploaded_count}")
                        else:
                            client.fail(run_id, args.node_key, result.exit_code, f"process exited with {result.exit_code}")
                            print(f"❌ failed run {run_id}, exit={result.exit_code}")
                    except Exception as exc:
                        try:
                            client.fail(run_id, args.node_key, 1, str(exc))
                        finally:
                            print(f"❌ run {run_id} failed: {exc}")
                            if args.once:
                                return 1
                elif args.once:
                    print("ℹ️ no task claimed")
                    return 0
                time.sleep(max(1, int(claim.get("poll_seconds") or args.poll_seconds)))
            except httpx.HTTPError as exc:
                print(f"⚠️ worker API error: {exc}")
                if args.once:
                    return 1
                time.sleep(args.poll_seconds)
    finally:
        client.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Local worker for ai-spider-app phone capture tasks")
    parser.add_argument("--base-url", default=os.getenv("WORKER_BASE_URL") or os.getenv("AI_SPIDER_BASE_URL") or "", help="Cloud app base URL, e.g. http://host")
    parser.add_argument("--token", default=os.getenv("WORKER_API_TOKEN") or "", help="Worker API token")
    parser.add_argument("--node-key", default=os.getenv("WORKER_NODE_KEY") or socket.gethostname(), help="Stable worker node key")
    parser.add_argument("--name", default=os.getenv("WORKER_NAME") or socket.gethostname(), help="Display name")
    parser.add_argument("--repo-root", default=os.getenv("WORKER_REPO_ROOT") or Path(__file__).resolve().parents[1], help="Project root")
    parser.add_argument("--poll-seconds", type=int, default=int(os.getenv("WORKER_POLL_SECONDS", "5")), help="Fallback poll interval")
    parser.add_argument("--capabilities", default=os.getenv("WORKER_CAPABILITIES", "uiautomator2,autoglm,scroll_promo,jd_new_floor_audit"), help="Comma-separated task modes")
    parser.add_argument("--once", action="store_true", help="Run a single poll/claim cycle")
    args = parser.parse_args()
    if not args.base_url:
        parser.error("--base-url or WORKER_BASE_URL is required")
    if not args.token:
        parser.error("--token or WORKER_API_TOKEN is required")
    return args


if __name__ == "__main__":
    sys.exit(main())
