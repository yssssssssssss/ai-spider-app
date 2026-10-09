"""Expose dedicated JD checks in the shared report shape, retaining the raw report."""
import json


def normalize_floor_reports(report, task, run_id, device_serial):
    if report.get("report_type") != "jd_new_floor_audit":
        return []
    reports = []
    for source in (report, report.get("secondary_tab_audit")):
        if not source:
            continue
        provenance = source.get("provenance") or {}
        checks = []
        for key, check in source.get("checks", {}).items():
            evidence = []
            for item in check.get("evidence") or check.get("annotations") or []:
                frame = (source.get("frames") or {}).get(item.get("frame"), {})
                artifact = frame if frame else report.get("artifacts", {}).get("raw", {})
                evidence.append({**item, "image_id": artifact.get("image_id"), "filename": artifact.get("filename") or artifact.get("raw_file")})
            checks.append({
                "rule_id": str(check.get("id") or key), "clause": check.get("title"),
                # Old reports do not snapshot the original normative text. Do not invent it.
                "expected": None, "observed": json.dumps(check.get("details") or {}, ensure_ascii=False),
                "status": check.get("status", "uncertain"), "reason": check.get("conclusion"),
                "method": "dedicated_rule_engine", "evidence": evidence,
            })
        reports.append({
            "schema_version": 1, "report_type": "specification_inspection",
            "specification": None,
            "rule_engine": {"source": provenance.get("implementation"), "sha256": provenance.get("implementation_sha256")},
            "scene": {"app": task.get("target_app"), "name": task.get("target_scenario"), "task_run_id": run_id, "device_serial": device_serial},
            "checks": checks, "model_calls": provenance.get("model_calls", []),
            "summary": {status: sum(check["status"] == status for check in checks)
                        for status in ("pass", "fail", "uncertain", "not_applicable")},
        })
    return reports
