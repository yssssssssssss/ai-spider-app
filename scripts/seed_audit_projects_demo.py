"""Seed real H5 baselines and clearly labelled synthetic App inspections in a test/demo DB.

Run from the repository root with the backend dependencies installed:
  DATABASE_URL=... python scripts/seed_audit_projects_demo.py \
    --results /path/to/results.json \
    --records-file docs/examples/official-venue-pilot10-v3.json \
    --project-name '官方会场全周期演示'
"""

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
DEMO_TASK_NAME = "演示：上线后 App 巡查（模拟数据）"
DEMO_SKILL_NAME = "演示：官方会场 v5（模拟）"


def is_demo_database_url(database_url: str) -> bool:
    """Check the database name only, never credentials, host or query parameters."""
    try:
        url = urlsplit(database_url)
        name = unquote(url.path.lstrip("/")).lower()
        return url.scheme in {"postgresql", "postgresql+psycopg2", "postgres"} and bool(url.hostname) and (
            "test" in name or "demo" in name
        )
    except ValueError:
        return False


def synthetic_checks(findings: list[dict]) -> list[dict]:
    """Stable transitions based on real pre statuses, without altering the H5 findings."""
    seen = Counter()
    checks = []
    for finding in sorted(findings, key=lambda item: item["rule_id"]):
        before = finding["status"]
        index = seen[before]
        seen[before] += 1
        if before == "fail":
            after = "pass" if index % 2 == 0 else "fail"
        elif before == "pass":
            after = ("fail", "pass", "uncertain")[index] if index < 3 else "pass"
        elif before == "not_applicable":
            after = "fail" if index == 0 else "not_applicable"
        elif before == "disabled":
            after = "not_applicable"
        else:
            after = "uncertain"
        checks.append({
            "rule_id": finding["rule_id"], "status": after,
            "observed": f"【模拟数据】{finding['rule_id']}：上线前 {before} → 上线后 {after}，非真实 App 检查。",
            "reason": "仅用于演示全周期比对，结论由真实 H5 状态确定性变换产生。",
            "bbox_norm": [50, 50, 950, 900] if after in {"pass", "fail"} else None,
        })
    return checks


def import_demo_specs(db):
    from app import models
    from app.services import audit_workspace as service

    spec = db.query(models.AuditSpec).filter_by(key="official-venue-review").first()
    if spec is None:
        spec = models.AuditSpec(key="official-venue-review", name="官方会场 H5 规范")
        db.add(spec)
    versions = [service.import_spec_version(
        db, spec, (ROOT / f"docs/specifications/official-venue-review/h5-v{v}.json").read_bytes(), "h5", None,
    ) for v in range(2, 6)]
    return versions


def seed(db, results_path: Path, records_path: Path, project_name: str) -> dict:
    from app import models
    from app.services import audit_workspace as service
    from app.services.inspection import Specification, build_inspection, skill_snapshot

    versions = import_demo_specs(db)
    existing_task = db.query(models.Task).filter_by(name=DEMO_TASK_NAME).first()
    if existing_task is not None:
        return {"skipped": True, "reason": "演示任务已存在"}

    # Fixed pilot record IDs use pNN-rNN-<venue_id>; do not decode the 30MB file twice.
    selected_record_ids = json.loads(records_path.read_text(encoding="utf-8"))["record_ids"]
    venue_ids = {record_id.split("-", 2)[2] for record_id in selected_record_ids}
    if len(venue_ids) != 10:
        raise ValueError("演示清单必须包含10个不同会场")
    project = models.AuditProject(name=project_name, description="真实 H5 上线前审核 + 模拟 App 上线后审核，仅用于演示。")
    db.add(project)
    pre_run = service.create_h5_run(db, results_path.read_bytes(), results_path.name, versions[-1],
                                    "官方会场10个试点：真实 H5 上线前审核", venue_ids=venue_ids, project=project)
    if len(pre_run.targets) != 10:
        raise ValueError("results.json 未包含全部10个试点会场")

    h5_rules = versions[-1].rules_json
    specification = Specification.model_validate({
        "title": DEMO_SKILL_NAME, "version": "演示-App-v5", "source": "seed_audit_projects_demo.py",
        "document": "模拟规范。沿用 H5 v5 的 OV 规则 ID，仅用于演示，不代表真实 App 审核。",
        "rules": [{"id": r["rule_id"], "clause": r["title"] or r["rule_id"],
                   "expected": "符合对应官方会场规则（模拟）"} for r in h5_rules],
    })
    demo_spec = models.AuditSpec(key="demo-official-venue-app", name=DEMO_SKILL_NAME,
                                description="演示规范，仅供模拟数据使用")
    db.add(demo_spec)
    # Preserve enabled/duplicate metadata while explicitly applying these demo rules to App.
    demo_source = specification.model_dump()
    for item, h5_rule in zip(demo_source["rules"], h5_rules):
        item.update(enabled=h5_rule["enabled"], duplicate_of=h5_rule["duplicate_of"], carriers=["app"])
    app_version = service.import_spec_version(db, demo_spec, json.dumps(demo_source, ensure_ascii=False).encode(), "app", None)
    skill = models.AnalysisSkill(name=DEMO_SKILL_NAME, prompt="仅供演示，不执行真实巡查。", skill_type="inspection",
                                 version=5, specification_json=specification.model_dump())
    task = models.Task(name=DEMO_TASK_NAME, status="completed", target_app="京东（模拟）", target_scenario="官方会场（模拟）")
    db.add_all([skill, task])
    db.flush()
    task.analysis_skill_ids = [skill.id]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    totals = Counter(dict.fromkeys(service.COMPARE_CATEGORIES, 0))
    ordered = sorted(pre_run.targets, key=lambda t: (-t.summary_json["fail"], t.business_key))
    # One still-problematic venue gets a second pre; other untouched venues retain
    # review and baseline stages. All fabricated records carry the demo marker.
    recheck_source = ordered[2]
    recheck = models.AuditRun(
        name=f"演示：{recheck_source.name} 上线前复查（模拟）", carrier="h5", phase="pre",
        spec_version=versions[-1], project=project, created_at=now,
        source_kind="h5_import", source_ref_json={"demo": True},
    )
    findings = deepcopy(recheck_source.findings_json)
    for finding in findings:
        finding["observed"] = "【模拟复查】" + finding["observed"]
    recheck.targets = [models.AuditTarget(
        business_key=recheck_source.business_key, name=recheck_source.name,
        outcome=recheck_source.outcome, findings_json=findings, summary_json=recheck_source.summary_json,
    )]
    recheck.summary_json = service._run_summary(recheck.targets)
    db.add(recheck)
    db.flush()
    # Two automatically linked posts (one closed), plus an explicitly unmapped
    # business key illustrating an independent check.
    post_sources = [ordered[0], ordered[1], ordered[3]]
    for index, pre in enumerate(post_sources):
        completed = now + timedelta(seconds=index + 1)
        source = models.TaskRun(task_id=task.id, attempt_no=index + 1, status="completed", exit_code=0,
                                started_at=now, completed_at=completed,
                                analysis_skills_snapshot_json=[skill_snapshot(skill)],
                                result_json={"demo": True, "venue_id": pre.business_key})
        db.add(source)
        db.flush()
        image = models.Image(file_path=f"demo-synthetic/{source.id}.png", task_id=task.id, task_run_id=source.id,
                             source_app="京东（模拟）", scenario="官方会场（模拟）", captured_at=completed)
        db.add(image)
        db.flush()
        checks = synthetic_checks(pre.findings_json)
        if index == 0:
            for check in checks:
                if check["status"] in {"fail", "uncertain"}:
                    check["status"] = "pass"
                    check["observed"] = "【模拟数据】全部问题已修复，验收闭环。"
                    check["bbox_norm"] = [50, 50, 950, 900]
        inspection = build_inspection({"checks": checks}, specification, image, [],
                                      skill_snapshot(skill), (390, 844))
        inspection["synthetic"] = True
        db.add(models.Analysis(image_id=image.id, skill_id=skill.id, status="done", embedding_status="skipped",
                               analyzed_at=completed, inspection_json=inspection))
        db.flush()
        business_key = pre.business_key if index < 2 else f"demo-independent:{pre.business_key}"
        post_run = service.create_app_run(db, source.id, skill.id, app_version,
                                          f"演示：{pre.name} App 上线后审核（模拟）", pre.name,
                                          business_key, project=project)
        post_run.created_at = completed
        post_run.source_ref_json = {**post_run.source_ref_json, "demo": True}
        if post_run.targets[0].baseline_target_id:
            totals.update(service.compare_targets(pre, post_run.targets[0])["counts"])
    task.completed_at = completed
    db.flush()
    from app.services.audit_analytics import project_cockpit
    cockpit = project_cockpit(service.load_project_runs(db, project.id))
    stages = {key: value["count"] for key, value in cockpit["stages"].items()}
    if not all(stages.values()):
        raise ValueError("演示项目必须覆盖全部五种阶段")
    return {"project_id": str(project.id), "spec_versions": len(versions) + 1,
            "pre_runs": 2, "pre_targets": 11, "post_runs": 3, "post_targets": 3,
            "with_baseline": 2, "compare_counts": dict(totals), "stages": stages}



def import_full_run(db, results_path: Path) -> dict:
    from app.services import audit_workspace as service

    versions = import_demo_specs(db)
    run = service.create_h5_run(db, results_path.read_bytes(), results_path.name, versions[-1],
                                "全部会场：独立 H5 审核")
    return {"run_id": str(run.id), "project_id": None, **run.summary_json}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, help="10个试点的真实结果来源；默认使用 --full-run 文件")
    parser.add_argument("--full-run", type=Path, help="另收录全部会场为不归属项目的独立 H5 审核")
    parser.add_argument("--records-file", type=Path, default=ROOT / "docs/examples/official-venue-pilot10-v3.json")
    parser.add_argument("--project-name", default="官方会场全周期演示")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "backend"))
    from app.config import settings

    if not is_demo_database_url(settings.DATABASE_URL):
        print("拒绝运行：DATABASE_URL 的数据库名必须包含 test 或 demo。", file=sys.stderr)
        return 1
    if not args.project_name.strip():
        parser.error("--project-name 不能为空")
    results_path = args.results or args.full_run
    if results_path is None:
        parser.error("需要 --results 或 --full-run")
    for path in (results_path, args.records_file, args.full_run):
        if path is not None and not path.is_file():
            parser.error(f"文件不存在：{path}")

    from sqlalchemy.exc import SQLAlchemyError
    from app.database import SessionLocal, init_db

    try:
        init_db()
        with SessionLocal.begin() as db:
            summary = seed(db, results_path, args.records_file, args.project_name.strip())
            if args.full_run is not None:
                summary["full_run"] = import_full_run(db, args.full_run)
    except (ValueError, KeyError, TypeError, IndexError, OSError) as exc:
        print(f"演示未写入：{exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("演示未写入：数据库操作失败，请检查测试库连接与 vector 扩展。", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
