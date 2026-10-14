"""Seed real H5 baselines and clearly labelled synthetic App inspections in a test/demo DB.

Run from the repository root with the backend dependencies installed:
  DATABASE_URL=... python scripts/seed_audit_projects_demo.py \
    --results /path/to/results.json \
    --records-file docs/examples/official-venue-pilot10-v3.json \
    --project-name '官方会场全周期演示'
"""

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import hashlib
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
        elif before in {"disabled", "not_applicable"}:
            after = "fail" if index == 0 else "not_applicable"
        else:
            after = "uncertain"
        checks.append({
            "rule_id": finding["rule_id"], "status": after,
            "observed": f"【模拟数据】{finding['rule_id']}：上线前 {before} → 上线后 {after}，非真实 App 检查。",
            "reason": "仅用于演示全周期比对，结论由真实 H5 状态确定性变换产生。",
            "bbox_norm": [50, 50, 950, 900] if after in {"pass", "fail"} else None,
        })
    return checks


def seed(db, results_path: Path, records_path: Path, project_name: str) -> dict:
    from app import models
    from app.services import audit_projects as service
    from app.services.inspection import Specification, build_inspection, skill_snapshot

    # One task is a durable marker. A committed seed is never duplicated on rerun.
    existing_task = db.query(models.Task).filter_by(name=DEMO_TASK_NAME).first()
    if existing_task is not None:
        record = db.query(models.AuditRecord).filter(
            models.AuditRecord.source_ref_json["task_run_id"].astext.in_(
                [str(run.id) for run in existing_task.runs]
            ),
        ).first()
        page = db.get(models.AuditPage, record.page_id) if record else None
        return {"skipped": True, "reason": "演示任务已存在", "project_id": str(page.project_id) if page else None}

    raw = results_path.read_bytes()
    data = json.loads(raw)
    selected_record_ids = set(json.loads(records_path.read_text(encoding="utf-8"))["record_ids"])
    if not selected_record_ids:
        raise ValueError("样本清单的 record_ids 不能为空")
    # The pilot file lists record_id; import_h5 takes venue_id, not record_id.
    selected = [result for result in data["results"] if result["venue"]["record_id"] in selected_record_ids]
    if {result["venue"]["record_id"] for result in selected} != selected_record_ids:
        raise ValueError("results.json 未包含样本清单中的全部 record_id")
    venue_ids = {str(result["venue"]["venue_id"]) for result in selected}
    if len(venue_ids) < 3:
        raise ValueError("演示至少需要三个不同会场")

    project = db.query(models.AuditProject).filter_by(name=project_name).order_by(models.AuditProject.created_at).first()
    if project is None:
        project = service.create_project(db, project_name, "真实 H5 上线前记录 + 模拟 App 上线后记录，仅用于演示。", None)
    imported = service.import_h5(db, project, data, results_path.name, hashlib.sha256(raw).hexdigest(), venue_ids=venue_ids, user_id=None)
    pre_records = db.query(models.AuditRecord).join(models.AuditPage).filter(
        models.AuditPage.project_id == project.id,
        models.AuditPage.business_key.in_(venue_ids),
        models.AuditRecord.source_kind == "h5_import",
        models.AuditRecord.source_ref_json["sha256"].astext == hashlib.sha256(raw).hexdigest(),
    ).all()
    # Prefer venues with multiple real failures so fixed and still_open both appear.
    pre_records.sort(key=lambda record: (-record.summary_json.get("fail", 0), str(record.source_ref_json["venue_id"])))
    chosen = pre_records[:3]
    if len(chosen) != 3:
        raise ValueError("无法找到三个已导入的上线前记录")

    rules = {finding["rule_id"]: finding for pre in chosen for finding in pre.findings_json}
    spec = Specification.model_validate({
        "title": DEMO_SKILL_NAME, "version": "5", "source": "seed_audit_projects_demo.py",
        "document": "模拟规范。沿用真实 H5 的 OV 规则 ID，仅用于演示，不代表真实 App 审核。",
        "rules": [{"id": rule_id, "clause": finding["title"] or rule_id, "expected": "符合对应官方会场规则（模拟）"}
                  for rule_id, finding in sorted(rules.items())],
    })
    skill = models.AnalysisSkill(name=DEMO_SKILL_NAME, prompt="仅供演示，不执行真实巡查。", skill_type="inspection",
                                 version=5, specification_json=spec.model_dump())
    task = models.Task(name=DEMO_TASK_NAME, status="completed", target_app="京东（模拟）", target_scenario="官方会场（模拟）")
    db.add_all([skill, task])
    db.flush()
    task.analysis_skill_ids = [skill.id]
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    totals = Counter(dict.fromkeys(service.COMPARE_CATEGORIES, 0))
    comparisons = []
    for index, pre in enumerate(chosen):
        completed = now + timedelta(seconds=index)
        # App aggregation spans a whole run. Separate runs prevent cross-venue findings from mixing.
        run = models.TaskRun(task_id=task.id, attempt_no=index + 1, status="completed", exit_code=0,
                             started_at=now, completed_at=completed, analysis_skills_snapshot_json=[skill_snapshot(skill)],
                             result_json={"synthetic": True, "venue_id": pre.source_ref_json["venue_id"]})
        db.add(run)
        db.flush()
        image = models.Image(file_path=f"demo-synthetic/{run.id}.png", task_id=task.id, task_run_id=run.id,
                             source_app="京东（模拟）", scenario="官方会场（模拟）", captured_at=completed)
        db.add(image)
        db.flush()
        # Match the T1 fixture's build_inspection contract, including evidence and clause fields.
        inspection = build_inspection({"checks": synthetic_checks(pre.findings_json)}, spec, image, [],
                                      skill_snapshot(skill), (390, 844))
        inspection["synthetic"] = True
        db.add(models.Analysis(image_id=image.id, skill_id=skill.id, status="done", embedding_status="skipped",
                               analyzed_at=completed, inspection_json=inspection))
        db.flush()
        page = db.get(models.AuditPage, pre.page_id)
        post = service.add_app_record(db, page, run.id, skill.id, baseline_record_id=pre.id if index < 2 else None)
        post.note = "模拟数据，仅演示生命周期；未执行真实 App 巡查。"
        # Explicit comparison also demonstrates the independent post without storing a baseline.
        comparison = service.record_comparison(db, post, pre.id)
        totals.update(comparison["counts"])
        comparisons.append({"venue_id": page.business_key, "baseline": index < 2, "counts": comparison["counts"]})
    task.completed_at = completed
    if not all(totals[category] for category in service.COMPARE_CATEGORIES):
        raise ValueError("这些样本的真实上线前状态不足以覆盖全部比对类别，请选择包含多条不符合项的会场")
    return {"project_id": str(project.id), "import": imported, "pre_records": len(pre_records), "post_records": 3,
            "with_baseline": 2, "without_baseline": 1, "compare_counts": dict(totals), "comparisons": comparisons}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    parser.add_argument("--records-file", type=Path, default=ROOT / "docs/examples/official-venue-pilot10-v3.json")
    parser.add_argument("--project-name", required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "backend"))
    from app.config import settings

    if not is_demo_database_url(settings.DATABASE_URL):
        print("拒绝运行：DATABASE_URL 的数据库名必须包含 test 或 demo。", file=sys.stderr)
        return 1
    if not args.project_name.strip():
        parser.error("--project-name 不能为空")
    for path in (args.results, args.records_file):
        if not path.is_file():
            parser.error(f"文件不存在：{path}")

    from sqlalchemy.exc import SQLAlchemyError
    from app.database import SessionLocal, init_db

    try:
        init_db()
        with SessionLocal.begin() as db:
            summary = seed(db, args.results, args.records_file, args.project_name.strip())
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print(f"演示未写入：{exc}", file=sys.stderr)
        return 1
    except SQLAlchemyError:
        print("演示未写入：数据库操作失败，请检查测试库连接与 vector 扩展。", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
