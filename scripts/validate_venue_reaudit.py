"""Verify complete replay coverage and package the evidence without changing the baseline."""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shutil
import zipfile
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.venue_identity import capture_fingerprint, verify_capture_identity
from scripts.recheck_tab_spacing import classify_spacing, verify_dom
from scripts.venue_check_evidence import CheckEvidenceBuilder


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate(root):
    catalog, packet, baseline = read(root / "catalog.json"), read(root / "results.json"), read(root / "baseline.json")
    spec = read(root / "specification/walkthrough.json")
    rule_ids = {r["id"] for r in spec["rules"]}
    rule_map = {r["id"]: r for r in spec["rules"]}
    total = len(catalog["venues"])
    h5 = spec.get("audit_mode") == "h5_v2"
    source = Path(baseline["source"])
    assert hashlib.sha256((source / "results.json").read_bytes()).hexdigest() == baseline["results_sha256"], "baseline changed"
    assert hashlib.sha256((root / "specification/source.pdf").read_bytes()).hexdigest() == spec["source"]["sha256"]
    assert total > 0 and total == len({v["venue_id"] for v in catalog["venues"]})
    assert len(packet["results"]) == total and not packet["status_counts"].get("pending"), "replay incomplete"
    evidence_builder = CheckEvidenceBuilder(root)
    evidence_counts = Counter()
    screens, checks, measurements = 0, 0, 0
    models, states, check_counts, measurement_states = Counter(), Counter(), Counter(), Counter()
    for row in packet["results"]:
        venue, capture, audit = row["venue"], row["capture"], row["audit"]
        assert audit and venue == capture["venue"] == audit["venue"], "identity mismatch"
        verify_capture_identity(root, venue, capture, audit["page_state"])
        assert audit.get("capture_fingerprint") == capture_fingerprint(capture), "audit uses different captures"
        assert len(capture["screens"]) == 2
        for screen in capture["screens"]:
            payload = (root / screen["file"]).read_bytes()
            assert hashlib.sha256(payload).hexdigest() == screen["sha256"]
            assert hashlib.sha256((source / screen["file"]).read_bytes()).hexdigest() == screen["sha256"]
            assert (int.from_bytes(payload[16:20], "big"), int.from_bytes(payload[20:24], "big")) == (390, 844)
            screens += 1
        assert len(audit["checks"]) == len(rule_ids) and {c["rule_id"] for c in audit["checks"]} == rule_ids
        assert sum(audit["summary"].values()) == len(rule_ids)
        states[audit["page_state"]] += 1
        for check in audit["checks"]:
            checks += 1
            check_counts[check["status"]] += 1
            if "check_evidence" in row and check.get("enabled", True):
                detail = evidence_builder.prepare(check, capture, venue)
                assert row["check_evidence"].get(check["rule_id"]) == detail, "check detail evidence mismatch"
                evidence_counts[detail["state"]] += 1
            rule = rule_map[check["rule_id"]]
            if h5:
                assert check["enabled"] == rule["enabled"] and check["expected"] == rule["expected"]
                assert (check["status"] == "disabled") == (not rule["enabled"])
                if check["status"] == "disabled":
                    assert not check["evidence"] and not check["measurement_ids"]
            if audit["page_state"] != "ready" and rule.get("enabled", True):
                assert check["status"] == "uncertain", "unavailable page received a verdict"
            if check["status"] in {"pass", "fail"}:
                assert check["evidence"], "missing evidence"
                if check["rule_id"] == "OV-009" and spec.get("spacing", {}).get("acceptable_range_px"):
                    review = {**check["facts"], "venue": venue}
                    verify_dom(root, review)
                    assert classify_spacing(review, spec["spacing"]) == check["status"], "spacing range verdict mismatch"
            for evidence in check["evidence"]:
                screen = capture["screens"][evidence["screen"] - 1]
                assert evidence["file"] == screen["file"] and evidence["sha256"] == screen["sha256"]
                left, top, right, bottom = evidence["bbox_px"]
                assert 0 <= left < right <= 390 and 0 <= top < bottom <= 844
        for item in audit["visual_measurements"]:
            measurements += 1
            measurement_states[item["status"]] += 1
            assert item["sha256"] == capture["screens"][item["screen"] - 1]["sha256"]
            for band in item.get("result", {}).get("bands", []):
                if item["role"] == "floor_gap":
                    comparison = band["length_comparison"]
                    interval = spec.get("spacing", {}).get("acceptable_range_px")
                    if interval:
                        assert comparison["status"] in {"within_range", "outside_range"}
                        assert comparison["min_px"] == interval["min"] and comparison["max_px"] == interval["max"]
                    else:
                        assert comparison["status"] == ("measured_without_acceptance_tolerance" if h5 else "needs_calibration")
                    if h5 and not interval:
                        assert comparison["calibration_confirmed"]
                        assert math.isclose(comparison["expected_image_px"], 24 * capture["screens"][item["screen"] - 1]["height"] / 812, abs_tol=1e-9)
        if audit["visual_measurements"] or audit.get("structured_facts"):
            assert (root / "venues" / venue["record_id"] / "visual-evidence.html").exists()
        for call in audit["model_calls"]:
            if call["status"] == "success":
                models[call["response_model"] or call["requested_model"]] += 1
        assert not (root / "venues" / venue["record_id"] / "audit-error.json").exists(), "unrecovered model error"
    assert dict(check_counts) == packet["comparison"]["new_check_counts"]
    assert screens == 2 * total and checks == len(rule_ids) * total and measurements == packet["comparison"]["measurement_requests"]
    for name, expected in (("venues.csv", total + 1), ("checks.csv", checks + 1), ("measurements.csv", measurements + 1)):
        with (root / name).open(encoding="utf-8-sig", newline="") as stream:
            assert len(list(csv.reader(stream))) == expected, "CSV coverage mismatch"
    validation = {"status": "passed", "validated_at": datetime.now(timezone.utc).isoformat(),
                  "venue_count": total, "screen_count": screens, "rule_check_count": checks,
                  "rule_version": spec["version"], "active_rule_count": sum(r.get("enabled", True) for r in spec["rules"]),
                  "check_counts": dict(check_counts), "check_evidence_states": dict(evidence_counts), "page_state_counts": dict(states), "successful_response_models": dict(models),
                  "measurement_count": measurements, "measurement_status_counts": dict(measurement_states),
                  "original_screens_unchanged": True, "baseline_results_unchanged": True,
                  "qr_entry_identity_verified": True, "audit_capture_fingerprints_verified": True,
                  "unit_policy": ("user_confirmed_h5_pixel_range" if spec["spacing"].get("acceptable_range_px") else "user_confirmed_812_viewport_no_tolerance") if h5 else "screenshot_pixels_only"}
    write(root / "validation.json", validation)
    run = read(root / "run.json")
    run.update({"status": "complete", "completed_at": validation["validated_at"], "screen_count": screens,
                "rule_check_count": checks, "result_counts": packet["status_counts"], "validation_file": "validation.json"})
    write(root / "run.json", run)
    implementation = root / "implementation"
    implementation.mkdir(exist_ok=True)
    project = Path(__file__).resolve().parents[1]
    for name in ("scripts/rerun_venue_audit.py", "scripts/build_venue_recheck_report.py", "scripts/venue_check_evidence.py", "scripts/venue_check_evidence.js", "scripts/venue_check_evidence.css", "scripts/validate_venue_reaudit.py", "scripts/recheck_tab_spacing.py", "scripts/apply_tab_spacing_reviews.py", "scripts/capture_tab_spacing.mjs", "scripts/web_visual_probe.mjs", "scripts/venue_identity.py", "scripts/capture_venues.mjs", "backend/app/services/visual_measurement.py"):
        shutil.copyfile(project / name, implementation / Path(name).name)
    files = sorted(path for path in root.rglob("*") if path.is_file() and path.name != "manifest.sha256")
    manifest = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(root)}\n" for path in files)
    (root / "manifest.sha256").write_text(manifest, encoding="utf-8")
    files.append(root / "manifest.sha256")
    archive = root.with_suffix(".zip")
    with zipfile.ZipFile(archive, "w", allowZip64=True) as bundle:
        for path in files:
            bundle.write(path, arcname=str(Path(root.name) / path.relative_to(root)),
                         compress_type=zipfile.ZIP_STORED if path.suffix in {".png", ".pdf"} else zipfile.ZIP_DEFLATED)
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None, "archive CRC mismatch"
    print(json.dumps({"validation": validation, "archive": str(archive), "archive_bytes": archive.stat().st_size}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    validate(Path(parser.parse_args().output).resolve())
