"""Exercise user policy boundaries independently of the model's proposed verdicts."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
loader = importlib.util.spec_from_file_location("h5_replay", ROOT / "scripts/rerun_venue_audit.py")
replay = importlib.util.module_from_spec(loader)
loader.loader.exec_module(replay)


class H5PolicyTests(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads((ROOT / "docs/specifications/official-venue-review/h5-v2.json").read_text())
        self.capture = {"venue": {"venue_id": "v"}, "screens": [
            {"file": "one.png", "width": 390, "height": 844, "sha256": "one", "scroll_y": 0},
            {"file": "two.png", "width": 390, "height": 844, "sha256": "two", "scroll_y": 844}]}
        self.previous = {"checks": [{"rule_id": r["id"], "status": "uncertain"} for r in self.spec["rules"]]}
        self.facts = replay.H5Facts(hero_complete=True, hero_evidence=self.e([0, 50, 1000, 300]),
            main_title_complete=True, texts=[replay.HeroText(screen=1, bbox_norm=[10, 100, 600, 200],
                text="好物上新", role="main_title", readable=True)], pure_product_hero=True,
            product_count=1, products=[self.e([650, 80, 900, 250])], person_count=0, people=[],
            countdown_present=False, countdown_evidence=None, first_screen_assessment_complete=True,
            complete_first_screen_feeds_products=[self.e([20, 500, 980, 800])])
        self.reply = replay.Reply(page_state="ready", overview="h5", page_warnings=[], facts=self.facts, visual_regions=[],
            checks=[replay.Check(rule_id=r["id"], status="pass", observed="visible", reason="evidence",
                evidence=[self.e([0, 0, 1000, 1000])]) for r in self.spec["rules"] if r["enabled"]])

    def e(self, box):
        return replay.Evidence(screen=1, bbox_norm=box)

    def checks(self):
        audit = replay.normalize(self.reply, self.capture, self.spec, [], [], self.previous)
        return audit, {c["rule_id"]: c for c in audit["checks"]}

    def test_inactive_rules_are_preserved_and_not_uncertain(self):
        audit, checks = self.checks()
        self.assertEqual(len(checks), 23)
        self.assertEqual(audit["active_rule_count"], 14)
        self.assertEqual(audit["summary"]["disabled"], 9)
        self.assertEqual(checks["OV-007"]["status"], "pass")
        self.assertEqual(checks["OV-006"]["status"], "disabled")

    def test_optional_components_remain_not_applicable_when_absent(self):
        for check in self.reply.checks:
            if check.rule_id in {"OV-002", "OV-003", "OV-004"}:
                check.status, check.reason = "not_applicable", "完整前置区域未发现该可选组件"
        _, checks = self.checks()
        for rid in ("OV-002", "OV-003", "OV-004", "OV-016", "OV-018"):
            self.assertEqual(checks[rid]["status"], "not_applicable")

    def test_disabling_navigation_retains_rule_and_removes_old_failure(self):
        self.spec = json.loads((ROOT / "docs/specifications/official-venue-review/h5-v3.json").read_text())
        self.reply.checks = [c for c in self.reply.checks if c.rule_id != "OV-007"]
        next(c for c in self.previous["checks"] if c["rule_id"] == "OV-007")["status"] = "fail"
        audit, checks = self.checks()
        self.assertEqual(len(checks), 23)
        self.assertEqual(audit["active_rule_count"], 13)
        self.assertEqual(audit["summary"]["disabled"], 10)
        self.assertEqual(checks["OV-007"]["status"], "disabled")
        self.assertEqual(checks["OV-007"]["previous_status"], "fail")
        self.assertEqual(checks["OV-007"]["evidence"], [])
        self.assertEqual(audit["mandatory_fail_count"], 0)
        self.assertIn("10项未激活", audit["limits"])

    def test_new_spacing_policy_does_not_pass_approximate_model_boundaries(self):
        self.spec = json.loads((ROOT / "docs/specifications/official-venue-review/h5-v5.json").read_text())
        self.reply.checks = [c for c in self.reply.checks if c.rule_id != "OV-007"]
        _, checks = self.checks()
        self.assertEqual(checks["OV-009"]["status"], "uncertain")
        self.assertIn("7–9px", checks["OV-009"]["observed"])
        self.reply.page_warnings = ["首屏存在灰色示意楼层"]
        next(c for c in self.reply.checks if c.rule_id == "OV-009").status = "not_applicable"
        _, checks = self.checks()
        self.assertEqual(checks["OV-009"]["status"], "not_applicable")

    def test_title_count_excludes_brand_and_whitespace(self):
        self.facts.texts[0].text = "好 物\n上新"
        self.facts.texts.append(replay.HeroText(screen=1, bbox_norm=[600, 200, 900, 240],
            text="很长的品牌利益点不属于主标题", role="brand", readable=True))
        _, checks = self.checks()
        self.assertEqual(checks["OV-017"]["facts"]["character_count"], 4)
        self.assertEqual(checks["OV-017"]["status"], "pass")
        self.facts.texts[0].text = "123456789"
        _, checks = self.checks()
        self.assertEqual(checks["OV-017"]["status"], "fail")

    def test_bad_title_boundary_or_unreadable_text_is_uncertain(self):
        self.facts.texts[0].bbox_norm = [0, 0, 1000, 30]
        _, checks = self.checks()
        self.assertEqual(checks["OV-017"]["status"], "uncertain")
        self.facts.texts[0].bbox_norm, self.facts.texts[0].readable = [10, 100, 600, 200], False
        _, checks = self.checks()
        self.assertEqual(checks["OV-017"]["status"], "uncertain")

    def test_incomplete_facts_do_not_repeat_an_unverified_model_count(self):
        self.facts.product_count = None
        self.facts.main_title_complete = False
        for c in self.reply.checks:
            if c.rule_id in {"OV-015", "OV-017"}:
                c.observed = "模型未经验证的计数99"
        _, checks = self.checks()
        for rid in ("OV-015", "OV-017"):
            self.assertEqual(checks[rid]["status"], "uncertain")
            self.assertNotIn("99", checks[rid]["observed"])

    def test_person_and_product_counts_require_each_object_evidence(self):
        self.facts.person_count = 2
        self.facts.people = [self.e([20, 80, 200, 250]), self.e([300, 80, 450, 250])]
        _, checks = self.checks()
        self.assertEqual(checks["OV-016"]["status"], "fail")
        self.facts.product_count = None
        _, checks = self.checks()
        self.assertEqual(checks["OV-015"]["status"], "uncertain")

    def test_countdown_position_uses_same_hero_title_boundary(self):
        self.facts.countdown_present = True
        self.facts.countdown_evidence = self.e([10, 210, 600, 240])
        _, checks = self.checks()
        self.assertEqual(checks["OV-018"]["status"], "pass")
        self.facts.countdown_evidence = self.e([10, 60, 600, 90])
        _, checks = self.checks()
        self.assertEqual(checks["OV-018"]["status"], "fail")

    def test_shared_first_screen_rule_is_not_double_counted(self):
        self.facts.complete_first_screen_feeds_products = []
        audit, checks = self.checks()
        self.assertEqual(checks["OV-005"]["status"], "fail")
        self.assertEqual(checks["OV-023"]["status"], "fail")
        self.assertEqual(audit["mandatory_fail_count"], 1)
        self.reply.page_warnings = ["楼层3-楼层间隔异常占用了首屏"]
        _, checks = self.checks()
        self.assertEqual(checks["OV-005"]["status"], "uncertain")

    def test_812_calibration_reports_difference_without_acceptance_tolerance(self):
        comparison = replay.spacing_comparison(25, self.capture["screens"][0], self.spec)
        self.assertAlmostEqual(comparison["expected_image_px"], 24 * 844 / 812)
        self.assertAlmostEqual(comparison["observed_design_px"], 25 * 812 / 844)
        self.assertEqual(comparison["status"], "measured_without_acceptance_tolerance")
        self.assertTrue(comparison["calibration_confirmed"])

    def test_disabled_rules_cannot_be_injected_by_the_model(self):
        self.reply.checks.append(replay.Check(rule_id="OV-006", status="pass", observed="nav", reason="visible", evidence=[]))
        with self.assertRaises(ValueError):
            self.checks()

    def test_fact_review_is_hash_bound_and_cannot_set_a_verdict(self):
        review = {"screen_sha256": {"1": "one", "2": "two"}, "reason": "主标题复核",
                  "facts": {"texts": [{"screen": 1, "bbox_norm": [10, 100, 600, 200],
                             "text": "仅主标题", "role": "main_title", "readable": True}]}}
        updated = replay.apply_fact_reviews(self.reply, self.capture, [review])
        self.assertEqual(updated.facts.texts[0].text, "仅主标题")
        self.assertEqual(self.reply.facts.texts[0].text, "好物上新")
        review["screen_sha256"]["1"] = "wrong"
        with self.assertRaises(ValueError):
            replay.apply_fact_reviews(self.reply, self.capture, [review])
        review["screen_sha256"]["1"] = "one"
        review["facts"] = {"status": "pass"}
        with self.assertRaises(ValueError):
            replay.apply_fact_reviews(self.reply, self.capture, [review])

    def test_white_background_policy_replaces_original_conflict(self):
        def patch(box, color):
            return {"id": str(box), "role": "feeds_background", "screen": 1, "status": "measured",
                    "rule_ids": ["OV-010"], "file": "one.png", "sha256": "one", "bbox_px": box,
                    "label": "feeds外背景", "solid_sample": {"bbox_px": box, "dominant_hex": color},
                    "result": {"dominant_hex": color, "dominant_ratio": 1}}
        for color, expected in (("#FFFFFF", "pass"), ("#E999D0", "fail")):
            measurements = [patch([0, 500, 3, 503], color), patch([0, 600, 3, 603], color)]
            audit = replay.normalize(self.reply, self.capture, self.spec, measurements, [], self.previous)
            check = next(c for c in audit["checks"] if c["rule_id"] == "OV-010")
            self.assertEqual(check["status"], expected)

    def test_user_resolved_warning_is_removed_without_changing_original(self):
        self.previous["page_warnings"] = ["名称不同需确认", "楼层异常"]
        self.reply.page_warnings = ["名称不同需确认", "加载占位"]
        review = {"screen_sha256": {"1": "one", "2": "two"},
                  "resolved_page_warnings": ["名称不同需确认"]}
        audit = replay.normalize(self.reply, self.capture, self.spec, [], [], self.previous, [review])
        self.assertEqual(audit["page_warnings"], ["加载占位", "楼层异常"])
        self.assertIn("名称不同需确认", self.previous["page_warnings"])
        self.assertIn("名称不同需确认", self.reply.page_warnings)
        review["screen_sha256"]["1"] = "wrong"
        with self.assertRaises(ValueError):
            replay.normalize(self.reply, self.capture, self.spec, [], [], self.previous, [review])


if __name__ == "__main__":
    unittest.main()
