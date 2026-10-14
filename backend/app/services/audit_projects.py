"""Normalize and compare audit results; callers own database transactions."""

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from typing import Iterable, Literal, TypedDict
from uuid import UUID

from sqlalchemy import JSON, func
from sqlalchemy.orm import Session

from app import models


class Evidence(TypedDict):
    kind: Literal["h5_report", "app_images"]
    image_ids: list[str]


class Finding(TypedDict):
    rule_id: str
    title: str
    status: Literal["pass", "fail", "uncertain", "not_applicable", "disabled"]
    observed: str
    reason: str
    evidence: Evidence


@dataclass
class ParsedVenue:
    venue_id: str
    venue_name: str
    project_id: str
    spec_key: str
    spec_version: str
    findings: list[Finding]
    summary: dict[str, int]


FINDING_STATUSES = ("pass", "fail", "uncertain", "not_applicable", "disabled")
COMPARE_CATEGORIES = ("fixed", "still_open", "regressed", "new_issue", "kept", "needs_confirmation", "not_comparable")


def _summary(findings: list[Finding]) -> dict[str, int]:
    counts = Counter(finding["status"] for finding in findings)
    return {status: counts[status] for status in FINDING_STATUSES}


def parse_h5_results(data: dict, record_ids: set[str] | None = None) -> list[ParsedVenue]:
    parsed = []
    for result in data["results"]:
        venue = result["venue"]
        venue_id = str(venue["venue_id"])
        if record_ids is not None and venue_id not in record_ids:
            continue
        findings = []
        for check in (result.get("audit") or {}).get("checks", []):
            if check["status"] not in FINDING_STATUSES:
                raise ValueError(f"Unknown H5 finding status: {check['status']}")
            findings.append({
                "rule_id": check["rule_id"], "title": check.get("title", ""), "status": check["status"],
                "observed": check.get("observed", ""), "reason": check.get("reason", ""),
                "evidence": {"kind": "h5_report", "image_ids": []},
            })
        parsed.append(ParsedVenue(
            venue_id=venue_id, venue_name=venue["venue_name"], project_id=str(venue["project_id"]),
            spec_key=data["title"], spec_version=str(data["rule_version"]),
            findings=findings, summary=_summary(findings),
        ))
    return parsed


def aggregate_app_findings(analyses: Iterable[models.Analysis]) -> list[Finding]:
    precedence = {"fail": 0, "pass": 1, "uncertain": 2, "not_applicable": 3}
    by_rule = {}
    for analysis in analyses:
        for check in (analysis.inspection_json or {}).get("checks", []):
            if check["status"] not in precedence:
                raise ValueError(f"Unknown App finding status: {check['status']}")
            by_rule.setdefault(check["rule_id"], []).append((str(analysis.image_id), check))
    findings = []
    for rule_id, checks in by_rule.items():
        status = min((check["status"] for _, check in checks), key=precedence.__getitem__)
        contributors = [(image_id, check) for image_id, check in checks if check["status"] == status]
        findings.append({
            "rule_id": rule_id, "title": contributors[0][1]["clause"], "status": status,
            "observed": "\n".join(dict.fromkeys(check["observed"] for _, check in contributors if check["observed"])),
            "reason": "\n".join(dict.fromkeys(check["reason"] for _, check in contributors if check["reason"])),
            "evidence": {"kind": "app_images", "image_ids": list(dict.fromkeys(image_id for image_id, _ in contributors))},
        })
    return findings


def compare(pre_findings: list[Finding], post_findings: list[Finding], *,
            pre_spec: tuple[str, str], post_spec: tuple[str, str]) -> dict:
    """Explicit table transitions win, then uncertain, then not_comparable.

    Missing pre -> fail is new_issue; one-sided uncertain needs confirmation.
    Unlisted transitions are not_comparable. Specs are (key, version) pairs.
    """
    pre_by_id = {finding["rule_id"]: finding for finding in pre_findings}
    post_by_id = {finding["rule_id"]: finding for finding in post_findings}
    transitions = {("fail", "pass"): "fixed", ("fail", "fail"): "still_open",
                   ("pass", "fail"): "regressed", ("pass", "pass"): "kept"}
    counts = dict.fromkeys(COMPARE_CATEGORIES, 0)
    rules = []
    for rule_id in pre_by_id | post_by_id:
        pre, post = pre_by_id.get(rule_id), post_by_id.get(rule_id)
        pre_status = pre["status"] if pre else None
        post_status = post["status"] if post else None
        category = transitions.get((pre_status, post_status))
        if category is None:
            if pre_status in {None, "not_applicable", "disabled"} and post_status == "fail":
                category = "new_issue"
            elif "uncertain" in (pre_status, post_status):
                category = "needs_confirmation"
            else:
                category = "not_comparable"
        counts[category] += 1
        rules.append({
            "rule_id": rule_id, "title": (post or pre)["title"], "category": category,
            "pre_status": pre_status, "pre_observed": pre["observed"] if pre else None,
            "post_status": post_status, "post_observed": post["observed"] if post else None,
        })
    return {"rules": rules, "counts": counts, "spec_mismatch": pre_spec != post_spec}


def import_h5(db: Session, project: models.AuditProject, data: dict, file_name: str, sha256: str,
              record_ids: set[str] | None, user_id: UUID | None) -> dict:
    venues = parse_h5_results(data, record_ids)
    db.flush()
    pages = {page.business_key: page for page in db.query(models.AuditPage).filter(
        models.AuditPage.project_id == project.id,
    ).all() if page.business_key is not None}
    imported = {ref["venue_id"] for (ref,) in db.query(models.AuditRecord.source_ref_json).join(models.AuditPage).filter(
        models.AuditPage.project_id == project.id,
        models.AuditRecord.source_kind == "h5_import",
        models.AuditRecord.source_ref_json["sha256"].astext == sha256,
    ).all()}
    counts = {"created": 0, "skipped": 0, "pages_created": 0}
    for venue in venues:
        if venue.venue_id in imported:
            counts["skipped"] += 1
            continue
        page = pages.get(venue.venue_id)
        if page is None:
            page = models.AuditPage(project_id=project.id, name=venue.venue_name, business_key=venue.venue_id)
            db.add(page)
            pages[venue.venue_id] = page
            counts["pages_created"] += 1
        db.add(models.AuditRecord(
            page=page, phase="pre", carrier="h5", source_kind="h5_import",
            source_ref_json={"file_name": file_name, "sha256": sha256, "generated_at": data.get("generated_at"),
                             "venue_id": venue.venue_id, "project_id": venue.project_id},
            spec_key=venue.spec_key, spec_version=venue.spec_version, findings_json=venue.findings,
            summary_json=venue.summary, created_by=user_id,
        ))
        imported.add(venue.venue_id)
        counts["created"] += 1
    db.flush()
    return counts


def set_baseline(db: Session, record: models.AuditRecord, baseline_id: UUID | None) -> models.AuditRecord:
    baseline = None
    if baseline_id is not None:
        if record.phase != "post":
            raise ValueError("Only post records can have a baseline")
        baseline = db.get(models.AuditRecord, baseline_id)
        if baseline is None:
            raise ValueError("Baseline record not found")
        if baseline.page_id != record.page_id:
            raise ValueError("Baseline must belong to the same page")
        if baseline.phase != "pre":
            raise ValueError("Baseline must be a pre record")
    record.baseline_record = baseline
    record.baseline_record_id = baseline_id
    return record


def add_app_record(db: Session, page: models.AuditPage, task_run_id: UUID, skill_id: UUID,
                   phase: str = "post", baseline_record_id: UUID | None = None,
                   user_id: UUID | None = None) -> models.AuditRecord:
    if phase not in {"pre", "post"}:
        raise ValueError("Phase must be pre or post")
    if db.get(models.TaskRun, task_run_id) is None:
        raise ValueError("Task run not found")
    skill = db.get(models.AnalysisSkill, skill_id)
    if skill is None:
        raise ValueError("Skill not found")
    analyses = db.query(models.Analysis).join(models.Image).filter(
        models.Image.task_run_id == task_run_id, models.Analysis.skill_id == skill_id,
        models.Analysis.inspection_json.isnot(None),
    ).order_by(models.Image.created_at, models.Image.id).all()
    findings = aggregate_app_findings(analyses)
    if not findings:
        raise ValueError("Task run has no inspection results for the selected Skill")
    record = models.AuditRecord(
        page_id=page.id, phase=phase, carrier="app", source_kind="app_task_run",
        source_ref_json={"task_run_id": str(task_run_id), "skill_id": str(skill_id)},
        spec_key=skill.name, spec_version=str(skill.version), findings_json=findings,
        summary_json=_summary(findings), created_by=user_id,
    )
    set_baseline(db, record, baseline_record_id)
    db.add(record)
    db.flush()
    return record


def import_h5_upload(db: Session, project: models.AuditProject, raw: bytes, file_name: str,
                     record_ids: str | None, user_id: UUID) -> dict:
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("File must contain valid JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ValueError("H5 JSON must contain a results list")
    selected = None
    if record_ids is not None:
        selected = {value.strip() for value in record_ids.split(",") if value.strip()} or None
    try:
        return import_h5(db, project, data, file_name, hashlib.sha256(raw).hexdigest(), selected, user_id)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid H5 results structure") from exc


def _required_name(name: str | None) -> str:
    if name is None or not name.strip():
        raise ValueError("Name is required")
    return name.strip()


def create_project(db: Session, name: str, description: str | None, user_id: UUID) -> models.AuditProject:
    project = models.AuditProject(name=_required_name(name), description=description, created_by=user_id)
    db.add(project)
    db.flush()
    return project


def update_project(project: models.AuditProject, changes: dict) -> models.AuditProject:
    if "name" in changes:
        project.name = _required_name(changes["name"])
    if "description" in changes:
        project.description = changes["description"]
    return project


def create_page(db: Session, project: models.AuditProject, name: str,
                business_key: str | None) -> models.AuditPage:
    name = _required_name(name)
    if business_key is not None:
        business_key = business_key.strip() or None
    if business_key is not None and db.query(models.AuditPage.id).filter_by(
        project_id=project.id, business_key=business_key,
    ).first():
        raise ValueError("Page business_key already exists in this project")
    page = models.AuditPage(project_id=project.id, name=name, business_key=business_key)
    db.add(page)
    db.flush()
    return page


def get_project_record(db: Session, project_id: UUID, record_id: UUID) -> models.AuditRecord:
    record = db.query(models.AuditRecord).join(models.AuditPage).filter(
        models.AuditRecord.id == record_id, models.AuditPage.project_id == project_id,
    ).first()
    if record is None:
        raise LookupError("Audit record not found")
    return record


def update_record(db: Session, record: models.AuditRecord, changes: dict) -> models.AuditRecord:
    if "baseline_record_id" in changes:
        baseline_id = changes["baseline_record_id"]
        if baseline_id is not None:
            page = db.get(models.AuditPage, record.page_id)
            get_project_record(db, page.project_id, baseline_id)
        set_baseline(db, record, baseline_id)
    if "note" in changes:
        record.note = changes["note"]
    return record


def compare_records(pre: models.AuditRecord, post: models.AuditRecord) -> dict:
    if post.phase != "post":
        raise ValueError("Comparison requires a post record")
    if pre.page_id != post.page_id:
        raise ValueError("Baseline must belong to the same page")
    if pre.phase != "pre":
        raise ValueError("Baseline must be a pre record")
    return compare(pre.findings_json, post.findings_json,
                   pre_spec=(pre.spec_key, pre.spec_version), post_spec=(post.spec_key, post.spec_version))


def record_comparison(db: Session, post: models.AuditRecord, pre_id: UUID | None = None) -> dict:
    pre_id = pre_id if pre_id is not None else post.baseline_record_id
    if pre_id is None:
        raise ValueError("A pre record or baseline is required")
    page = db.get(models.AuditPage, post.page_id)
    return compare_records(get_project_record(db, page.project_id, pre_id), post)


def _project_fields(project: models.AuditProject) -> dict:
    return {"id": project.id, "name": project.name, "description": project.description,
            "created_by": project.created_by, "created_at": project.created_at, "updated_at": project.updated_at}


def _page_fields(page: models.AuditPage) -> dict:
    return {"id": page.id, "project_id": page.project_id, "name": page.name,
            "business_key": page.business_key, "created_at": page.created_at}


def list_projects(db: Session) -> list[dict]:
    pages = db.query(models.AuditPage.project_id, func.count().label("page_count")).group_by(
        models.AuditPage.project_id,
    ).subquery()
    records = db.query(
        models.AuditPage.project_id,
        func.count().filter(models.AuditRecord.phase == "pre").label("pre"),
        func.count().filter(models.AuditRecord.phase == "post").label("post"),
        func.count().filter(models.AuditRecord.carrier == "h5").label("h5"),
        func.count().filter(models.AuditRecord.carrier == "app").label("app"),
    ).join(models.AuditRecord).group_by(models.AuditPage.project_id).subquery()
    rows = db.query(models.AuditProject, pages.c.page_count, records.c.pre, records.c.post,
                    records.c.h5, records.c.app).outerjoin(
        pages, pages.c.project_id == models.AuditProject.id,
    ).outerjoin(records, records.c.project_id == models.AuditProject.id).order_by(
        models.AuditProject.created_at.desc(), models.AuditProject.id.desc(),
    ).all()
    return [{**_project_fields(project), "page_count": page_count or 0,
             "record_counts": {"pre": pre or 0, "post": post or 0, "h5": h5 or 0, "app": app or 0}}
            for project, page_count, pre, post, h5, app in rows]


def _latest_records(records: list[models.AuditRecord]) -> tuple:
    # Callers provide records in chronological order. Baselines use this same batch.
    latest = {record.phase: record for record in records}
    pre, post = latest.get("pre"), latest.get("post")
    comparison = None
    if post is not None and post.baseline_record_id is not None:
        by_id = {record.id: record for record in records}
        comparison = compare_records(by_id[post.baseline_record_id], post)
    return pre, post, comparison


def project_detail(db: Session, project: models.AuditProject) -> dict:
    pages = db.query(models.AuditPage).filter_by(project_id=project.id).order_by(
        models.AuditPage.created_at, models.AuditPage.id,
    ).all()
    records = db.query(models.AuditRecord).join(models.AuditPage).filter(
        models.AuditPage.project_id == project.id,
    ).order_by(models.AuditRecord.created_at, models.AuditRecord.id).all()
    by_page = {page.id: [] for page in pages}
    for record in records:
        by_page[record.page_id].append(record)
    matrix = []
    for page in pages:
        pre, post, comparison = _latest_records(by_page[page.id])
        matrix.append({**_page_fields(page), "latest_pre": pre, "latest_post": post,
                       "has_baseline": post is not None and post.baseline_record_id is not None,
                       "compare_counts": {category: comparison["counts"][category] for category in
                                          ("fixed", "still_open", "regressed", "new_issue")} if comparison else None})
    return {**_project_fields(project), "pages": matrix}


def page_detail(db: Session, page: models.AuditPage) -> dict:
    records = db.query(models.AuditRecord).filter_by(page_id=page.id).order_by(
        models.AuditRecord.created_at, models.AuditRecord.id,
    ).all()
    return {**_page_fields(page), "records": records, "comparison": _latest_records(records)[2]}


def app_candidates(db: Session) -> list[dict]:
    eligible = db.query(models.Analysis.id).join(models.Image).join(models.AnalysisSkill).filter(
        models.Image.task_run_id == models.TaskRun.id, models.Analysis.inspection_json.isnot(None),
        models.Analysis.inspection_json != JSON.NULL,
    ).exists()
    runs = db.query(models.TaskRun, models.Task.name).join(models.Task).filter(
        models.TaskRun.status == "completed", eligible,
    ).order_by(models.TaskRun.completed_at.desc().nullslast(), models.TaskRun.created_at.desc(),
               models.TaskRun.id.desc()).limit(50).all()
    if not runs:
        return []
    skills = db.query(models.Image.task_run_id, models.AnalysisSkill).select_from(models.AnalysisSkill).join(
        models.Analysis, models.Analysis.skill_id == models.AnalysisSkill.id,
    ).join(models.Image, models.Image.id == models.Analysis.image_id).filter(
        models.Image.task_run_id.in_([run.id for run, _ in runs]),
        models.Analysis.inspection_json.isnot(None),
        models.Analysis.inspection_json != JSON.NULL,
    ).distinct().order_by(models.AnalysisSkill.name, models.AnalysisSkill.id).all()
    by_run = {run.id: [] for run, _ in runs}
    for run_id, skill in skills:
        by_run[run_id].append(skill)
    return [{"task_run_id": run.id, "task_name": name, "completed_at": run.completed_at, "skills": by_run[run.id]}
            for run, name in runs]
