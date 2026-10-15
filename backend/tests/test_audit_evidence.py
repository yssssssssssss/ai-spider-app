"""T9a-1 evidence contracts; fixtures generate their own images and reports."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
from uuid import uuid4
from zipfile import ZipFile, ZipInfo

import pytest
from PIL import Image
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from app import models
from app.config import settings
from app.database import engine, get_db, init_db
from app.routers import audit_workspace as router
from app.services import audit_evidence as evidence, audit_workspace as workspace
from app.services.auth import create_access_token
from scripts import backfill_audit_evidence as backfill
from test_audit_job_h5 import context as h5_context, create as create_job, wait_for


def image_bytes(format="PNG"):
    output = BytesIO()
    Image.new("RGB", (12, 18), f"#{uuid4().hex[:6]}").save(output, format=format)
    return output.getvalue()


def report_for(data, venue_id="venue-a", *, state="localized", source="original_capture"):
    sha = hashlib.sha256(data).hexdigest()
    file = f"venues/record-{venue_id}/screen-1.png"
    result = {
        "venue": {"venue_id": venue_id, "venue_name": "测试会场", "record_id": f"record-{venue_id}"},
        "capture": {"screens": [{"number": 1, "file": file, "sha256": sha, "width": 12, "height": 18}]},
        "audit": {"checks": [{"rule_id": "OV-001", "title": "框架", "status": "fail", "observed": "错位",
                              "reason": "顺序不对", "method": "h5_user_policy_v2", "model_status": "fail"}]},
        "check_evidence": {"OV-001": {"state": state, "items": [{
            "file": file, "sha256": sha, "image_size": [12, 18], "crop_px": [0, 1, 12, 16],
            "marks": [{"kind": "rect", "bbox_px": [1, 2, 10, 14], "label": "框架区域"}],
            "source": source, "status": state, "label": "原截图 1",
        }]}},
    }
    return {"results": [result]}


def package(packet, files, *, include_report=True):
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        if include_report:
            archive.writestr("results.json", json.dumps(packet))
        for file, data in files.items():
            archive.writestr(file, data)
    return output.getvalue()


def referenced(packet):
    return packet["results"][0]["check_evidence"]["OV-001"]["items"][0]


@pytest.fixture(autouse=True)
def asset_root(tmp_path, monkeypatch):
    root = tmp_path / "assets"
    monkeypatch.setattr(settings, "AUDIT_EVIDENCE_ROOT", str(root))
    return root


@pytest.fixture
def context():
    if "test" not in (engine.url.database or ""):
        pytest.skip("Evidence tests require a disposable test database")
    init_db()
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
            spec = models.AuditSpec(key="evidence-" + uuid4().hex, name="证据规范")
            version = models.AuditSpecVersion(spec=spec, version=1, label="v1", carrier_scope="both", sha256=uuid4().hex,
                source_json={}, rules_json=[{"rule_id": "OV-001", "title": "框架", "enabled": True}])
            user = models.User(username="evidence-" + uuid4().hex, password_hash="unused", role="operator")
            viewer = models.User(username="evidence-viewer-" + uuid4().hex, password_hash="unused", role="viewer")
            db.add_all([version, user, viewer])
            db.commit()
            app = FastAPI()
            app.include_router(router.router, prefix="/api")
            app.dependency_overrides[get_db] = lambda: db
            with TestClient(app) as client:
                token = create_access_token(user)
                client.headers["Authorization"] = "Bearer " + token
                yield SimpleNamespace(db=db, version=version, client=client, token=token, viewer=viewer)
        transaction.rollback()


def import_run(ctx, packet, source=None):
    return workspace.create_h5_run(ctx.db, json.dumps(packet).encode(), "results.json", ctx.version,
                                   "审核", evidence_source=source)


@pytest.mark.parametrize("state,role,converted", [
    ("localized", "localized", "localized"), ("context", "context", "context"),
    ("missing", "context", "missing"), ("candidate", "context", "context"),
])
def test_conversion_states_and_purity(state, role, converted):
    packet = report_for(image_bytes(), state=state)
    result = packet["results"][0]
    before = deepcopy(result)
    actual = evidence.convert_h5_evidence(result, "OV-001")
    assert actual["state"] == converted
    item = actual["items"][0]
    assert item["role"] == role
    assert item["asset"] == referenced(packet)["sha256"]
    assert item["screen"] == 1 and item["image_size"] == [12, 18]
    assert item["crop_px"] == [0, 1, 12, 16]
    assert item["marks"][0]["source"] == "model"
    item["marks"][0]["bbox_px"][0] = 99
    assert result == before


@pytest.mark.parametrize("source,expected", [("original_capture", "model"), ("live_h5_capture", "model"), ("live_h5_dom", "dom")])
def test_mark_sources_and_line_coordinates(source, expected):
    packet = report_for(image_bytes(), source=source)
    referenced(packet)["marks"] = [{"kind": "line", "start_px": [0, 2], "end_px": [12, 2], "dashed": True}]
    mark = evidence.convert_h5_evidence(packet["results"][0], "OV-001")["items"][0]["marks"][0]
    assert mark == {"kind": "line", "start_px": [0, 2], "end_px": [12, 2], "dashed": True, "source": expected}


def test_measurements_flags_values_and_methods():
    result = report_for(image_bytes())["results"][0]
    result["audit"]["visual_measurements"] = [{
        "id": "background", "rule_ids": ["OV-001"], "localization_method": "vlm_normalized_roi",
        "verified": True, "status": "measured", "result": {"dominant_hex": "#FFFFFF", "comparison": {
            "expected_hex": "#FFFFFF", "all_pixels_match": True}},
    }, {"id": "other", "rule_ids": ["OV-010"], "status": "measured"}]
    converted = evidence.convert_h5_evidence(result, "OV-001")
    assert len(converted["measurements"]) == 1
    measurement = converted["measurements"][0]
    assert measurement["verified"] is False
    assert (measurement["kind"], measurement["value"], measurement["expected"], measurement["verdict"]) == (
        "color", "#FFFFFF", "#FFFFFF", "pass")
    assert evidence.h5_finding_metadata(result, "OV-001") == {"method": "model", "model_status": "fail"}
    result["audit"]["checks"] = [{"rule_id": "OV-009", "method": "live_h5_dom_spacing", "model_status": "pass"}]
    result["audit"]["spacing_review"] = {
        "source": "live_h5_dom_spacing", "measurement_status": "measured", "semantic_boundary_verified": True,
        "distance_css_px": 12, "audit_status": "fail", "range_comparison": {"min_px": 7, "max_px": 9},
    }
    converted = evidence.convert_h5_evidence(result, "OV-009")
    spacing = converted["measurements"][0]
    assert (spacing["source"], spacing["verified"], spacing["value"], spacing["expected"]) == ("dom", True, 12, "7–9px")
    assert evidence.h5_finding_metadata(result, "OV-009") == {"method": "dom", "model_status": "pass"}
    result["audit"]["spacing_review"]["semantic_boundary_verified"] = False
    assert evidence.convert_h5_evidence(result, "OV-009")["measurements"][0]["verified"] is False


@pytest.mark.parametrize("method,expected", [("h5_user_policy_v2", "model"), ("h5_spacing_applicability", "model"), ("pixel", "pixel"), ("hybrid", "hybrid")])
def test_method_mapping(method, expected):
    result = report_for(image_bytes())["results"][0]
    result["audit"]["checks"][0]["method"] = method
    finding = workspace.parse_h5_results({"results": [result]})[0].findings[0]
    assert finding["method"] == expected and finding["model_status"] == "fail"


@pytest.mark.parametrize("kind", ["directory", "zip"])
def test_sources_read_only_exact_references(tmp_path, kind):
    data = image_bytes()
    if kind == "directory":
        (tmp_path / "image.png").write_bytes(data)
        source = evidence.DirectoryEvidenceSource(tmp_path)
    else:
        source = evidence.ZipEvidenceSource(BytesIO(package({}, {"image.png": data}, include_report=False)))
    with source:
        assert source.read("./image.png") == data
        with pytest.raises(FileNotFoundError):
            source.read("absent.png")
    assert not (tmp_path / "results.json").exists()


@pytest.mark.parametrize("kind", ["directory", "zip"])
@pytest.mark.parametrize("path", ["../image.png", "a/../image.png", "/tmp/image.png", "C:\\image.png", "\\\\host\\image.png"])
def test_sources_reject_traversal_and_absolute_paths(tmp_path, kind, path):
    source = evidence.DirectoryEvidenceSource(tmp_path) if kind == "directory" else evidence.ZipEvidenceSource(BytesIO(package({}, {})))
    with source, pytest.raises(evidence.UnsafeEvidencePath):
        source.read(path)


def test_sources_reject_escaping_symlinks(tmp_path):
    outside = tmp_path / "outside.png"
    outside.write_bytes(image_bytes())
    root = tmp_path / "source"
    root.mkdir()
    (root / "escape.png").symlink_to(outside)
    with pytest.raises(evidence.UnsafeEvidencePath):
        evidence.DirectoryEvidenceSource(root).read("escape.png")
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        link = ZipInfo("escape.png")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "../outside.png")
    with evidence.ZipEvidenceSource(BytesIO(output.getvalue())) as source, pytest.raises(evidence.UnsafeEvidencePath):
        source.read("escape.png")


@pytest.mark.parametrize("format,mime,extension", [("PNG", "image/png", "png"), ("JPEG", "image/jpeg", "jpg"), ("WEBP", "image/webp", "webp")])
def test_store_validates_metadata_and_deduplicates(context, asset_root, format, mime, extension):
    data = image_bytes(format)
    sha = hashlib.sha256(data).hexdigest()
    orphan = asset_root / sha[:2] / f"{sha}.{extension}"
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"interrupted, unregistered write")
    asset = evidence.store_asset(context.db, data, sha, None)
    repeated = evidence.store_asset(context.db, data, sha, None)
    assert repeated.sha256 == asset.sha256
    assert (asset.mime, asset.width, asset.height, asset.bytes) == (mime, 12, 18, len(data))
    assert asset.storage_path == f"{sha[:2]}/{sha}.{extension}"
    assert evidence.asset_path(asset).read_bytes() == data
    assert len(list(asset_root.rglob("*.*"))) == 1


def test_mismatch_and_invalid_images_never_stored(context, asset_root):
    data = image_bytes()
    with pytest.raises(evidence.EvidenceIntegrityError):
        evidence.store_asset(context.db, data, "0" * 64, None)
    for invalid in (b"not an image", image_bytes("GIF"), data[:40]):
        sha = hashlib.sha256(invalid).hexdigest()
        with pytest.raises(evidence.InvalidEvidenceImage):
            evidence.store_asset(context.db, invalid, sha, None)
        assert context.db.get(models.AuditEvidenceAsset, sha) is None
    assert not asset_root.exists()


def test_results_only_then_directory_ingest_deduplicates_across_venues_runs(context, tmp_path, asset_root):
    data = image_bytes()
    packet = report_for(data)
    packet["results"] += report_for(data, "venue-b")["results"]
    run = import_run(context, packet)
    assert run.targets[0].findings_json[0]["evidence"]["state"] == "not_attached"
    assert run.targets[0].findings_json[0]["evidence"]["items"][0]["asset"] == hashlib.sha256(data).hexdigest()
    assert not asset_root.exists()
    for result in packet["results"]:
        path = tmp_path / result["check_evidence"]["OV-001"]["items"][0]["file"]
        path.parent.mkdir(parents=True)
        path.write_bytes(data)
    source = evidence.DirectoryEvidenceSource(tmp_path)
    first = import_run(context, packet, source)
    second = import_run(context, packet, source)
    sha = hashlib.sha256(data).hexdigest()
    assert context.db.query(models.AuditEvidenceAsset).filter_by(sha256=sha).count() == 1
    assert context.db.get(models.AuditEvidenceAsset, sha).first_run_id == first.id
    assert second.targets[0].findings_json[0]["evidence"]["state"] == "localized"
    assert len(list(asset_root.rglob("*.png"))) == 1
    context.db.delete(first)
    context.db.flush()
    context.db.expire_all()
    assert context.db.get(models.AuditEvidenceAsset, sha).first_run_id is None


def test_mismatch_marks_finding_and_missing_file_marks_item(context, tmp_path, asset_root):
    data = image_bytes()
    packet = report_for(data)
    item = referenced(packet)
    path = tmp_path / item["file"]
    path.parent.mkdir(parents=True)
    path.write_bytes(image_bytes())
    run = import_run(context, packet, evidence.DirectoryEvidenceSource(tmp_path))
    finding = run.targets[0].findings_json[0]
    assert finding["evidence_integrity_error"] is True
    assert finding["evidence"]["items"][0]["integrity_error"] is True
    assert finding["evidence"]["state"] == "missing"
    assert context.db.get(models.AuditEvidenceAsset, item["sha256"]) is None
    assert not asset_root.exists()
    path.unlink()
    run = import_run(context, packet, evidence.DirectoryEvidenceSource(tmp_path))
    assert run.targets[0].findings_json[0]["evidence"]["items"][0]["state"] == "missing"


def test_import_zip_and_image_api_query_auth_cache(context):
    data = image_bytes()
    packet = report_for(data)
    item = referenced(packet)
    response = context.client.post("/api/audit-runs/h5", files={
        "file": ("results.json", json.dumps(packet)),
        "evidence": ("evidence.zip", package(packet, {item["file"]: data})),
    }, data={"name": "ZIP 导入", "spec_version_id": str(context.version.id)})
    assert response.status_code == 200, response.text
    path = "/api/audit-evidence/" + item["sha256"]
    context.client.headers.clear()
    assert context.client.get(path).status_code == 401
    assert context.client.get("/api/audit-evidence/" + "0" * 64, params={"token": context.token}).status_code == 404
    # An unregistered file on disk is never exposed.
    unregistered = hashlib.sha256(b"unknown").hexdigest()
    file = evidence.storage_root() / unregistered[:2] / (unregistered + ".png")
    file.parent.mkdir(exist_ok=True)
    file.write_bytes(data)
    assert context.client.get("/api/audit-evidence/" + unregistered, params={"token": context.token}).status_code == 404
    response = context.client.get(path, params={"token": context.token})
    assert response.status_code == 200 and response.content == data
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "private, max-age=31536000, immutable"


def test_reattach_endpoint_stats_persistence_and_idempotency(context):
    data = image_bytes()
    packet = report_for(data)
    missing = report_for(image_bytes(), "missing")
    corrupt = report_for(image_bytes(), "corrupt")
    packet["results"] += missing["results"] + corrupt["results"]
    run = import_run(context, packet)
    source = deepcopy(packet)
    source["results"] += report_for(data, "unknown")["results"]
    zip_bytes = package(source, {referenced(packet)["file"]: data, referenced(corrupt)["file"]: b"wrong bytes"})
    url = f"/api/audit-runs/{run.id}/evidence"
    response = context.client.post(url, files={"evidence": ("e.zip", zip_bytes)})
    assert response.status_code == 200, response.text
    assert response.json() == {"matched_targets": 3, "stored_assets": 1, "missing": 1, "integrity_errors": 1, "unmatched": 1}
    context.db.expire_all()
    target = context.db.query(models.AuditTarget).filter_by(run_id=run.id, business_key="venue-a").one()
    assert target.findings_json[0]["evidence"]["state"] == "localized"
    previous = deepcopy(target.findings_json)
    response = context.client.post(url, files={"evidence": ("e.zip", zip_bytes)})
    assert response.json() == {"matched_targets": 3, "stored_assets": 0, "missing": 1, "integrity_errors": 1, "unmatched": 1}
    context.db.refresh(target)
    assert target.findings_json == previous
    context.client.headers["Authorization"] = "Bearer " + create_access_token(context.viewer)
    assert context.client.post(url, files={"evidence": ("e.zip", zip_bytes)}).status_code == 403


def test_reattach_rejects_wrong_sha_and_business_key(context, asset_root):
    data = image_bytes()
    packet = report_for(data)
    run = import_run(context, packet)
    original = deepcopy(run.targets[0].findings_json)
    wrong = report_for(image_bytes())
    other = report_for(data, "other")
    wrong["results"] += other["results"]
    source = evidence.ZipEvidenceSource(BytesIO(package(wrong, {})))
    with source:
        stats = evidence.attach_run_evidence(context.db, run, source)
    assert stats == {"matched_targets": 0, "stored_assets": 0, "missing": 0, "integrity_errors": 0, "unmatched": 2}
    assert run.targets[0].findings_json == original and not asset_root.exists()


def test_legacy_backfill_requires_original_report_digest(context, asset_root):
    data = image_bytes()
    packet = report_for(data)
    run = import_run(context, packet)
    finding = deepcopy(run.targets[0].findings_json[0])
    finding["evidence"] = {"kind": "h5_report", "image_ids": []}
    run.targets[0].findings_json = [finding]
    wrong = deepcopy(packet)
    wrong["note"] = "not the originally imported report"
    with evidence.ZipEvidenceSource(BytesIO(package(wrong, {}))) as source:
        assert evidence.attach_run_evidence(context.db, run, source)["matched_targets"] == 0
    assert not asset_root.exists()
    with evidence.ZipEvidenceSource(BytesIO(package(packet, {referenced(packet)["file"]: data}))) as source:
        stats = evidence.attach_run_evidence(context.db, run, source)
    assert stats["matched_targets"] == 1 and stats["stored_assets"] == 1
    assert run.targets[0].findings_json[0]["evidence"]["items"][0]["role"] == "localized"


def test_backfill_script_dry_run_and_zip_without_report(context, tmp_path, asset_root, monkeypatch, capsys):
    data = image_bytes()
    packet = report_for(data)
    run = import_run(context, packet)
    before = deepcopy(run.targets[0].findings_json)
    (tmp_path / "results.json").write_text(json.dumps(packet))
    file = tmp_path / referenced(packet)["file"]
    file.parent.mkdir(parents=True)
    file.write_bytes(data)
    @contextmanager
    def session():
        yield context.db
    monkeypatch.setattr("app.database.SessionLocal", session)
    backfill.main(["--run", str(run.id), "--source", str(tmp_path), "--dry-run"])
    stats = json.loads(capsys.readouterr().out)
    assert stats == {"matched_targets": 1, "stored_assets": 1, "missing": 0, "integrity_errors": 0, "unmatched": 0}
    assert run.targets[0].findings_json == before and not asset_root.exists()
    assert context.db.get(models.AuditEvidenceAsset, referenced(packet)["sha256"]) is None
    zip_path = tmp_path / "evidence.zip"
    zip_path.write_bytes(package(packet, {referenced(packet)["file"]: data}, include_report=False))
    backfill.main(["--run", str(run.id), "--source", str(zip_path)])
    assert json.loads(capsys.readouterr().out) == stats
    context.db.expire_all()
    assert run.targets[0].findings_json[0]["evidence"]["state"] == "localized"


def test_invalid_zip_and_non_h5_run_rejected(context):
    run = import_run(context, report_for(image_bytes()))
    context.db.commit()
    url = f"/api/audit-runs/{run.id}/evidence"
    assert context.client.post(url, files={"evidence": ("bad.zip", b"not zip")}).status_code == 400
    run.carrier = "app"
    context.db.flush()
    response = context.client.post(url, files={"evidence": ("e.zip", package({}, {}, include_report=False))})
    assert response.status_code == 400


def test_app_preserves_pixel_bbox_from_inspection_and_legacy_shape():
    one, two = uuid4(), uuid4()
    checks = [{"rule_id": "OV-001", "clause": "框架", "status": "fail", "observed": "错位", "reason": "不符合",
               "evidence": [{"image_id": str(one), "bbox_px": [1, 2, 8, 10]}]},
              {"rule_id": "OV-001", "clause": "框架", "status": "fail", "observed": "错位", "reason": "不符合", "bbox": [2, 3, 9, 11]}]
    findings = workspace.aggregate_app_findings([SimpleNamespace(image_id=image_id, inspection_json={"checks": [check]})
                                                for image_id, check in zip((one, two), checks)])
    assert findings[0]["evidence"]["image_ids"] == [str(one), str(two)]
    assert findings[0]["evidence"]["items"] == [
        {"image_id": str(one), "marks": [{"kind": "rect", "bbox_px": [1, 2, 8, 10], "source": "model", "label": "框架"}]},
        {"image_id": str(two), "marks": [{"kind": "rect", "bbox_px": [2, 3, 9, 11], "source": "model", "label": "框架"}]},
    ]


def test_h5_job_ingest_stores_assets(h5_context, asset_root):
    job = wait_for(h5_context, create_job(h5_context, {"catalog_url": "https://yx.jd.com/activity-manage/test", "venue_ids": ["RA1"]}), "completed")
    run = h5_context.db.get(models.AuditRun, job.audit_run_id)
    items = [item for f in run.targets[0].findings_json for item in f["evidence"]["items"]]
    assert items and all(item["state"] in {"localized", "context"} for item in items)
    for item in items:
        asset = h5_context.db.get(models.AuditEvidenceAsset, item["asset"])
        assert asset is not None
        assert evidence.asset_path(asset).read_bytes()
    assert list(asset_root.rglob("*.png"))


def test_measurement_only_image_reference_is_ingested(context, tmp_path):
    data = image_bytes()
    packet = report_for(data)
    result = packet["results"][0]
    item = referenced(packet)
    result.pop("check_evidence")
    result["audit"]["visual_measurements"] = [{
        "id": "color", "rule_ids": ["OV-001"], "file": item["file"], "sha256": item["sha256"],
        "bbox_px": [1, 2, 5, 6], "screen": 1, "localization_method": "vlm_normalized_roi",
        "semantic_boundary_verified": True, "status": "measured", "result": {"dominant_hex": "#FFFFFF"},
    }]
    path = tmp_path / item["file"]
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    run = import_run(context, packet, evidence.DirectoryEvidenceSource(tmp_path))
    converted = run.targets[0].findings_json[0]["evidence"]
    assert converted["state"] == "context"
    assert converted["measurements"][0]["verified"] is False
    assert converted["measurements"][0]["bbox_px"] == [1, 2, 5, 6]
    assert context.db.get(models.AuditEvidenceAsset, item["sha256"]) is not None


def test_reattach_repaired_image_clears_integrity_errors(context):
    data = image_bytes()
    packet = report_for(data)
    item = referenced(packet)
    with evidence.ZipEvidenceSource(BytesIO(package(packet, {item["file"]: b"corrupt"}))) as source:
        run = import_run(context, packet, source)
    assert run.targets[0].findings_json[0]["evidence_integrity_error"] is True
    with evidence.ZipEvidenceSource(BytesIO(package(packet, {item["file"]: data}))) as source:
        assert evidence.attach_run_evidence(context.db, run, source)["stored_assets"] == 1
    finding = run.targets[0].findings_json[0]
    assert "evidence_integrity_error" not in finding
    assert "integrity_error" not in finding["evidence"]["items"][0]
    assert (finding["status"], finding["observed"], finding["reason"]) == ("fail", "错位", "顺序不对")


def test_unsafe_report_path_rejected_by_api(context, asset_root):
    packet = report_for(image_bytes())
    referenced(packet)["file"] = "../escape.png"
    response = context.client.post("/api/audit-runs/h5", files={
        "file": ("results.json", json.dumps(packet)), "evidence": ("e.zip", package(packet, {})),
    }, data={"name": "不安全路径", "spec_version_id": str(context.version.id)})
    assert response.status_code == 400
    assert not asset_root.exists()
