"""H5 lifecycle requirements, with filesystem-producing substitutes for Ego/Python."""
from collections import deque
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

import cv2
from PIL import Image
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import models
from app.database import SessionLocal, engine, get_db, init_db
from app.routers import audit_workspace as router
from app.services import audit_job_h5 as h5, audit_jobs as jobs, audit_workspace as workspace
from app.services.auth import create_access_token
from app.services.audit_evidence import mark_not_attached
from scripts import rerun_venue_audit as replay, build_venue_recheck_report as report
from scripts.audit_spec_profile import build_profile
from scripts.tests.test_venue_fresh_audit import reply_for

URL = "https://yx.jd.com/activity-manage/merchants/detail/room/myManageVenue/edit/signedEdit?planCode=one&poolId=two"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False))


def catalog_at(root):
    venues = []
    for number in range(1, 4):
        url = f"https://babelserv.m.jd.com/service/preview/mall/active/Venue{number}/1791734400000?source=preview&pageId={number}"
        venue = {"record_id": f"p01-r0{number}-RA{number}", "venue_id": f"RA{number}", "venue_name": f"会场{number}",
                 "project_id": f"00{number}", "source_page": 1, "source_row": number,
                 "qr_file": f"qrcodes/RA{number}.png", "preview_url": url, "official_url": None}
        qr = root / venue["qr_file"]
        qr.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(qr), cv2.QRCodeEncoder_create().encode(url))
        venues.append(venue)
    write(root / "catalog.json", {"source_url": URL, "venues": venues})
    write(root / "identity-verification.json", {"entries": [
        {"record_id": v["record_id"], "status": "verified_entry"} for v in venues]})
    return venues


def capture_at(root, venue, failed=False):
    capture = {"venue": venue, "identity_verification": {"status": "verified_entry"},
               "navigation_status": "verified_entry", "navigation_url": venue["preview_url"],
               "capture_status": "failed" if failed else "success", "screens": []}
    if failed:
        capture["error_type"] = "ScreenshotTimeout"
    else:
        for number in (1, 2):
            file = f"venues/{venue['record_id']}/screen-{number}.png"
            path = root / file
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (390, 844), "white").save(path)
            capture["screens"].append({"number": number, "file": file, "width": 390, "height": 844,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "scroll_y": (number - 1) * 844})
    write(root / "venues" / venue["record_id"] / "capture.json", capture)


class FakeRunner:
    def __init__(self):
        self.preflights = deque([True])
        self.calls = []
        self.closed = []
        self.terminated = []
        self.fail_step = None
        self.stderr = ""
        self.block_step = None
        self.entered = threading.Event()
        self.release = threading.Event()
        self.capture_failed = set()
        self.pid = 10000
        self.spaces = set()

    def terminate(self, pid):
        self.terminated.append(pid)
        self.release.set()

    def run(self, args, *, cwd, stdin=None, on_start=None, on_json=None, cancelled=None):
        options = None
        if args[0] == "ego-browser":
            if "finish({keep: []})" in stdin:
                self.closed.extend(self.spaces)
                self.spaces.clear()
                return subprocess.CompletedProcess(args, 0, stderr="")
            step = "preflight"
            if stdin.startswith("globalThis.venueCapture = "):
                options = json.loads(stdin.split(";\n", 1)[0].split(" = ", 1)[1])
                step = "catalog" if options.get("VENUE_MODE") == "catalog" else "capture"
        else:
            step = {"audit_spec_profile.py": "profile", "rerun_venue_audit.py": "audit",
                    "build_venue_recheck_report.py": "report"}[Path(args[1]).name]
        self.calls.append((step, list(args), options))
        self.pid += 1
        if on_start:
            on_start(self.pid)
        if self.block_step == step:
            self.entered.set()
            assert self.release.wait(10), "test did not release fake subprocess"
        if cancelled and cancelled.is_set():
            return subprocess.CompletedProcess(args, -9, stderr="killed")
        if self.fail_step == step:
            return subprocess.CompletedProcess(args, 1, stderr=self.stderr)
        emit = on_json or (lambda message: None)
        if step == "preflight":
            self.spaces.add(23)
            emit({"space_id": 23})
            emit({"stage": "preflight", "space_id": 23, "ready": self.preflights.popleft() if self.preflights else True})
        elif step == "catalog":
            catalog_at(Path(options["VENUE_ROOT"]))
        elif step == "capture":
            source = Path(options["VENUE_ROOT"])
            ids = replay.read(Path(options["VENUE_RECORDS_FILE"]))["record_ids"]
            for venue in replay.read(source / "catalog.json")["venues"]:
                assert (source / venue["qr_file"]).is_file()  # capture's verifier checks the entire catalog.
                if venue["record_id"] in ids:
                    capture_at(source, venue, venue["venue_id"] in self.capture_failed)
                    emit({"stage": "captured", "record_id": venue["record_id"]})
                    if self.block_step == "capture_progress" and not self.entered.is_set():
                        self.entered.set()
                        assert self.release.wait(10)
        elif step == "profile":
            data = replay.read(Path(args[args.index("--input") + 1]))
            write(Path(args[args.index("--output") + 1]), build_profile(data["rules_json"], data["source_json"]))
        elif step == "audit":
            assert "--fresh" in args and args[args.index("--concurrency") + 1] == "6"
            source, output, profile, records = (Path(args[args.index(flag) + 1]) for flag in
                                              ("--source", "--output", "--spec", "--records-file"))
            catalog, _, spec = replay.prepare(source, output, profile, records_path=records, fresh=True)
            for venue in catalog["venues"]:
                folder = output / "venues" / venue["record_id"]
                capture = replay.read(folder / "capture.json")
                warnings = replay.fresh_capture_warnings(output, venue, capture)
                reply = reply_for(spec)
                if warnings:
                    reply = replay.Reply(page_state="error", overview="采集失败", page_warnings=warnings,
                        visual_regions=[], checks=[replay.Check(rule_id=r["id"], status="uncertain",
                            observed="采集失败", reason="页面未就绪", evidence=[]) for r in spec["rules"]])
                audit = replay.normalize(reply, capture, spec, [], [], None)
                write(folder / "audit.json", audit)
                emit({"stage": "audited", "record_id": venue["record_id"]})
            write(output / "run.json", {"status": "completed"})
            emit({"stage": "replay_finished", "completed": len(catalog["venues"]), "total": len(catalog["venues"]), "failed": 0})
        elif step == "report":
            report.build(Path(args[args.index("--output") + 1]))
        return subprocess.CompletedProcess(args, 0, stderr="")


@pytest.fixture
def context(tmp_path, monkeypatch):
    if "test" not in (engine.url.database or ""):
        pytest.skip("Never connect these tests to a development database")
    init_db()
    monkeypatch.setattr(jobs, "_executors", {})
    monkeypatch.setattr(h5.shutil, "which", lambda executable: "/fake/ego-browser")
    (tmp_path / "scripts").symlink_to(ROOT / "scripts", target_is_directory=True)
    runner = FakeRunner()
    executor = h5.H5AuditExecutor(runner, repo=tmp_path)
    jobs.register_executor("h5", executor)
    with SessionLocal() as db:
        spec = models.AuditSpec(key="h5-" + uuid4().hex, name="官方会场")
        db.add(spec)
        version = workspace.import_spec_version(db, spec,
            (ROOT / "docs/specifications/official-venue-review/h5-v5.json").read_bytes(), "h5")
        project = models.AuditProject(name="H5 测试项目")
        user = models.User(username="h5-" + uuid4().hex, password_hash="unused", role="operator")
        db.add_all([project, user])
        db.commit()
        app = FastAPI()
        app.include_router(router.router, prefix="/api")
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            client.headers["Authorization"] = "Bearer " + create_access_token(user)
            yield SimpleNamespace(db=db, version=version, project=project, executor=executor,
                                  runner=runner, repo=tmp_path, client=client)
        runner.release.set()
        thread = executor._thread
        if thread:
            thread.join(10)
            assert not thread.is_alive()
        db.rollback()
        for job in db.query(models.AuditJob).filter_by(spec_version_id=version.id):
            db.delete(job)
        db.flush()
        for run in db.query(models.AuditRun).filter_by(spec_version_id=version.id):
            db.delete(run)
        db.flush()
        for row in (project, version, spec, user):
            db.delete(row)
        db.commit()


def create(ctx, input=None, **extra):
    job = jobs.create_job(ctx.db, name="会场首轮审核", carrier="h5", phase="post",
        spec_version_id=ctx.version.id, project_id=ctx.project.id,
        input=input if input is not None else {"catalog_url": URL}, **extra)
    job_id = job.id
    ctx.db.commit()
    return job_id


def wait_for(ctx, job_id, status):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        ctx.db.expire_all()
        job = ctx.db.get(models.AuditJob, job_id)
        if job.status == status:
            return job
        if job.status in jobs.TERMINAL_STATUSES:
            pytest.fail(f"expected {status}, got {job.status}: {job.error}")
        time.sleep(0.01)
    pytest.fail(f"timed out waiting for {status}: {job.status} {job.status_detail}")


@pytest.mark.parametrize("url", ["http://yx.jd.com/x", "https://yx.jd.com.evil.test/x", "https://other.jd.com/x",
                                  "https://evil.test@yx.jd.com/x", "https://yx.jd.com:444/x"])
def test_reject_non_catalog_urls(context, url):
    with pytest.raises(ValueError, match="catalog_url"):
        create(context, {"catalog_url": url})
    context.db.rollback()
    assert not context.runner.calls


def test_reject_directory_outside_data_and_symlink(context, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "data").mkdir()
    (tmp_path / "data/escape").symlink_to(outside)
    for path in (str(outside), "../outside", "data/escape"):
        with pytest.raises(ValueError, match="data/"):
            create(context, {"catalog_dir": path})
        context.db.rollback()


def test_unknown_venue_ids_fail_with_all_unknown_ids(context):
    source = context.repo / "data/existing"
    catalog_at(source)
    job = wait_for(context, create(context, {"catalog_dir": "existing", "venue_ids": ["RA9", "RA8"]}), "failed")
    assert "RA8" in job.error and "RA9" in job.error
    assert not context.runner.calls


def test_login_handoff_continue_and_selected_capture(context):
    context.runner.preflights = deque([False, True])
    job_id = create(context, {"catalog_url": URL, "venue_ids": ["RA2"]})
    job = wait_for(context, job_id, "needs_action")
    assert "TaskSpace 23" in job.status_detail and "登录后点继续" in job.status_detail
    assert job.executor_ref_json["space_id"] == 23
    assert not context.runner.closed
    assert context.client.post(f"/api/audit-jobs/{job_id}/continue").status_code == 200
    job = wait_for(context, job_id, "completed")
    assert [step for step, _, _ in context.runner.calls] == ["preflight", "preflight", "catalog", "capture", "profile", "audit", "report"]
    run = context.db.get(models.AuditRun, job.audit_run_id)
    assert [target.business_key for target in run.targets] == ["RA2"]


def test_full_flow_matches_direct_parser_and_includes_capture_failures(context):
    context.runner.capture_failed = {"RA3"}
    job_id = create(context)
    job = wait_for(context, job_id, "completed")
    run = context.db.get(models.AuditRun, job.audit_run_id)
    assert run.project_id == context.project.id and run.phase == "post"
    packet = replay.read(Path(job.executor_ref_json["work_dir"]) / "audit/results.json")
    parsed = workspace.parse_h5_results(packet, rules=context.version.rules_json)
    assert len(parsed) == 3
    for target, direct in zip(sorted(run.targets, key=lambda t: t.business_key), sorted(parsed, key=lambda t: t.venue_id)):
        findings = deepcopy(target.findings_json)
        for finding in findings:
            mark_not_attached(finding["evidence"])
        assert (target.business_key, target.outcome, target.capture_reason, target.summary_json, findings) == (
            direct.venue_id, direct.outcome, direct.capture_reason, direct.summary, direct.findings)
    assert run.summary_json["targets"] == 3
    assert run.summary_json["outcomes"]["capture_failed"] == 1
    assert {t.business_key: t.capture_reason for t in run.targets}["RA3"] == "other"
    thread = context.executor._thread
    if thread:
        thread.join(10)
    assert context.runner.closed == [23]


def test_reuse_complete_directory_skips_browser_and_keeps_source_unchanged(context):
    source = context.repo / "data/existing"
    for venue in catalog_at(source):
        capture_at(source, venue)
    before = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    job = wait_for(context, create(context, {"catalog_dir": "data/existing", "venue_ids": ["RA1"]}), "completed")
    assert [step for step, _, _ in context.runner.calls] == ["profile", "audit", "report"]
    assert before == {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    assert context.db.get(models.AuditRun, job.audit_run_id).summary_json["targets"] == 1


def test_reuse_uncaptured_selection_keeps_catalog_qr_inputs_complete(context):
    source = context.repo / "data/existing"
    catalog_at(source)
    job = wait_for(context, create(context, {"catalog_dir": "existing", "venue_ids": ["RA2"]}), "completed")
    steps = [step for step, _, _ in context.runner.calls]
    assert steps == ["preflight", "capture", "profile", "audit", "report"]
    assert context.db.get(models.AuditRun, job.audit_run_id).summary_json["targets"] == 1
    assert not (source / "venues").exists()


def test_subprocess_failure_is_redacted_and_bounded_in_utf8_bytes(context):
    context.runner.fail_step = "capture"
    context.runner.stderr = "prefix" * 1000 + '\n' + '\n'.join([
        'TOKEN=token-value API_KEY="key value" password=private',
        'Cookie: session=secret-cookie; other=also-private', 'Authorization: Bearer private-bearer',
        '失败原因' * 100, 'https://example.test/?token=url-token&key=url-key', 'sk-private-secret'])
    job = wait_for(context, create(context), "failed")
    assert len(job.error.encode()) <= 2048
    for secret in ("token-value", "key value", "private", "secret-cookie", "also-private", "url-token", "url-key"):
        assert secret not in job.error
    assert "失败原因" in job.error
    assert "[REDACTED]" in job.error
    assert job.executor_ref_json["pid"] is None


def test_cancel_terminates_process_group_closes_space_and_wins_race(context):
    context.runner.block_step = "capture"
    job_id = create(context)
    assert context.runner.entered.wait(5)
    job = wait_for(context, job_id, "running")
    pid = job.executor_ref_json["pid"]
    thread = context.executor._thread
    assert context.client.post(f"/api/audit-jobs/{job_id}/cancel").status_code == 200
    thread.join(10)
    job = wait_for(context, job_id, "cancelled")
    assert context.runner.terminated == [pid]
    assert context.runner.closed == [23]
    assert job.audit_run_id is None
    assert not any(step == "audit" for step, _, _ in context.runner.calls)


def test_jobs_execute_serially_in_creation_order_with_queue_positions(context):
    context.runner.block_step = "capture"
    first = create(context)
    assert context.runner.entered.wait(5)
    second, third = create(context), create(context)
    assert context.db.get(models.AuditJob, second).status == "queued"
    assert context.db.get(models.AuditJob, second).status_detail == "排队中，前面还有 1 个"
    assert context.db.get(models.AuditJob, third).status_detail == "排队中，前面还有 2 个"
    assert [step for step, _, _ in context.runner.calls].count("preflight") == 1
    context.runner.release.set()
    for job_id in (first, second, third):
        wait_for(context, job_id, "completed")
    audits = [Path(args[args.index("--output") + 1]).parent.name for step, args, _ in context.runner.calls if step == "audit"]
    assert audits == [str(first), str(second), str(third)]


def test_json_lines_update_step_and_capture_progress(context):
    context.runner.block_step = "capture_progress"
    job_id = create(context)
    assert context.runner.entered.wait(5)
    job = wait_for(context, job_id, "running")
    assert job.status_detail == "采集 1/3"
    assert job.executor_ref_json["step"] == "capture"
    context.runner.release.set()
    wait_for(context, job_id, "completed")


def test_startup_interrupts_running_and_ingesting_preserves_action_and_requeues(context):
    rows = {}
    for status in ("running", "ingesting", "needs_action", "queued"):
        job = models.AuditJob(name="重启", carrier="h5", phase="pre", spec_version_id=context.version.id,
            input_json={"catalog_url": URL}, status=status, executor_ref_json={"step": "audit", "space_id": None})
        context.db.add(job)
        context.db.flush()
        rows[status] = job.id
    context.db.commit()
    context.executor.on_startup()
    for status in ("running", "ingesting"):
        job = wait_for(context, rows[status], "failed")
        assert job.error == "执行中断：后端重启"
    assert wait_for(context, rows["needs_action"], "needs_action").executor_ref_json["step"] == "audit"
    wait_for(context, rows["queued"], "completed")
    assert context.client.post(f"/api/audit-jobs/{rows['needs_action']}/continue").status_code == 200
    wait_for(context, rows["needs_action"], "completed")


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
@pytest.mark.parametrize("action", ["continue", "cancel"])
def test_terminal_job_actions_return_409(context, status, action):
    job = models.AuditJob(name="终态", carrier="h5", phase="pre", spec_version_id=context.version.id, status=status)
    context.db.add(job)
    context.db.commit()
    assert context.client.post(f"/api/audit-jobs/{job.id}/{action}").status_code == 409
    assert not context.runner.calls


def test_availability_requires_ego_and_scripts(context, monkeypatch):
    monkeypatch.setattr(h5.shutil, "which", lambda executable: None)
    available, reason = jobs.executor_availability(context.version, "h5")
    assert not available and "ego-browser" in reason
    monkeypatch.setattr(h5.shutil, "which", lambda executable: "/fake/ego-browser")
    (context.repo / "scripts").unlink()
    available, reason = context.executor.availability(context.version)
    assert not available and "capture_venues.mjs" in reason


def test_reconcile_only_wakes_worker_after_commit_and_recovers_missing_thread(context, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(context.executor, "_wake", lambda: None)
        job_id = create(context)
        assert not context.runner.calls
    # No browser availability lookup is needed by reconciliation.
    job = context.db.get(models.AuditJob, job_id)
    jobs.reconcile_job(context.db, job)
    assert job.status == "queued" and not context.runner.calls
    context.db.commit()
    wait_for(context, job_id, "completed")


def test_rollback_never_launches_work(context):
    jobs.create_job(context.db, name="回滚", carrier="h5", phase="pre", spec_version_id=context.version.id,
                    input={"catalog_url": URL})
    context.db.rollback()
    context.db.commit()  # An unrelated later commit must not wake a rolled-back request.
    assert context.executor._thread is None and not context.runner.calls


def test_process_runner_uses_process_group_signal(monkeypatch):
    calls = []
    monkeypatch.setattr(h5.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    h5.ProcessRunner().terminate(123)
    assert calls == [(123, h5.signal.SIGKILL)]
