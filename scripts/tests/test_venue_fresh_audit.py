import argparse
import asyncio
import hashlib
import os
from pathlib import Path
import shutil
from urllib.parse import quote

import cv2
from PIL import Image
import pytest

from scripts import build_venue_recheck_report as report
from scripts import rerun_venue_audit as replay
from scripts.audit_spec_profile import build_profile

ROOT = Path(__file__).resolve().parents[2]
OFFICIAL = ROOT / "docs/specifications/official-venue-review"


@pytest.fixture
def capture_bundle(tmp_path, spec_version):
    source, output = tmp_path / "capture", tmp_path / "audit"
    source.mkdir()
    url = "https://babelserv.m.jd.com/service/preview/mall/active/CorrectVenue/1791734400000?source=preview&pageId=123"
    venue = {"record_id": "p01-r01-RA1", "venue_id": "RA1", "venue_name": "测试会场", "project_id": "001",
             "source_page": 1, "source_row": 1, "qr_file": "qrcodes/target.png", "preview_url": url, "official_url": None}
    qr = source / venue["qr_file"]
    qr.parent.mkdir()
    cv2.imwrite(str(qr), cv2.QRCodeEncoder_create().encode(url))
    folder = source / "venues" / venue["record_id"]
    folder.mkdir(parents=True)
    identity = {"record_id": venue["record_id"], "status": "verified_entry"}
    capture = {"venue": venue, "identity_verification": identity, "navigation_status": "verified_entry",
               "navigation_url": url, "capture_status": "success", "screens": []}
    for number in (1, 2):
        file = f"venues/{venue['record_id']}/screen-{number}.png"
        Image.new("RGB", (390, 844), "white").save(source / file)
        capture["screens"].append({"number": number, "file": file, "width": 390, "height": 844,
                                   "sha256": hashlib.sha256((source / file).read_bytes()).hexdigest(), "scroll_y": (number - 1) * 844})
    replay.atomic(source / "catalog.json", {"venues": [venue]})
    replay.atomic(source / "identity-verification.json", {"entries": [identity]})
    replay.atomic(folder / "capture.json", capture)
    profile = build_profile(spec_version.rules_json, spec_version.source_json)
    profile_path = tmp_path / "profile.json"
    replay.atomic(profile_path, profile)
    return argparse.Namespace(source=source, output=output, spec=profile_path, capture=capture, venue=venue, profile=profile)


def reply_for(profile, page_state="ready"):
    return replay.Reply(page_state=page_state, overview="会场首轮审核", page_warnings=[], visual_regions=[],
        checks=[replay.Check(rule_id=r["id"], status="pass", observed="当前截图可见", reason="符合本轮要求",
                            evidence=[replay.Evidence(screen=1, bbox_norm=[0, 0, 1000, 1000])])
                for r in profile["rules"] if r["enabled"]],
        facts=replay.H5Facts(hero_complete=True, hero_evidence=replay.Evidence(screen=1, bbox_norm=[0, 50, 1000, 300]),
            main_title_complete=True, texts=[replay.HeroText(screen=1, bbox_norm=[10, 100, 600, 200],
                text="好物上新", role="main_title", readable=True)], pure_product_hero=True,
            product_count=1, products=[replay.Evidence(screen=1, bbox_norm=[650, 80, 900, 250])],
            person_count=0, people=[], countdown_present=False, countdown_evidence=None,
            first_screen_assessment_complete=True, complete_first_screen_feeds_products=[])
        if page_state == "ready" else None)


def run_audit(bundle, monkeypatch, reply=None, fresh=True, no_gate=False):
    calls = []

    async def complete_images(self, prompt, images, **kwargs):
        calls.append(prompt)
        if reply is None:
            pytest.fail("unavailable captures must not call the model")
        return reply.model_dump_json()

    monkeypatch.setattr(replay.LLMAnalyzer, "complete_images", complete_images)
    args = argparse.Namespace(source=str(bundle.source), output=str(bundle.output), spec=str(bundle.spec),
                              concurrency=2, limit=None, records_file=None, normalize_only=False, fresh=fresh, no_gate=no_gate)
    asyncio.run(replay.main(args))
    assert replay.read(bundle.output / "progress.json")["failed"] == 0
    report.build(bundle.output)
    return calls, replay.read(bundle.output / "results.json")


@pytest.mark.parametrize("official_profile", [False, True])
def test_fresh_capture_import_counts_and_report(capture_bundle, monkeypatch, audit_workspace, spec_version, official_profile):
    bundle = capture_bundle
    if official_profile:
        bundle.profile = replay.read(OFFICIAL / "h5-v5.json")
        replay.atomic(bundle.spec, bundle.profile)
    disabled = 10 if official_profile else 0
    # Even an unrelated/broken results file must never be consulted in fresh mode.
    (bundle.source / "results.json").write_text("not a baseline")
    calls, packet = run_audit(bundle, monkeypatch, reply_for(bundle.profile))
    assert len(calls) == 1
    audit = packet["results"][0]["audit"]
    assert audit["page_state"] == "ready"
    assert all(c["previous_status"] is None for c in audit["checks"])
    assert audit["mandatory_fail_count"] == 1  # OV-005/023 share one issue.
    assert packet["status_counts"] == {"visible_issues": 1}
    parsed, = audit_workspace.parse_h5_results(packet, rules=spec_version.rules_json)
    assert parsed.outcome == "issues"
    assert parsed.capture_reason is None
    assert parsed.summary == {"pass": 7, "fail": 1, "uncertain": 2, "not_applicable": 2, "disabled": disabled}
    assert len(parsed.findings) == 13 + disabled
    baseline = replay.read(bundle.output / "baseline.json")
    assert baseline["fresh"] is True and baseline["results_sha256"] is None
    assert packet["fresh"] is True and packet["comparison"] is None
    assert not (bundle.output / "comparison.json").exists()
    assert not (bundle.output / "comparison.csv").exists()
    assert (bundle.output / "report.html").is_file()
    assert (bundle.output / "venues.csv").is_file()
    assert (bundle.output / "checks.csv").is_file()
    assert (bundle.output / "venues" / bundle.venue["record_id"] / "visual-evidence.html").is_file()
    assert (bundle.output / "specification/assets/frameworks.png").read_bytes() == (OFFICIAL / "assets/frameworks.png").read_bytes()
    # Building again must not depend on the original capture directory.
    shutil.rmtree(bundle.source)
    report.build(bundle.output)


@pytest.mark.parametrize("page_state", ["error", "loading", "unknown"])
def test_fresh_page_state_comes_from_reply(capture_bundle, monkeypatch, audit_workspace, page_state):
    calls, packet = run_audit(capture_bundle, monkeypatch, reply_for(capture_bundle.profile, page_state))
    assert len(calls) == 1
    assert packet["results"][0]["audit"]["page_state"] == page_state
    parsed, = audit_workspace.parse_h5_results(packet)
    assert parsed.outcome == "capture_failed"
    assert parsed.summary["uncertain"] == 12  # duplicate rule excluded


@pytest.mark.parametrize("failure,screen_count,reason", [
    ("capture_failed", 0, "other"), ("capture_failed", 1, "other"),
    ("login_required", 2, "login_required"), ("recorded_login", 2, "login_required"),
    ("official_entry_conflict", 2, "other"), ("wrong_qr", 2, "other"),
    ("unverified_redirect", 2, "offline"),
])
def test_unavailable_captures_skip_model_and_import_as_capture_failed(
        capture_bundle, monkeypatch, audit_workspace, failure, screen_count, reason):
    bundle = capture_bundle
    capture = bundle.capture
    capture["screens"] = capture["screens"][:screen_count]
    if failure == "capture_failed":
        capture.update(capture_status="failed", error_type="ScreenshotTimeout")
    elif failure == "login_required":
        capture.update(navigation_status="login_required",
                       navigation_url="https://plogin.m.jd.com/login/login?returnurl=" + quote(bundle.venue["preview_url"], safe=""))
    elif failure == "recorded_login":
        replay.atomic(bundle.source / "identity-verification.json", {"entries": [{"record_id": bundle.venue["record_id"], "status": "login_required"}]})
    elif failure == "official_entry_conflict":
        bundle.venue["official_url"] = "https://pro.m.jd.com/mall/active/OtherVenue/index.html"
        replay.atomic(bundle.source / "catalog.json", {"venues": [bundle.venue]})
    elif failure == "wrong_qr":
        cv2.imwrite(str(bundle.source / bundle.venue["qr_file"]), cv2.QRCodeEncoder_create().encode(bundle.venue["preview_url"].replace("CorrectVenue", "OtherVenue")))
    else:
        capture.update(navigation_status="unverified_redirect", navigation_url="https://example.test/other", requested_url=bundle.venue["preview_url"])
    replay.atomic(bundle.source / "venues" / bundle.venue["record_id"] / "capture.json", capture)
    calls, packet = run_audit(bundle, monkeypatch)
    assert calls == []
    audit = packet["results"][0]["audit"]
    assert audit["summary"] == {"uncertain": 13}
    assert audit["model_calls"] == []
    assert audit.get("capture_gate", {}).get("verdict") == "blocked" or "capture_failed" in " ".join(audit["page_warnings"])
    assert packet["status_counts"] == {"page_error": 1}
    parsed, = audit_workspace.parse_h5_results(packet)
    assert parsed.outcome == "capture_failed"
    assert parsed.capture_reason == reason
    assert parsed.summary["capture_detail"]["page_warnings"] == audit["page_warnings"]


def test_reaudit_keeps_baseline_comparison(capture_bundle, monkeypatch, audit_workspace):
    bundle = capture_bundle
    shutil.copytree(OFFICIAL / "assets", bundle.source / "specification/assets")
    replay.atomic(bundle.source / "specification/walkthrough.json", bundle.profile)
    previous_reply = reply_for(bundle.profile, "error")
    previous = replay.normalize(previous_reply, bundle.capture, bundle.profile, [], [], None)
    previous.update(overview="原始页面异常", page_warnings=["login_required"])
    replay.atomic(bundle.source / "results.json", {"results": [{"venue": bundle.venue, "status": "page_error", "audit": previous}]})
    calls, packet = run_audit(bundle, monkeypatch, fresh=False)
    assert calls == []
    audit = packet["results"][0]["audit"]
    assert audit["page_state"] == "error" and audit["overview"] == "原始页面异常"
    assert audit["page_warnings"] == ["login_required"]
    assert all(c["previous_status"] == "uncertain" for c in audit["checks"])
    assert "fresh" not in replay.read(bundle.output / "baseline.json")
    assert packet["comparison"]["baseline_venue_counts"] == {"page_error": 1}
    assert packet["comparison"]["changes"] == []
    assert (bundle.output / "comparison.json").is_file()
    assert (bundle.output / "comparison.csv").is_file()
    assert audit_workspace.parse_h5_results(packet)[0].capture_reason == "login_required"


def test_ready_reaudit_runs_model_and_compares_to_original(capture_bundle, monkeypatch):
    bundle = capture_bundle
    shutil.copytree(OFFICIAL / "assets", bundle.source / "specification/assets")
    replay.atomic(bundle.source / "specification/walkthrough.json", bundle.profile)
    previous_reply = reply_for(bundle.profile)
    previous_reply.facts.complete_first_screen_feeds_products = [replay.Evidence(screen=1, bbox_norm=[20, 500, 980, 800])]
    previous = replay.normalize(previous_reply, bundle.capture, bundle.profile, [], [], None)
    replay.atomic(bundle.source / "results.json", {"results": [{"venue": bundle.venue, "status": "needs_confirmation", "audit": previous}]})
    calls, packet = run_audit(bundle, monkeypatch, reply_for(bundle.profile), fresh=False)
    assert len(calls) == 1
    changes = packet["comparison"]["changes"]
    assert {c["rule_id"] for c in changes} == {"OV-005", "OV-023"}
    assert all(c["previous_status"] == "pass" and c["status"] == "fail" for c in changes)
    assert packet["comparison"]["transition_counts"] == {"pass->fail": 2}


def test_fresh_saved_identity_failure_overrides_cached_ready_audit(capture_bundle, monkeypatch):
    bundle = capture_bundle
    run_audit(bundle, monkeypatch, reply_for(bundle.profile))
    replay.atomic(bundle.source / "identity-verification.json", {"entries": [{"record_id": bundle.venue["record_id"], "status": "login_required"}]})
    calls, packet = run_audit(bundle, monkeypatch)
    assert calls == []
    assert packet["status_counts"] == {"page_error": 1}


def test_fresh_selection_uses_catalog_and_requires_profile(capture_bundle, tmp_path):
    bundle = capture_bundle
    records = tmp_path / "records.json"
    replay.atomic(records, {"record_ids": [bundle.venue["record_id"]]})
    catalog, baseline, _ = replay.prepare(bundle.source, bundle.output, bundle.spec, records_path=records, fresh=True)
    assert baseline is None
    assert catalog["selected_venue_count"] == 1
    with pytest.raises(ValueError, match="requires --spec"):
        replay.prepare(bundle.source, tmp_path / "no-profile", fresh=True)
    replay.atomic(records, {"record_ids": ["unknown"]})
    with pytest.raises(ValueError, match="duplicated or unknown"):
        replay.prepare(bundle.source, tmp_path / "unknown", bundle.spec, records_path=records, fresh=True)


@pytest.mark.parametrize("no_gate", [False, True])
@pytest.mark.parametrize("official_profile", [False, True])
def test_title_gate_before_model_and_no_gate_escape(capture_bundle, monkeypatch, no_gate, official_profile):
    bundle = capture_bundle
    if official_profile:
        bundle.profile = replay.read(OFFICIAL / "h5-v5.json")
        replay.atomic(bundle.spec, bundle.profile)
    bundle.capture["page_title"] = "挑好物逛京东"
    replay.atomic(bundle.source / "venues" / bundle.venue["record_id"] / "capture.json", bundle.capture)
    calls, packet = run_audit(bundle, monkeypatch, reply_for(bundle.profile), no_gate=no_gate)
    audit = packet["results"][0]["audit"]
    assert len(calls) == int(no_gate)
    if no_gate:
        assert "capture_gate" not in audit
    else:
        assert packet["results"][0]["status"] == "page_error"
        assert audit["capture_gate"]["reason"] == "venue_lost"
        assert audit["model_calls"] == []
        assert all(c["status"] == "uncertain" and "capture_gate:venue_lost" in c["reason"] for c in audit["checks"])
        assert audit["page_warnings"] == [audit["capture_gate"]["message"]]


def test_floor_error_calls_model_and_marks_related_checks_uncertain(capture_bundle, monkeypatch):
    bundle = capture_bundle
    bundle.capture["first_screen_text"] = "楼层异常"
    replay.atomic(bundle.source / "venues" / bundle.venue["record_id"] / "capture.json", bundle.capture)
    calls, packet = run_audit(bundle, monkeypatch, reply_for(bundle.profile))
    audit = packet["results"][0]["audit"]
    assert len(calls) == 1 and audit["page_state"] == "ready"
    assert audit["capture_gate"]["verdict"] == "degraded"
    assert audit["capture_gate"]["message"] in audit["page_warnings"]
    checks = {c["rule_id"]: c for c in audit["checks"]}
    assert all(checks[rid]["status"] == "uncertain" for rid in ("OV-001", "OV-002", "OV-005", "OV-009", "OV-023"))
    assert checks["OV-017"]["status"] == "pass"


def test_changed_capture_invalidates_cached_gate_and_can_recover(capture_bundle, monkeypatch):
    bundle = capture_bundle
    run_audit(bundle, monkeypatch, reply_for(bundle.profile))
    bundle.capture["page_title"] = "挑好物逛京东"
    path = bundle.source / "venues" / bundle.venue["record_id"] / "capture.json"
    replay.atomic(path, bundle.capture)
    calls, packet = run_audit(bundle, monkeypatch)
    assert not calls and packet["status_counts"] == {"page_error": 1}
    calls, packet = run_audit(bundle, monkeypatch, reply_for(bundle.profile), no_gate=True)
    assert len(calls) == 1 and packet["results"][0]["audit"]["page_state"] == "ready"


@pytest.mark.parametrize("lost", [False, True])
def test_newer_reaudit_capture_rechecks_gate_and_can_recover_previous_error(capture_bundle, monkeypatch, lost):
    bundle = capture_bundle
    shutil.copytree(OFFICIAL / "assets", bundle.source / "specification/assets")
    replay.atomic(bundle.source / "specification/walkthrough.json", bundle.profile)
    previous = replay.normalize(reply_for(bundle.profile, "error"), bundle.capture, bundle.profile, [], [], None)
    baseline = bundle.source / "results.json"
    replay.atomic(baseline, {"results": [{"venue": bundle.venue, "status": "page_error", "audit": previous}]})
    bundle.capture["page_title"] = "挑好物逛京东" if lost else "正常会场"
    path = bundle.source / "venues" / bundle.venue["record_id"] / "capture.json"
    replay.atomic(path, bundle.capture)
    stamp = baseline.stat().st_mtime_ns + 1_000_000
    os.utime(path, ns=(stamp, stamp))
    calls, packet = run_audit(bundle, monkeypatch, reply_for(bundle.profile), fresh=False)
    assert len(calls) == int(not lost)
    assert packet["results"][0]["audit"]["capture_gate"]["verdict"] == ("blocked" if lost else "ok")


def test_legacy_valid_cache_attaches_gate_without_another_model_call(capture_bundle, monkeypatch):
    bundle = capture_bundle
    run_audit(bundle, monkeypatch, reply_for(bundle.profile))
    path = bundle.output / "venues" / bundle.venue["record_id"] / "audit.json"
    audit = replay.read(path)
    del audit["capture_gate"]
    replay.atomic(path, audit)
    calls, packet = run_audit(bundle, monkeypatch)
    assert not calls and packet["results"][0]["audit"]["capture_gate"]["verdict"] == "ok"


def test_new_screens_replace_cached_capture_and_gate_before_model(capture_bundle, monkeypatch):
    bundle = capture_bundle
    run_audit(bundle, monkeypatch, reply_for(bundle.profile))
    screen = bundle.capture["screens"][0]
    image = bundle.source / screen["file"]
    Image.new("RGB", (390, 844), "black").save(image)
    screen["sha256"] = hashlib.sha256(image.read_bytes()).hexdigest()
    bundle.capture["page_title"] = "挑好物逛京东"
    replay.atomic(bundle.source / "venues" / bundle.venue["record_id"] / "capture.json", bundle.capture)
    calls, packet = run_audit(bundle, monkeypatch)
    assert not calls and packet["status_counts"] == {"page_error": 1}
    assert (bundle.output / screen["file"]).read_bytes() == image.read_bytes()


def test_recovered_capture_drops_previous_gate_warning(capture_bundle, monkeypatch):
    bundle = capture_bundle
    bundle.capture["first_screen_text"] = "楼层异常"
    path = bundle.source / "venues" / bundle.venue["record_id"] / "capture.json"
    replay.atomic(path, bundle.capture)
    run_audit(bundle, monkeypatch, reply_for(bundle.profile))
    bundle.source = bundle.output
    bundle.output = bundle.output.parent / "reaudit"
    bundle.capture["first_screen_text"] = "正常会场"
    path = bundle.source / "venues" / bundle.venue["record_id"] / "capture.json"
    replay.atomic(path, bundle.capture)
    calls, packet = run_audit(bundle, monkeypatch, reply_for(bundle.profile), fresh=False)
    audit = packet["results"][0]["audit"]
    assert len(calls) == 1 and audit["capture_gate"]["verdict"] == "ok"
    assert not any("capture_gate:floor_error" in w for w in audit["page_warnings"])
    assert next(c for c in audit["checks"] if c["rule_id"] == "OV-001")["status"] == "pass"
