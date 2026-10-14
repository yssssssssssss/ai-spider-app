"""A matching metadata object must not hide a stale other-venue preview URL."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import cv2
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location("venue_replay", ROOT / "scripts/rerun_venue_audit.py")
replay = importlib.util.module_from_spec(loader)
loader.loader.exec_module(replay)


class VenueIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "source"
        self.output = Path(self.temp.name) / "replay"
        self.source.mkdir()
        self.url = "https://babelserv.m.jd.com/service/preview/mall/active/CorrectVenue/1791734400000?source=preview&pageId=123"
        self.wrong_url = self.url.replace("CorrectVenue", "PreviousPageVenue").replace("pageId=123", "pageId=456")
        self.venue = {"venue_name": "target", "venue_id": "RA1", "project_id": "001",
                      "record_id": "p01-r01-RA1", "qr_file": "qrcodes/target.png",
                      "official_url": None, "preview_url": self.url}
        qr_path = self.source / self.venue["qr_file"]
        qr_path.parent.mkdir()
        cv2.imwrite(str(qr_path), cv2.QRCodeEncoder_create().encode(self.url))
        folder = self.source / "venues" / self.venue["record_id"]
        folder.mkdir(parents=True)
        self.capture = {"venue": self.venue, "screens": []}
        for number in (1, 2):
            name = f"venues/{self.venue['record_id']}/screen-{number}.png"
            Image.new("RGB", (390, 844), "white").save(self.source / name)
            self.capture["screens"].append({"number": number, "file": name, "width": 390, "height": 844,
                                            "sha256": hashlib.sha256((self.source / name).read_bytes()).hexdigest()})
        (self.source / "specification").mkdir()
        self.write("specification/walkthrough.json", {"source": {"sha256": "spec"}})
        self.persist()

    def write(self, name, value):
        (self.source / name).write_text(json.dumps(value))

    def persist(self):
        self.write("catalog.json", {"venues": [self.venue]})
        self.write(f"venues/{self.venue['record_id']}/capture.json", self.capture)
        self.write("results.json", {"results": [{"venue": self.venue, "status": "partial_inspection",
                                                  "audit": {"page_state": "ready", "checks": []}}]})

    def test_stale_url_is_rejected_even_when_all_identity_objects_and_hashes_match(self):
        self.venue["preview_url"] = self.wrong_url
        self.persist()
        with self.assertRaisesRegex(ValueError, "QR.*preview"):
            replay.prepare(self.source, self.output)
        self.assertFalse((self.output / "catalog.json").exists())

    def test_correct_qr_is_accepted_and_copied_to_replay(self):
        replay.prepare(self.source, self.output)
        self.assertTrue((self.output / self.venue["qr_file"]).exists())

    def test_unverified_redirect_to_another_venue_is_rejected(self):
        from scripts.venue_identity import verify_capture_identity
        self.capture["navigation_url"] = self.wrong_url
        with self.assertRaisesRegex(ValueError, "navigation"):
            verify_capture_identity(self.source, self.venue, self.capture)

    def test_conflicting_official_entry_cannot_receive_a_ready_verdict(self):
        from scripts.venue_identity import verify_capture_identity
        self.venue["official_url"] = "https://pro.m.jd.com/mall/active/AnotherVenue/index.html"
        with self.assertRaisesRegex(ValueError, "official"):
            verify_capture_identity(self.source, self.venue, self.capture, page_state="ready")
        self.assertEqual(verify_capture_identity(self.source, self.venue, self.capture, page_state="unknown")["status"],
                         "official_entry_conflict")

    def test_login_return_url_is_bound_to_the_target_and_never_treated_as_ready(self):
        from urllib.parse import quote
        from scripts.venue_identity import verify_capture_identity
        self.capture["navigation_url"] = "https://plogin.m.jd.com/login/login?returnurl=" + quote(self.url, safe="")
        self.assertEqual(verify_capture_identity(self.source, self.venue, self.capture, "error")["status"], "login_required")

        with self.assertRaisesRegex(ValueError, "login"):
            verify_capture_identity(self.source, self.venue, self.capture, "ready")
        self.capture["navigation_url"] = "https://plogin.m.jd.com/login/login?returnurl=" + quote(self.wrong_url, safe="")
        with self.assertRaises(ValueError):
            verify_capture_identity(self.source, self.venue, self.capture, "error")
        self.capture["navigation_url"] = "https://plogin.m.jd.com/login/login?returnurl=" + quote("https://pro.m.jd.com/mall/active/CorrectVenue/index.html", safe="")
        self.assertEqual(verify_capture_identity(self.source, self.venue, self.capture, "error")["status"], "login_required")

    def test_an_unexpected_redirect_is_quarantined_and_cannot_be_ready(self):
        from scripts.venue_identity import verify_capture_identity
        self.capture.update(navigation_url=self.wrong_url, requested_url=self.url, navigation_status="unverified_redirect")
        self.assertEqual(verify_capture_identity(self.source, self.venue, self.capture, "unknown")["status"], "unverified_redirect")
        with self.assertRaisesRegex(ValueError, "unverified navigation"):
            verify_capture_identity(self.source, self.venue, self.capture, "ready")


if __name__ == "__main__":
    unittest.main()
