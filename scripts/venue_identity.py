"""Verify preview entries from QR pixels, independently of copied venue metadata.

The standalone venue tools require opencv-python-headless for QR decoding.
"""
import argparse
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit


def preview_identity(url):
    parsed = urlsplit(url)
    match = re.fullmatch(r"/service/preview/mall/active/([^/]+)/(\d+)", parsed.path)
    page_ids = parse_qs(parsed.query).get("pageId", [])
    if parsed.scheme != "https" or parsed.hostname != "babelserv.m.jd.com" or not match or len(page_ids) != 1:
        raise ValueError("invalid venue preview URL")
    return (*match.groups(), page_ids[0])


@lru_cache(maxsize=1024)
def _decode_qr_bytes(payload):
    import cv2
    import numpy as np

    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("invalid QR image")
    detector = cv2.QRCodeDetector()
    # React's QR canvas has no quiet zone. Padding also handles dense small codes.
    for border, scale in ((12, 4), (10, 2), (30, 6), (70, 12)):
        padded = cv2.copyMakeBorder(image, border, border, border, border,
                                   cv2.BORDER_CONSTANT, value=(255, 255, 255))
        enlarged = cv2.resize(padded, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
        url, _, _ = detector.detectAndDecode(enlarged)
        if url:
            preview_identity(url)
            return url
    raise ValueError("QR preview URL cannot be decoded")


def decoded_entry(root, venue):
    qr_file = venue.get("qr_file")
    if not qr_file:
        raise ValueError(f"missing QR evidence: {venue['record_id']}")
    root = Path(root).resolve()
    path = (root / qr_file).resolve()
    if not path.is_relative_to(root):
        raise ValueError("QR evidence escapes report directory")
    payload = path.read_bytes()
    return {"venue_id": venue["venue_id"], "project_id": venue["project_id"],
            "qr_file": qr_file, "qr_sha256": hashlib.sha256(payload).hexdigest(),
            "preview_url": _decode_qr_bytes(payload)}


def verify_venue_identity(root, venue):
    entry = decoded_entry(root, venue)
    if entry["preview_url"] != venue.get("preview_url"):
        raise ValueError(f"QR differs from recorded preview URL: {venue['record_id']}")
    official = venue.get("official_url")
    official_activity = re.search(r"/active/([^/]+)/", official or "")
    conflict = bool(official and (not official_activity or
                    official_activity.group(1) != preview_identity(entry["preview_url"])[0]))
    entry["status"] = "official_entry_conflict" if conflict else "verified_entry"
    return entry


def capture_fingerprint(capture):
    value = {"venue": capture["venue"], "screens": capture["screens"],
             "navigation_url": capture.get("navigation_url")}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def verify_capture_identity(root, venue, capture, page_state=None):
    entry = verify_venue_identity(root, venue)
    if capture["venue"] != venue:
        raise ValueError(f"capture venue identity differs: {venue['record_id']}")
    navigation = capture.get("navigation_url")
    if capture.get("navigation_status") == "unverified_redirect":
        if capture.get("requested_url") != entry["preview_url"] or page_state == "ready":
            raise ValueError(f"unverified navigation cannot receive a venue verdict: {venue['record_id']}")
        entry["status"] = "unverified_redirect"
        return entry
    if navigation:
        parsed = urlsplit(navigation)
        login = parsed.scheme == "https" and parsed.hostname == "plogin.m.jd.com" and parsed.path in {"/login/login", "/login/nopassword"}
        target = parse_qs(parsed.query).get("returnurl", [None])[0] if login else navigation
        target_url = urlsplit(target or "")
        public_match = re.fullmatch(r"/mall/active/([^/]+)/index.html", target_url.path)
        public_login = login and target_url.scheme == "https" and target_url.hostname == "pro.m.jd.com" and public_match
        matches = (public_match.group(1) == preview_identity(entry["preview_url"])[0] if public_login else
                   bool(target) and preview_identity(target) == preview_identity(entry["preview_url"]))
        if not matches:
            raise ValueError(f"capture navigation reached another venue: {venue['record_id']}")
        if login and page_state == "ready":
            raise ValueError(f"login navigation cannot receive a ready verdict: {venue['record_id']}")
        if login:
            entry["status"] = "login_required"
    if entry["status"] == "official_entry_conflict" and page_state == "ready":
        raise ValueError(f"official entry conflicts with QR preview: {venue['record_id']}")
    return entry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--repair-links", action="store_true", help="replace recorded links with decoded QR entries")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    path = root / "catalog.json"
    catalog = json.loads(path.read_text())
    entries, changed = [], []
    ids = [v["venue_id"] for v in catalog["venues"]]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate venue IDs")
    for venue in catalog["venues"]:
        decoded = decoded_entry(root, venue)
        if args.repair_links:
            if venue.get("preview_url") != decoded["preview_url"]:
                changed.append(venue["record_id"])
            venue["preview_url"] = decoded["preview_url"]
            venue["preview_url_method"] = "decoded_qr_pixels"
        entries.append({"record_id": venue["record_id"], **verify_venue_identity(root, venue)})
    if args.repair_links:
        backup = root / "catalog.before-qr-repair.json"
        if not backup.exists():
            backup.write_bytes(path.read_bytes())
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(path)
    (root / "identity-verification.json").write_text(json.dumps({"entries": entries}, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"verified": len(entries), "corrected_links": len(changed), "record_ids": changed,
                      "official_entry_conflicts": sum(e["status"] == "official_entry_conflict" for e in entries)}))


if __name__ == "__main__":
    main()
