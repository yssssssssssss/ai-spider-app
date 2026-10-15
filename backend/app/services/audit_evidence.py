"""Content-addressed audit images and report conversion. Callers own transactions."""
from abc import ABC, abstractmethod
from copy import deepcopy
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import tempfile
from zipfile import BadZipFile, ZipFile

from PIL import Image, UnidentifiedImageError
from sqlalchemy.dialects.postgresql import insert

from app import models
from app.config import settings


class EvidenceIntegrityError(ValueError):
    """The bytes do not match the report's SHA-256."""


class InvalidEvidenceImage(ValueError):
    """Evidence must be a decodable PNG, JPEG or WebP image."""


class UnsafeEvidencePath(ValueError):
    pass


def storage_root():
    root = Path(settings.AUDIT_EVIDENCE_ROOT)
    return (root if root.is_absolute() else Path(settings.PROJECT_ROOT) / root).resolve()


def asset_path(asset):
    root = storage_root()
    path = (root / asset.storage_path).resolve()
    if not path.is_relative_to(root):
        raise UnsafeEvidencePath("Evidence storage path escapes root")
    return path


def _image_info(data):
    try:
        with Image.open(BytesIO(data)) as image:
            formats = {"PNG": ("image/png", "png"), "JPEG": ("image/jpeg", "jpg"), "WEBP": ("image/webp", "webp")}
            if image.format not in formats:
                raise InvalidEvidenceImage("Evidence must be PNG, JPEG or WebP")
            mime, ext = formats[image.format]
            width, height = image.size
            image.verify()
        with Image.open(BytesIO(data)) as image:
            image.load()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise InvalidEvidenceImage("Evidence is not a decodable image") from exc
    return mime, ext, width, height


def store_asset(db, data: bytes, expected_sha256, run_id):
    digest = hashlib.sha256(data).hexdigest()
    if not isinstance(expected_sha256, str) or digest != expected_sha256.lower():
        raise EvidenceIntegrityError("Evidence SHA-256 does not match report")
    mime, ext, width, height = _image_info(data)
    relative = f"{digest[:2]}/{digest}.{ext}"
    path = storage_root() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or db.get(models.AuditEvidenceAsset, digest) is None:
        # A reader can only see the complete file, including during concurrent imports.
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as output:
                temporary = output.name
                output.write(data)
            os.replace(temporary, path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)
    db.execute(insert(models.AuditEvidenceAsset).values(
        sha256=digest, mime=mime, width=width, height=height, bytes=len(data),
        storage_path=relative, first_run_id=run_id,
    ).on_conflict_do_nothing(index_elements=["sha256"]))
    return db.get(models.AuditEvidenceAsset, digest)


def _relative_path(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise UnsafeEvidencePath("Invalid evidence path")
    value = value.replace("\\", "/")
    path = PurePosixPath(value)
    if path.is_absolute() or PureWindowsPath(value).drive or ".." in path.parts or str(path) == ".":
        raise UnsafeEvidencePath("Evidence path must be relative without '..'")
    return path.as_posix()


class EvidenceSource(ABC):
    """Read only report-referenced paths; never enumerate or extract images."""

    @abstractmethod
    def read(self, path: str) -> bytes:
        pass

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class DirectoryEvidenceSource(EvidenceSource):
    def __init__(self, root):
        self.root = Path(root).resolve()

    def read(self, path):
        file = (self.root / _relative_path(path)).resolve()
        if not file.is_relative_to(self.root):
            raise UnsafeEvidencePath("Evidence symlink escapes source root")
        if not file.is_file():
            raise FileNotFoundError(path)
        return file.read_bytes()


class ZipEvidenceSource(EvidenceSource):
    def __init__(self, file):
        try:
            self.archive = ZipFile(file)
        except BadZipFile as exc:
            raise ValueError("Evidence package must be a zip file") from exc

    def read(self, path):
        name = _relative_path(path)
        try:
            member = self.archive.getinfo(name)
        except KeyError as exc:
            raise FileNotFoundError(name) from exc
        if stat.S_ISLNK(member.external_attr >> 16):
            raise UnsafeEvidencePath("Zip evidence may not be a symlink")
        if member.is_dir():
            raise FileNotFoundError(name)
        try:
            return self.archive.read(member)
        except BadZipFile as exc:
            raise EvidenceIntegrityError("Corrupt zip evidence member") from exc

    def close(self):
        self.archive.close()


def _check(result, rule_id):
    return next((c for c in (result.get("audit") or {}).get("checks", []) if c["rule_id"] == rule_id), {})


def _mark_source(source, check):
    if source in {"dom", "live_h5_dom", "live_h5_dom_spacing"}:
        return "dom"
    if source == "pixel" or check.get("method") == "pixel":
        return "pixel"
    return "model"


def _item(raw, result, check):
    file = raw.get("file", "")
    captured = next((s for s in (result.get("capture") or {}).get("screens", []) if s.get("file") == file), {})
    screen = raw.get("screen")
    if screen is None:
        screen = captured.get("number")
    if screen is None:
        match = re.search(r"screen-(\d+)", file)
        screen = int(match[1]) if match else 1
    role = "localized" if raw.get("status") == "localized" else "context"
    return {
        "asset": raw.get("sha256"), "file": file, "screen": screen,
        "image_size": deepcopy(raw.get("image_size") or ([captured["width"], captured["height"]]
                                                        if "width" in captured and "height" in captured else None)),
        "crop_px": deepcopy(raw.get("crop_px")),
        "marks": [{**deepcopy(mark), "source": _mark_source(raw.get("source"), check)}
                  for mark in raw.get("marks", [])],
        "role": role, "label": raw.get("label", ""), "state": role,
    }


def _expected_range(comparison):
    if "min_px" in comparison and "max_px" in comparison:
        return f"{comparison['min_px']}–{comparison['max_px']}px"
    return None


def _measurement(raw, *, spacing=False):
    measurement = deepcopy(raw)
    result = raw.get("result") or {}
    edge = raw.get("edge_distance") or {}
    comparison = raw.get("range_comparison") or raw.get("edge_length_comparison") or result.get("comparison") or {}
    distance = spacing or bool(edge) or raw.get("kind") == "distance"
    semantic = raw.get("semantic_boundary_verified", edge.get("semantic_boundary_verified",
                                                              comparison.get("semantic_boundary_verified")))
    verified = (raw.get("verified") is True or semantic is True) and semantic is not False
    verified = verified and not str(raw.get("localization_method", "")).startswith("vlm")
    measured = raw.get("measurement_status", raw.get("status")) == "measured"
    verdict = raw.get("verdict", raw.get("audit_status"))
    if verdict is None and "all_pixels_match" in comparison:
        verdict = "pass" if comparison["all_pixels_match"] else "fail"
    if verdict is None:
        verdict = {"inside_range": "pass", "within_range": "pass", "outside_range": "fail"}.get(comparison.get("status"), "uncertain")
    if distance:
        value = raw.get("distance_css_px") if spacing else edge.get("distance_px")
        unit, expected = "css_px" if spacing else "px", _expected_range(comparison)
    else:
        value, unit, expected = result.get("dominant_hex"), "hex", comparison.get("expected_hex")
    measurement.update({
        "id": raw.get("id", "OV-009-spacing"), "kind": raw.get("kind", "distance" if distance else "color"),
        "value": raw.get("value", value), "unit": raw.get("unit", unit), "expected": raw.get("expected", expected),
        "verdict": verdict, "source": "dom" if spacing or raw.get("source") == "dom" else "pixel",
        "verified": bool(verified and measured),
        "asset": raw.get("screenshot_sha256") if spacing else raw.get("sha256"),
        "file": raw.get("screenshot_file") if spacing else raw.get("file"),
    })
    return measurement


def convert_h5_evidence(result, rule_id):
    """Pure report-to-v2 conversion; candidates remain context, never verified localization."""
    check = _check(result, rule_id)
    raw = (result.get("check_evidence") or {}).get(rule_id) or {}
    items = [_item(item, result, check) for item in raw.get("items", [])]
    audit = result.get("audit") or {}
    measurements = [_measurement(m) for m in audit.get("visual_measurements", []) if rule_id in m.get("rule_ids", [])]
    if rule_id == "OV-009" and audit.get("spacing_review"):
        measurements.append(_measurement(audit["spacing_review"], spacing=True))
    # Some producers reference an image only from the measurement.
    for measurement in measurements:
        if measurement.get("asset") and measurement.get("file") and not any(
                i["asset"] == measurement["asset"] and i["file"] == measurement["file"] for i in items):
            items.append(_item({"file": measurement["file"], "sha256": measurement["asset"],
                                "screen": measurement.get("screen"), "status": "context",
                                "label": measurement.get("label", "")}, result, check))
    state = raw.get("state", "context" if items else "missing")
    return {"kind": "h5_report", "image_ids": [], "items": items, "measurements": measurements,
            "state": "context" if state == "candidate" else state}


def h5_finding_metadata(result, rule_id):
    check = _check(result, rule_id)
    method = check.get("method", "model")
    if method not in {"model", "dom", "pixel", "hybrid"}:
        method = "dom" if method.startswith("live_h5_dom") else "pixel" if "pixel" in method else "model"
    # Auxiliary measurements do not establish how the final check was decided.
    metadata = {"method": method}
    if "model_status" in check:
        metadata["model_status"] = check["model_status"]
    return metadata


def mark_not_attached(evidence):
    evidence["state"] = "not_attached"
    for item in evidence["items"]:
        item["state"] = "not_attached"


def _attach_items(db, finding, source, run_id, stats, cache, new_assets, *, dry_run=False):
    evidence = finding["evidence"]
    for item in evidence["items"]:
        key = (item.get("file"), item.get("asset"))
        if key not in cache:
            try:
                if not key[0]:
                    raise FileNotFoundError("No referenced file")
                data = source.read(key[0])
                existing = db.get(models.AuditEvidenceAsset, key[1]) if key[1] else None
                if dry_run:
                    if hashlib.sha256(data).hexdigest() != key[1]:
                        raise EvidenceIntegrityError("Evidence SHA-256 does not match report")
                    _image_info(data)
                else:
                    store_asset(db, data, key[1], run_id)
                if existing is None and key[1] not in new_assets:
                    stats["stored_assets"] += 1
                    new_assets.add(key[1])
                cache[key] = "attached"
            except FileNotFoundError:
                stats["missing"] += 1
                cache[key] = "missing"
            except (EvidenceIntegrityError, InvalidEvidenceImage):
                stats["integrity_errors"] += 1
                cache[key] = "integrity_error"
        outcome = cache[key]
        item.pop("integrity_error", None)
        item["state"] = item["role"] if outcome == "attached" else "missing"
        if outcome == "integrity_error":
            item["integrity_error"] = True
    evidence["state"] = next((state for state in ("localized", "context")
                              if any(i["state"] == state for i in evidence["items"])), "missing")
    if any(i.get("integrity_error") for i in evidence["items"]):
        finding["evidence_integrity_error"] = True
    else:
        finding.pop("evidence_integrity_error", None)


def _stats():
    # File errors count unique (path, SHA) references; stored_assets counts new rows.
    return dict(matched_targets=0, stored_assets=0, missing=0, integrity_errors=0, unmatched=0)


def attach_run_evidence(db, run, source, *, dry_run=False):
    """Attach by business key + rule + SHA. A matching report digest authorizes legacy rows.

    A package may omit results.json if stored v2 findings already retain image references.
    Unmatched counts source venues without a target, plus incompatible finding references.
    Dry runs report would-be new assets without mutating findings, rows or storage.
    """
    if run.carrier != "h5":
        raise ValueError("Evidence packages are only supported for H5 runs")
    stats, cache, new_assets = _stats(), {}, set()
    try:
        raw_report = source.read("results.json")
    except FileNotFoundError:
        raw_report = None
    reports = None
    trusted_legacy = False
    if raw_report is not None:
        try:
            packet = json.loads(raw_report)
            reports = {str(r["venue"]["venue_id"]): r for r in packet["results"]}
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError("Invalid evidence results.json") from exc
        trusted_legacy = hashlib.sha256(raw_report).hexdigest() == (run.source_ref_json or {}).get("sha256")
        keys = {target.business_key for target in run.targets}
        stats["unmatched"] = len(reports.keys() - keys)
    for target in run.targets:
        result = reports.get(target.business_key) if reports is not None else None
        if reports is not None and result is None:
            continue
        findings = deepcopy(target.findings_json)
        matched = False
        for finding in findings:
            current = finding.get("evidence") or {}
            if result is None:
                if not current.get("items"):
                    continue
                evidence = current
            else:
                evidence = convert_h5_evidence(result, finding["rule_id"])
                allowed = {i.get("asset") for i in current.get("items", []) if i.get("asset")}
                if not allowed and not trusted_legacy:
                    stats["unmatched"] += len(evidence["items"])
                    continue
                incompatible = [i for i in evidence["items"] if allowed and i.get("asset") not in allowed]
                stats["unmatched"] += len(incompatible)
                if incompatible:
                    # Do not replace a finding with a partial, different report.
                    continue
            if not evidence.get("items"):
                continue
            finding["evidence"] = evidence
            if result is not None:
                finding.update(h5_finding_metadata(result, finding["rule_id"]))
            _attach_items(db, finding, source, run.id, stats, cache, new_assets, dry_run=dry_run)
            matched = True
        if matched:
            stats["matched_targets"] += 1
            if not dry_run:
                target.findings_json = findings
    return stats


def ingest_run_evidence(db, run, source):
    stats, cache, new_assets = _stats(), {}, set()
    for target in run.targets:
        findings = deepcopy(target.findings_json)
        for finding in findings:
            _attach_items(db, finding, source, run.id, stats, cache, new_assets)
        target.findings_json = findings
    return stats
