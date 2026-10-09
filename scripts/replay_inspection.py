"""Replay one versioned specification against existing captures; no DB or phone writes."""
import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from PIL import Image
from app.services.inspection import Specification, build_inspection, skill_snapshot
from app.services.llm_analyzer import LLMAnalyzer
from app.services.model_trace import capture_model_calls, model_purpose


async def replay(args):
    spec = Specification.model_validate_json(Path(args.spec).read_text(encoding="utf-8"))
    skill = SimpleNamespace(id=uuid4(), name=spec.title, version=1, skill_type="inspection",
                            prompt="根据规范逐项巡查", profile="default", is_system=False, status="active", output_schema_json={}, specification_json=spec.model_dump())
    snapshot = skill_snapshot(skill)
    analyzer = LLMAnalyzer()
    reports = []
    for scene, filename in args.capture:
        path = Path(filename).resolve()
        with Image.open(path) as image:
            size = image.size
        image = SimpleNamespace(id=uuid4(), source_app=args.app, scenario=scene, task_run_id=None, device_id=None)
        with capture_model_calls() as calls:
            context = {"target_app": args.app, "target_scenario": scene}
            with model_purpose("target_validation"):
                is_target, reason = await analyzer.is_target_page(str(path), context)
            if not is_target:
                reports.append({"scene": scene, "status": "skipped", "reason": reason, "model_calls": calls})
                continue
            with model_purpose("specification_inspection"):
                result, status = await analyzer.analyze_with_skill(str(path), skill, context)
            report = build_inspection(result, spec, image, calls, snapshot, size)
            report["replay"] = {"source_file": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
                                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "analysis_status": status,
                                "target_validation": {"is_target": is_target, "reason": reason}}
            # These are offline artifacts, not database image records.
            for check in report["checks"]:
                for evidence in check["evidence"]:
                    evidence.pop("image_id")
                    evidence["file_path"] = report["replay"]["source_file"]
            reports.append(report)
        print(f"{scene}: {report['summary']}")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"validation_mode": "historical_capture_replay", "reports": reports}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", required=True)
    parser.add_argument("--app", default="京东")
    parser.add_argument("--capture", nargs=2, action="append", metavar=("SCENE", "IMAGE"), required=True)
    parser.add_argument("--output", required=True)
    asyncio.run(replay(parser.parse_args()))
