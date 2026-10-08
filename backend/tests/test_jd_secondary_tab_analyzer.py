import asyncio
import json
import os
import sys
import unittest
from contextlib import ExitStack
from io import BytesIO
from unittest.mock import patch

from PIL import Image, ImageDraw


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)


class FakeCompletion:
    providers = [object()]

    def __init__(self, baseline: dict, horizontal: dict, locator: dict | None = None):
        self.baseline = baseline
        self.horizontal = horizontal
        self.locator = locator or {}
        self.calls = []

    async def complete_images(self, prompt, images, preferred_provider=None, max_tokens=0):
        self.calls.append(
            {
                "prompt": prompt,
                "images": images,
                "preferred_provider": preferred_provider,
                "max_tokens": max_tokens,
            }
        )
        if "组件定位器" in prompt:
            payload = self.locator
        else:
            payload = self.horizontal if "横向滑动验证器" in prompt else self.baseline
        return json.dumps(payload, ensure_ascii=False)


def baseline_payload(selected_text: str = "精选") -> dict:
    def region():
        return {
            "items": [
                {
                    "text": selected_text,
                    "state": "selected",
                    "single_line": True,
                    "bbox_norm": [90, 200, 190, 800],
                },
                {
                    "text": "趋势",
                    "state": "special",
                    "single_line": True,
                    "bbox_norm": [280, 200, 380, 800],
                },
                {
                    "text": "品牌",
                    "state": "unselected",
                    "single_line": True,
                    "bbox_norm": [470, 200, 570, 800],
                },
            ],
            "all_single_line": True,
            "selected_color_hex": "#FF0F23",
            "unselected_color_hex": "#3D414D",
            "background_color_hex": "#F2F3F5",
            "second_button_color_hex": "#E63FAF",
            "selected_matches_target_FF0F23": True,
            "unselected_matches_target_3D414D": True,
            "background_matches_target_F2F3F5": True,
            "second_button_matches_target_E63FAF": True,
            "evidence": "三个文本项均为单行",
        }

    return {
        "regions": {"z1": region(), "z2": region(), "z3": region()},
        "comparisons": {
            "z2_matches_z1": True,
            "z2_evidence": "文字与顺序一致",
            "z3_matches_z1": False,
            "z3_evidence": "回退后内容与z1不同",
            "selected_content_consistent": True,
            "selected_content_evidence": "均选中精选",
        },
    }


def horizontal_payload(z2_moved: bool | None = True, outside_unchanged: bool | None = True) -> dict:
    return {
        "regions": {
            "z1": {
                "content_moved_horizontally": True,
                "outside_region_unchanged": outside_unchanged,
                "before_texts": ["精选", "趋势"],
                "after_texts": ["趋势", "品牌"],
                "evidence": "文本整体左移且区域外不变",
            },
            "z2": {
                "content_moved_horizontally": z2_moved,
                "outside_region_unchanged": outside_unchanged,
                "before_texts": ["精选", "趋势"],
                "after_texts": ["趋势", "品牌"],
                "evidence": "文本整体左移且区域外不变" if z2_moved else "未观察到位移",
            },
        }
    }


def frame_png() -> bytes:
    image = Image.new("RGB", (1080, 2400), (250, 250, 250))
    draw = ImageDraw.Draw(image)
    draw.rectangle((97, 1026, 205, 1074), fill=(225, 37, 27))
    draw.rectangle((302, 1026, 410, 1074), fill=(230, 63, 175))
    draw.rectangle((508, 1026, 616, 1074), fill=(102, 102, 102))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class JdSecondaryTabAnalyzerTests(unittest.TestCase):
    def test_locator_and_color_sampling_support_legacy_pillow(self):
        from app.services.jd_secondary_tab_analyzer import FRAME_KEYS, JdSecondaryTabAnalyzer

        locator = {
            "present": True,
            "anchor_text": "推荐",
            "anchor_color": "red",
            "anchor_bbox_norm": [90, 428, 190, 448],
            "tab_row_bbox_norm": [0, 421, 1000, 454],
            "visible_texts": ["推荐", "趋势", "品牌"],
        }
        fake = FakeCompletion(baseline_payload(), horizontal_payload(), locator)
        analyzer = JdSecondaryTabAnalyzer(fake)
        with ExitStack() as stack:
            if hasattr(Image.Image, "get_flattened_data"):
                stack.enter_context(patch.object(Image.Image, "get_flattened_data"))
                delattr(Image.Image, "get_flattened_data")
            located = asyncio.run(analyzer.locate_z1_png(frame_png()))
            report = asyncio.run(
                analyzer.analyze_pngs({key: frame_png() for key in FRAME_KEYS}, 1010, 1090)
            ).to_dict()

        self.assertEqual(located["bbox_px"], [0, 1010, 1080, 1090])
        self.assertEqual(report["checks"]["1"]["details"]["selected_color_hex"], "#E1251B")
        self.assertEqual(report["checks"]["1"]["details"]["second_button_color_hex"], "#E63FAF")

    def test_locates_dynamic_z1_from_red_recommendation_anchor(self):
        from app.services.jd_secondary_tab_analyzer import JdSecondaryTabAnalyzer

        locator = {
            "present": True,
            "anchor_text": "推荐",
            "anchor_color": "red",
            "anchor_bbox_norm": [90, 428, 190, 448],
            "tab_row_bbox_norm": [0, 421, 1000, 454],
            "visible_texts": ["推荐", "新奇AI", "新奇数码"],
            "evidence": "红色推荐位于横向Tab行",
        }
        fake = FakeCompletion(baseline_payload(), horizontal_payload(), locator)
        result = asyncio.run(JdSecondaryTabAnalyzer(fake).locate_z1_png(frame_png()))

        self.assertEqual(result["report_type"], "jd_secondary_tab_locator")
        self.assertEqual(result["anchor_text"], "推荐")
        self.assertEqual(result["bbox_px"], [0, 1010, 1080, 1090])
        self.assertEqual(len(fake.calls), 1)

    def test_builds_six_checks_and_samples_hex_colors(self):
        from app.services.jd_secondary_tab_analyzer import FRAME_KEYS, JdSecondaryTabAnalyzer

        fake = FakeCompletion(baseline_payload(), horizontal_payload())
        report = asyncio.run(
            JdSecondaryTabAnalyzer(fake).analyze_pngs(
                {key: frame_png() for key in FRAME_KEYS}, 1010, 1090
            )
        ).to_dict()

        self.assertEqual(report["report_type"], "jd_secondary_tab_audit")
        self.assertEqual(report["regions"]["z1"]["bbox_px"], [0, 1010, 1080, 1090])
        self.assertEqual(report["regions"]["z2"]["bbox_px"], [0, 450, 1080, 525])
        self.assertEqual(report["frames"]["z1_before"]["filename"], "secondary_tab_z1_before.png")
        self.assertEqual(len(fake.calls), 2)
        self.assertTrue(all(call["preferred_provider"] == "openai" for call in fake.calls))
        self.assertTrue(all(call["max_tokens"] == 4096 for call in fake.calls))

        first = report["checks"]["1"]
        self.assertEqual(first["status"], "pass")
        self.assertEqual(first["details"]["selected_count"], 1)
        self.assertEqual(first["details"]["unselected_count"], 1)
        self.assertEqual(first["details"]["special_count"], 1)
        self.assertEqual(first["details"]["selected_color_hex"], "#E1251B")
        self.assertEqual(first["details"]["unselected_color_hex"], "#666666")
        self.assertEqual(first["details"]["background_color_hex"], "#FAFAFA")
        self.assertEqual(first["details"]["second_button_text"], "趋势")
        self.assertEqual(first["details"]["second_button_color_hex"], "#E63FAF")
        self.assertTrue(first["details"]["second_button_color_matches_target"])
        self.assertIn("有1组选中态，1组非选中态", first["conclusion"])
        self.assertIn("第二个按钮“趋势”文字色值为#E63FAF", first["conclusion"])
        self.assertTrue(all(check["status"] == "pass" for check in report["checks"].values()))
        self.assertEqual(report["checks"]["2"]["conclusion"], "正确")
        self.assertEqual(report["checks"]["3"]["conclusion"], "正确")
        self.assertEqual(len(report["checks"]["6"]["evidence"]), 4)
        self.assertEqual(report["checks"]["6"]["evidence"][0]["bbox_px"], [0, 0, 1080, 2400])
        self.assertTrue(report["checks"]["6"]["evidence"][0]["full_frame"])

    def test_failed_horizontal_region_fails_check_six(self):
        from app.services.jd_secondary_tab_analyzer import FRAME_KEYS, JdSecondaryTabAnalyzer

        fake = FakeCompletion(baseline_payload(), horizontal_payload(z2_moved=False))
        report = asyncio.run(
            JdSecondaryTabAnalyzer(fake).analyze_pngs(
                {key: frame_png() for key in FRAME_KEYS}, 1010, 1090
            )
        ).to_dict()

        self.assertEqual(report["checks"]["6"]["status"], "fail")
        self.assertIn("z2", report["checks"]["6"]["conclusion"])
        self.assertEqual(report["summary"]["status"], "fail")

    def test_second_button_target_mismatch_fails_only_color_requirement(self):
        from app.services.jd_secondary_tab_analyzer import FRAME_KEYS, JdSecondaryTabAnalyzer

        baseline = baseline_payload()
        baseline["regions"]["z1"]["items"][1]["state"] = "unselected"
        baseline["regions"]["z1"]["second_button_matches_target_E63FAF"] = False
        fake = FakeCompletion(baseline, horizontal_payload())
        report = asyncio.run(
            JdSecondaryTabAnalyzer(fake).analyze_pngs(
                {key: frame_png() for key in FRAME_KEYS}, 1010, 1090
            )
        ).to_dict()

        first = report["checks"]["1"]
        self.assertEqual(first["status"], "fail")
        self.assertEqual(first["details"]["selected_count"], 1)
        self.assertEqual(first["details"]["unselected_count"], 1)
        self.assertEqual(first["details"]["special_count"], 1)
        self.assertIn("和目标色值#E63FAF不一致", first["conclusion"])

    def test_color_target_mismatch_and_multiple_selected_items_fail(self):
        from app.services.jd_secondary_tab_analyzer import FRAME_KEYS, JdSecondaryTabAnalyzer

        baseline = baseline_payload()
        baseline["regions"]["z1"]["selected_matches_target_FF0F23"] = False
        baseline["regions"]["z2"]["items"][2]["state"] = "selected"
        fake = FakeCompletion(baseline, horizontal_payload())
        report = asyncio.run(
            JdSecondaryTabAnalyzer(fake).analyze_pngs(
                {key: frame_png() for key in FRAME_KEYS}, 1010, 1090
            )
        ).to_dict()

        self.assertEqual(report["checks"]["1"]["status"], "fail")
        self.assertIn("不一致", report["checks"]["1"]["conclusion"])
        self.assertEqual(report["checks"]["5"]["status"], "fail")

    def test_z3_matching_z1_is_reported_as_error(self):
        from app.services.jd_secondary_tab_analyzer import FRAME_KEYS, JdSecondaryTabAnalyzer

        baseline = baseline_payload()
        baseline["comparisons"]["z3_matches_z1"] = True
        fake = FakeCompletion(baseline, horizontal_payload())
        report = asyncio.run(
            JdSecondaryTabAnalyzer(fake).analyze_pngs(
                {key: frame_png() for key in FRAME_KEYS}, 1010, 1090
            )
        ).to_dict()

        self.assertEqual(report["checks"]["3"]["status"], "fail")
        self.assertEqual(report["checks"]["3"]["conclusion"], "错误")

    def test_outside_change_fails_horizontal_check(self):
        from app.services.jd_secondary_tab_analyzer import FRAME_KEYS, JdSecondaryTabAnalyzer

        fake = FakeCompletion(baseline_payload(), horizontal_payload(outside_unchanged=False))
        report = asyncio.run(
            JdSecondaryTabAnalyzer(fake).analyze_pngs(
                {key: frame_png() for key in FRAME_KEYS}, 1010, 1090
            )
        ).to_dict()

        self.assertEqual(report["checks"]["6"]["status"], "fail")
        self.assertIn("区域外内容发生变化", report["checks"]["6"]["conclusion"])

    def test_missing_tab_content_is_a_failure_not_a_false_match(self):
        from app.services.jd_secondary_tab_analyzer import FRAME_KEYS, JdSecondaryTabAnalyzer

        baseline = baseline_payload()
        baseline["regions"]["z1"]["items"] = []
        baseline["regions"]["z2"]["items"] = []
        baseline["comparisons"]["z2_matches_z1"] = None
        fake = FakeCompletion(baseline, horizontal_payload())
        report = asyncio.run(
            JdSecondaryTabAnalyzer(fake).analyze_pngs(
                {key: frame_png() for key in FRAME_KEYS}, 1010, 1090
            )
        ).to_dict()

        self.assertEqual(report["checks"]["1"]["status"], "fail")
        self.assertEqual(report["checks"]["2"]["status"], "fail")
        self.assertEqual(report["checks"]["4"]["status"], "fail")
        self.assertEqual(report["checks"]["5"]["status"], "fail")
        self.assertEqual(report["checks"]["6"]["status"], "fail")

    def test_missing_frame_is_rejected_before_model_calls(self):
        from app.services.jd_secondary_tab_analyzer import FRAME_KEYS, JdSecondaryTabAnalyzer

        fake = FakeCompletion(baseline_payload(), horizontal_payload())
        frames = {key: frame_png() for key in FRAME_KEYS if key != "z3_before"}
        with self.assertRaisesRegex(ValueError, "z3_before"):
            asyncio.run(JdSecondaryTabAnalyzer(fake).analyze_pngs(frames, 1010, 1090))
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
