"""Pixel evidence must not erase missing calibration, unavailable pages, or source conflicts."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location("venue_reaudit", ROOT / "scripts/rerun_venue_audit.py")
replay = importlib.util.module_from_spec(loader)
loader.loader.exec_module(replay)


class VenueReauditTests(unittest.TestCase):
    def setUp(self):
        self.rules = [{"id": f"OV-{index:03}", "title": "rule", "strength": "conditional_mandatory",
                       "expected": "expected", "sources": [{"page": 1}], "remediation": "review"}
                      for index in range(1, 24)]
        self.spec = {"rules": self.rules, "version": "1", "title": "spec", "source": {"sha256": "source-hash"}}
        self.capture = {"venue": {"venue_id": "venue-1"}, "screens": [
            {"file": "screen-1.png", "width": 390, "height": 844, "sha256": "first"},
            {"file": "screen-2.png", "width": 390, "height": 844, "sha256": "second"}]}
        self.previous = {"checks": [{"rule_id": r["id"], "status": "uncertain"} for r in self.rules]}
        self.reply = replay.Reply(page_state="ready", overview="venue", page_warnings=[], visual_regions=[],
                                  checks=[replay.Check(rule_id=r["id"], status="pass", observed="visible", reason="observed",
                                                       evidence=[replay.Evidence(screen=1, bbox_norm=[0, 0, 1000, 1000])])
                                          for r in self.rules])

    def patch(self, identity, bbox, color="#FFFFFF", clear=True):
        return {"id": identity, "role": "feeds_background", "screen": 1, "status": "measured" if clear else "unverified_region_context",
                "context_clear": clear, "label": "background", "file": "screen-1.png", "sha256": "first", "bbox_px": bbox,
                "rule_ids": ["OV-010", "OV-011", "OV-012"],
                "result": {"dominant_hex": color, "dominant_ratio": 1, "uniform_opaque_region": True},
                "solid_sample": {"bbox_px": bbox, "dominant_hex": color, "uniform_opaque_region": True}}

    def test_two_white_samples_resolve_only_conditional_background_rules(self):
        patches = [self.patch("left", [0, 500, 3, 503]), self.patch("right", [380, 500, 383, 503])]
        report = replay.normalize(self.reply, self.capture, self.spec, patches, [], self.previous)
        checks = {c["rule_id"]: c for c in report["checks"]}
        self.assertEqual(checks["OV-011"]["status"], "not_applicable")
        self.assertEqual(checks["OV-012"]["status"], "not_applicable")
        self.assertEqual(checks["OV-011"]["change_source"], "pixel_verified_applicability")
        self.assertEqual(checks["OV-009"]["status"], "uncertain")
        self.assertEqual(checks["OV-010"]["status"], "uncertain")
        self.assertEqual(checks["OV-008"]["status"], "uncertain")

    def test_single_duplicate_or_unverified_patch_cannot_confirm_background(self):
        first = self.patch("left", [0, 500, 3, 503])
        for patches in ([first], [first, self.patch("duplicate", [0, 500, 3, 503])],
                        [first, self.patch("unclear", [380, 500, 383, 503], clear=False)]):
            with self.subTest(patches=patches):
                self.assertEqual(replay.background_class(patches), "unknown")
        self.assertEqual(replay.background_class([first, self.patch("pink", [380, 500, 383, 503], "#E999D0")]), "mixed")

    def test_spatially_distinct_solid_samples_can_share_a_clear_background_region(self):
        region = self.patch("left-strip", [0, 500, 3, 700])
        region["solid_samples"] = [
            {"bbox_px": [0, 500, 3, 503], "dominant_hex": "#FFFFFF"},
            {"bbox_px": [0, 650, 3, 653], "dominant_hex": "#FFFFFF"}]
        self.assertEqual(replay.background_class([region]), "white")

    def test_unavailable_page_cannot_pass_even_with_white_pixel_samples(self):
        self.reply.page_state = "error"
        patches = [self.patch("left", [0, 500, 3, 503]), self.patch("right", [380, 500, 383, 503])]
        report = replay.normalize(self.reply, self.capture, self.spec, patches, [], self.previous)
        self.assertEqual(report["summary"], {"uncertain": 23})
        self.assertEqual(report["mandatory_fail_count"], 0)

    def test_positive_margin_evidence_does_not_create_an_unsupported_minimum(self):
        patches = [self.patch("left", [0, 500, 3, 503], "#E999D0"), self.patch("right", [380, 500, 383, 503], "#E999D0")]
        margin = {"id": "margin", "role": "cart_margin", "screen": 1, "status": "measured", "label": "cart margin",
                  "rule_ids": ["OV-012"], "file": "screen-1.png", "sha256": "first", "bbox_px": [350, 600, 382, 630],
                  "result": {"bands": [{"length_px": 8, "bbox_px": [374, 600, 382, 630]}]}}
        check = next(c for c in self.reply.checks if c.rule_id == "OV-012")
        check.status, check.observed, check.reason = "fail", "加购靠近右缘", "边距过小"
        report = replay.normalize(self.reply, self.capture, self.spec, patches + [margin], [], self.previous)
        updated = next(c for c in report["checks"] if c["rule_id"] == "OV-012")
        self.assertEqual(updated["status"], "uncertain")
        self.assertEqual(updated["change_source"], "pixel_evidence_conflict")

    def test_summarized_floor_error_prevents_a_design_height_failure(self):
        self.reply.page_warnings = ["首屏楼层3-楼层间隔异常：关联楼层被过滤"]
        check = next(c for c in self.reply.checks if c.rule_id == "OV-005")
        check.status, check.observed, check.reason = "fail", "首屏商品被截断", "首屏商品未完整显示"
        report = replay.normalize(self.reply, self.capture, self.spec, [], [], self.previous)
        updated = next(c for c in report["checks"] if c["rule_id"] == "OV-005")
        self.assertEqual(updated["status"], "uncertain")
        self.assertIn("预览异常", updated["reason"])

    def test_missing_rules_or_duplicate_region_ids_fail_validation(self):
        shortened = self.reply.model_copy(deep=True)
        shortened.checks.pop()
        with self.assertRaises(ValueError):
            replay.normalize(shortened, self.capture, self.spec, [], [], self.previous)
        region = replay.Region(id="duplicate", role="feeds_background", screen=1, bbox_norm=[0, 0, 10, 10], label="background", context_clear=True)
        self.reply.visual_regions = [region, region]
        with self.assertRaises(ValueError):
            replay.normalize(self.reply, self.capture, self.spec, [], [], self.previous)


if __name__ == "__main__":
    unittest.main()
