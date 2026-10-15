"""Audit workspace imports and comparisons. Callers own transaction boundaries.

Published spec versions are immutable through the ORM. Source JSON is retained
verbatim; summaries exclude duplicate rules only from fail/uncertain counts.
"""

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from typing import Iterable, Literal, TypedDict
from uuid import UUID

from sqlalchemy import event, func
from sqlalchemy.orm import Session, object_session

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


FINDING_STATUSES = ("pass", "fail", "uncertain", "not_applicable", "disabled")
COMPARE_CATEGORIES = ("fixed", "still_open", "regressed", "new_issue", "kept", "needs_confirmation", "not_comparable")


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


OUTCOMES = ("issues", "needs_confirmation", "partial", "clean", "capture_failed")
CAPTURE_REASONS = ("offline", "expired", "login_required", "other")
CARRIER_SCOPES = {"h5": ["h5"], "app": ["app"], "both": ["h5", "app"]}


@event.listens_for(models.AuditSpecVersion, "before_update")
def _immutable_spec_version(mapper, connection, version):
    if object_session(version).is_modified(version, include_collections=False):
        raise ValueError("Published spec versions are immutable; import a new version")


def _json_object(raw_bytes: bytes) -> dict:
    try:
        data = json.loads(raw_bytes)
    except (ValueError, UnicodeError) as exc:
        raise ValueError("File must contain valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("JSON must contain an object")
    return data


def import_spec_version(db: Session, spec: models.AuditSpec, raw_bytes: bytes,
                        carrier_scope: str, user_id: UUID | None = None) -> models.AuditSpecVersion:
    if carrier_scope not in CARRIER_SCOPES:
        raise ValueError("Carrier scope must be h5, app or both")
    db.flush()
    # Serialize version allocation per spec, including concurrent identical imports.
    db.query(models.AuditSpec).filter_by(id=spec.id).with_for_update().one()
    digest = hashlib.sha256(raw_bytes).hexdigest()
    existing = db.query(models.AuditSpecVersion).filter_by(spec_id=spec.id, sha256=digest).first()
    if existing is not None:
        return existing
    data = _json_object(raw_bytes)
    rules = []
    try:
        for rule in data["rules"]:
            rule_id = rule["id"]
            if not isinstance(rule_id, str) or not rule_id.strip():
                raise ValueError("Rule id is required")
            sources = rule.get("sources") or []
            strength = rule.get("strength", "mandatory")
            strength = {"conditional_mandatory": "conditional", "recommendation": "recommended"}.get(strength, strength)
            if strength not in {"mandatory", "conditional", "recommended"}:
                raise ValueError(f"Unknown rule strength: {strength}")
            carriers = rule.get("carriers", CARRIER_SCOPES[carrier_scope])
            if not isinstance(carriers, list) or any(c not in {"h5", "app"} for c in carriers):
                raise ValueError("Rule carriers must be a list of h5/app")
            enabled = rule.get("enabled", True)
            if not isinstance(enabled, bool):
                raise ValueError("Rule enabled must be a boolean")
            rules.append({
                "rule_id": rule_id, "title": rule.get("title", rule.get("clause", "")),
                "clause": sources[0].get("clause", "") if sources else rule.get("clause", ""),
                "expected": rule["expected"], "strength": strength, "enabled": enabled,
                "carriers": carriers, "method": rule.get("verification_method"),
                "duplicate_of": rule.get("duplicate_of"),
            })
        if not rules or len({rule["rule_id"] for rule in rules}) != len(rules):
            raise ValueError("Specification must contain unique, nonempty rules")
        label = str(data.get("version", data.get("rule_version", "")))
        if not label:
            raise ValueError("Specification version label is required")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid specification rules structure") from exc
    latest = db.query(func.max(models.AuditSpecVersion.version)).filter_by(spec_id=spec.id).scalar() or 0
    version = models.AuditSpecVersion(
        spec_id=spec.id, version=latest + 1, label=label, carrier_scope=carrier_scope,
        rules_json=rules, source_json=data, sha256=digest, created_by=user_id,
    )
    db.add(version)
    db.flush()
    return version


def _summary(findings: list[Finding], rules: list[dict]) -> dict:
    duplicates = {rule["rule_id"] for rule in rules if rule.get("duplicate_of")}
    counts = Counter(f["status"] for f in findings
                     if f["rule_id"] not in duplicates or f["status"] not in {"fail", "uncertain"})
    return {status: counts[status] for status in FINDING_STATUSES}


def _outcome(summary: dict) -> str:
    if summary["fail"]:
        return "issues"
    if summary["uncertain"]:
        return "needs_confirmation"
    return "clean"


def _capture_failure(audit: dict) -> tuple[str, dict]:
    detail = {"page_warnings": audit.get("page_warnings"), "page_state": audit.get("page_state")}
    text = json.dumps(detail, ensure_ascii=False).lower()
    if "迷路" in text:
        reason = "offline"
    elif "过期" in text or "已结束" in text:
        reason = "expired"
    elif "login" in text:
        reason = "login_required"
    else:
        reason = "other"
    return reason, detail


@dataclass
class ParsedVenue:
    venue_id: str
    venue_name: str
    findings: list[Finding]
    summary: dict
    outcome: str
    capture_reason: str | None


def parse_h5_results(data: dict, venue_ids: set[str] | None = None,
                     rules: list[dict] | None = None) -> list[ParsedVenue]:
    if not isinstance(data.get("results"), list):
        raise ValueError("H5 JSON must contain a results list")
    parsed = []
    status_map = {"page_error": "capture_failed", "visible_issues": "issues",
                  "needs_confirmation": "needs_confirmation", "partial_inspection": "partial"}
    try:
        for result in data["results"]:
            venue = result["venue"]
            venue_id = str(venue["venue_id"])
            if venue_ids is not None and venue_id not in venue_ids:
                continue
            audit = result.get("audit") or {}
            findings = []
            for check in audit.get("checks", []):
                if check["status"] not in FINDING_STATUSES:
                    raise ValueError(f"Unknown H5 finding status: {check['status']}")
                findings.append({
                    "rule_id": check["rule_id"], "title": check.get("title", ""), "status": check["status"],
                    "observed": check.get("observed", ""), "reason": check.get("reason", ""),
                    "evidence": {"kind": "h5_report", "image_ids": []},
                })
            summary = _summary(findings, rules if rules is not None else audit.get("checks", []))
            outcome = status_map.get(result.get("status")) or _outcome(summary)
            capture_reason = None
            if outcome == "capture_failed":
                capture_reason, summary["capture_detail"] = _capture_failure(audit)
            parsed.append(ParsedVenue(venue_id, venue["venue_name"], findings, summary, outcome, capture_reason))
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Invalid H5 results structure") from exc
    return parsed


def _run_summary(targets: Iterable[models.AuditTarget]) -> dict:
    outcomes, reasons = Counter(), Counter()
    for target in targets:
        outcomes[target.outcome] += 1
        if target.capture_reason is not None:
            reasons[target.capture_reason] += 1
    return {"targets": sum(outcomes.values()), "outcomes": {key: outcomes[key] for key in OUTCOMES},
            "capture_reasons": {key: reasons[key] for key in CAPTURE_REASONS}}


def _validate_run(spec_version: models.AuditSpecVersion, carrier: str, name: str, phase: str) -> str:
    if carrier not in CARRIER_SCOPES.get(spec_version.carrier_scope, []):
        raise ValueError(f"Spec version carrier scope must include {carrier}")
    if phase not in {"pre", "post"}:
        raise ValueError("Phase must be pre or post")
    if not name or not name.strip():
        raise ValueError("Name is required")
    return name.strip()


def create_h5_run(db: Session, raw_bytes: bytes, file_name: str, spec_version: models.AuditSpecVersion,
                  name: str, phase: str = "pre", venue_ids: set[str] | None = None,
                  project: models.AuditProject | None = None, user_id: UUID | None = None) -> models.AuditRun:
    name = _validate_run(spec_version, "h5", name, phase)
    data = _json_object(raw_bytes)  # The full results file is decoded exactly once.
    venues = parse_h5_results(data, venue_ids, spec_version.rules_json)
    run = models.AuditRun(
        name=name, carrier="h5", phase=phase, spec_version=spec_version, source_kind="h5_import",
        source_ref_json={"file_name": file_name, "sha256": hashlib.sha256(raw_bytes).hexdigest(),
                         "generated_at": data.get("generated_at"), "rule_version": data.get("rule_version")},
        created_by=user_id,
    )
    run.targets = [models.AuditTarget(
        business_key=v.venue_id, name=v.venue_name, outcome=v.outcome, capture_reason=v.capture_reason,
        findings_json=v.findings, summary_json=v.summary,
    ) for v in venues]
    run.summary_json = _run_summary(run.targets)
    db.add(run)
    db.flush()
    if project is not None:
        assign_run(db, run, project)
    return run


def create_app_run(db: Session, task_run_id: UUID, skill_id: UUID, spec_version: models.AuditSpecVersion,
                   name: str, target_name: str, business_key: str | None = None, phase: str = "post",
                   project: models.AuditProject | None = None, user_id: UUID | None = None) -> models.AuditRun:
    name = _validate_run(spec_version, "app", name, phase)
    if not target_name or not target_name.strip():
        raise ValueError("Target name is required")
    task_run = db.get(models.TaskRun, task_run_id)
    if task_run is None:
        raise ValueError("Task run not found")
    if task_run.status != "completed":
        raise ValueError("Task run must be completed")
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
    summary = _summary(findings, spec_version.rules_json)
    target = models.AuditTarget(
        name=target_name.strip(), business_key=(business_key.strip() or None) if business_key else None,
        findings_json=findings, summary_json=summary, outcome=_outcome(summary),
    )
    run = models.AuditRun(
        name=name, carrier="app", phase=phase, spec_version=spec_version, source_kind="app_task_run",
        source_ref_json={"task_run_id": str(task_run_id), "skill_id": str(skill_id)},
        targets=[target], summary_json=_run_summary([target]), created_by=user_id,
    )
    db.add(run)
    db.flush()
    if project is not None:
        assign_run(db, run, project)
    return run


def set_target_baseline(db: Session, target: models.AuditTarget,
                        baseline: models.AuditTarget | None) -> models.AuditTarget:
    if baseline is not None:
        if target.run.phase != "post":
            raise ValueError("Only post targets can have a baseline")
        if baseline.run.phase != "pre":
            raise ValueError("Baseline must be a pre target")
        if target.run.project_id is None or target.run.project_id != baseline.run.project_id:
            raise ValueError("Baseline must belong to the same project")
        if not target.business_key or target.business_key != baseline.business_key:
            raise ValueError("Baseline must have the same nonempty business_key")
    target.baseline_target = baseline
    target.baseline_target_id = baseline.id if baseline is not None else None
    db.flush()
    return target


def assign_run(db: Session, run: models.AuditRun, project: models.AuditProject | None) -> models.AuditRun:
    db.flush()
    project_id = project.id if project is not None else None
    if run.project_id == project_id:
        return run
    # A move invalidates both outgoing and incoming links, even between projects.
    target_ids = [target.id for target in run.targets]
    linked = db.query(models.AuditTarget).filter(models.AuditTarget.baseline_target_id.in_(target_ids)).all()
    for target in [*run.targets, *linked]:
        target.baseline_target = None
        target.baseline_target_id = None
    run.project = project
    run.project_id = project_id
    db.flush()
    if project is not None and run.phase == "post":
        keys = {target.business_key for target in run.targets if target.business_key}
        candidates = db.query(models.AuditTarget).join(models.AuditRun).filter(
            models.AuditRun.project_id == project_id, models.AuditRun.phase == "pre",
            models.AuditTarget.business_key.in_(keys),
        ).order_by(models.AuditRun.created_at.desc(), models.AuditRun.id.desc(), models.AuditTarget.id.desc()).all()
        latest = {}
        for baseline in candidates:
            latest.setdefault(baseline.business_key, baseline)
        for target in run.targets:
            baseline = latest.get(target.business_key)
            target.baseline_target = baseline
            target.baseline_target_id = baseline.id if baseline is not None else None
    db.flush()
    return run


def compare_targets(pre: models.AuditTarget, post: models.AuditTarget) -> dict:
    """Compare findings without changing targets or requiring a stored baseline."""
    pre_spec, post_spec = pre.run.spec_version, post.run.spec_version
    result = compare(pre.findings_json, post.findings_json,
                     pre_spec=(str(pre_spec.spec_id), str(pre_spec.id)),
                     post_spec=(str(post_spec.spec_id), str(post_spec.id)))
    pre_rules = {rule["rule_id"]: rule for rule in pre_spec.rules_json}
    post_rules = {rule["rule_id"]: rule for rule in post_spec.rules_json}
    counts = dict.fromkeys(COMPARE_CATEGORIES, 0)
    for row in result["rules"]:
        before, after = pre_rules.get(row["rule_id"]), post_rules.get(row["rule_id"])
        if not (before and after and before["enabled"] and after["enabled"]
                and pre.run.carrier in before["carriers"] and post.run.carrier in after["carriers"]):
            row["category"] = "not_comparable"
        duplicate = (before or {}).get("duplicate_of") or (after or {}).get("duplicate_of")
        if not duplicate:
            counts[row["category"]] += 1
    result["counts"] = counts
    return result
