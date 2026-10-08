import asyncio
import base64
import json
import os
import sys
import unittest
from io import BytesIO

from PIL import Image


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)


def png_bytes(width=1000, height=1800):
    buffer = BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="PNG")
    return buffer.getvalue()


def valid_x_payload():
    return {
        "navigation_bar_above": {
            "present": True,
            "bbox_full_norm": [-20, 0, 500, 100],
            "evidence": "顶部频道导航",
        },
        "tab_bar_below": {
            "present": True,
            "bbox_full_norm": [0, 900, 1000, 1100],
            "evidence": "底部标签",
        },
        "floor": {
            "type": "combination",
            "bbox_norm": [0, 100, 1000, 900],
            "evidence": "左右组合布局",
        },
        "cover_title_floor": {
            "cover_image_present": True,
            "primary_focus_title_present": True,
            "bbox_norm": [0, 100, 650, 900],
            "evidence": "X区域包含封面图和首焦栏目标题",
        },
        "following_four_product_floor": {
            "present": False,
            "immediately_below_x": False,
            "bbox_full_norm": None,
            "evidence": "X区域下方未紧接一行4商品楼层",
        },
        "right_side": {
            "entry_count": 2,
            "entries_vertical": True,
            "bbox_norm": [650, 100, 1000, 900],
            "entries": [
                {"bbox_norm": [650, 100, 1000, 450]},
                {"bbox_norm": [650, 500, 1000, 900]},
            ],
        },
        "superstar_benefits": {"title_present": False},
    }


def valid_y_payload():
    return {
        "cover_image": {"present": True, "bbox_norm": [100, 200, 1200, 800]},
        "gradient_overlay": {
            "present": True,
            "supports_white_text": True,
            "bbox_norm": [100, 500, 900, 800],
        },
        "primary_focus_title": {"present": True, "bbox_norm": [150, 550, 600, 620]},
        "bottom_info_container": {"present": True, "bbox_norm": [100, 500, 900, 800]},
        "subtitle": {
            "present": True,
            "text": "新品尝鲜",
            "icon_present": False,
            "bbox_norm": [150, 630, 500, 690],
        },
        "benefit": {"present": True, "presentation": "button", "bbox_norm": [600, 650, 850, 750]},
    }


class FakeAnalyzer:
    providers = [{"name": "fake"}]

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def complete_images(self, prompt, images, preferred_provider=None, max_tokens=2048):
        response_index = len(self.calls)
        self.calls.append(
            {
                "prompt": prompt,
                "images": images,
                "preferred_provider": preferred_provider,
                "max_tokens": max_tokens,
            }
        )
        await asyncio.sleep(0)
        return self.responses[response_index]


class JdNewFloorAnalyzerTests(unittest.TestCase):
    def test_crops_twice_and_maps_clamped_bboxes_to_original_pixels(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        fake = FakeAnalyzer(
            "```json\n" + json.dumps(valid_x_payload(), ensure_ascii=False) + "\n```",
            json.dumps(valid_y_payload(), ensure_ascii=False),
        )
        result = asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes()))
        report = result.to_dict()

        self.assertEqual(len(fake.calls), 2)
        self.assertTrue(all(call["preferred_provider"] == "openai" for call in fake.calls))
        self.assertTrue(all(call["max_tokens"] == 4096 for call in fake.calls))
        decoded_sizes = []
        for call in fake.calls:
            decoded_sizes.append([])
            for encoded in call["images"]:
                with Image.open(BytesIO(base64.b64decode(encoded))) as image:
                    decoded_sizes[-1].append(image.size)
        self.assertEqual(decoded_sizes, [[(1000, 1800), (1000, 580)], [(540, 580)]])
        self.assertEqual(report["report_type"], "jd_new_floor_audit")
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["capture"], {"format": "PNG", "width": 1000, "height": 1800})
        self.assertEqual(report["regions"]["x"]["bbox_px"], [0, 510, 1000, 1090])
        self.assertEqual(report["regions"]["y"]["bbox_px"], [0, 510, 540, 1090])

        nav = report["checks"]["3.3"]["annotations"][0]
        self.assertEqual(nav["bbox_norm"], [0, 0, 500, 100])
        self.assertEqual(nav["bbox_px"], [0, 0, 500, 180])
        cover = report["checks"]["3.5"]["annotations"][0]
        self.assertEqual(cover["bbox_norm"], [100, 200, 1000, 800])
        self.assertEqual(cover["bbox_px"], [54, 626, 540, 974])

    def test_rejects_images_smaller_than_either_required_dimension_without_vlm_call(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        for width, height in ((539, 1800), (540, 1089)):
            with self.subTest(size=(width, height)):
                fake = FakeAnalyzer("{}", "{}")
                with self.assertRaisesRegex(ValueError, "at least 540x1090"):
                    asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes(width, height)))
                self.assertEqual(fake.calls, [])

    def test_conditional_checks_are_not_applicable(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        fake = FakeAnalyzer(json.dumps(valid_x_payload()), json.dumps(valid_y_payload()))
        report = asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes())).to_dict()

        self.assertEqual(set(report["checks"]), {"3.3", "3.4", "3.5", "3.6", "3.7", "3.8", "3.9"})
        self.assertEqual(report["checks"]["3.6"]["status"], "pass")
        self.assertEqual(report["checks"]["3.6"]["conclusion"], "格式正确")
        self.assertEqual(report["checks"]["3.6"]["region"], "x")
        self.assertEqual(report["checks"]["3.7"]["status"], "pass")
        self.assertEqual(report["checks"]["3.8"]["status"], "not_applicable")
        self.assertEqual(report["checks"]["3.9"]["status"], "not_applicable")
        self.assertTrue(all(report["checks"][check_id]["region"] == "x" for check_id in ("3.6", "3.7", "3.8", "3.9")))
        self.assertTrue(report["checks"]["3.7"]["annotations"])
        self.assertEqual(report["checks"]["3.7"]["annotations"][0]["bbox_px"], [650, 568, 1000, 1032])
        self.assertEqual(report["checks"]["3.8"]["annotations"], [])
        self.assertEqual(
            [item["label"] for item in report["checks"]["3.6"]["annotations"]],
            ["X区域封面图+首焦栏目标题"],
        )
        self.assertIn("未出现“超级明星福利”标题", report["checks"]["3.9"]["conclusion"])
        allowed = {"pass", "fail", "not_applicable", "uncertain"}
        self.assertTrue(all(check["status"] in allowed for check in report["checks"].values()))

    def test_server_marks_missing_required_components_as_fail(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        y_payload = valid_y_payload()
        y_payload["cover_image"]["present"] = False
        valid_entry = {
            "bbox_norm": [650, 100, 1000, 300],
            "tag_bar_present": True,
            "tag_text": "新品标签",
            "product_thumbnail_present": True,
            "product_name_present": True,
            "product_name_single_line": True,
            "price_row_present": True,
            "main_price_present": True,
            "cta_present": True,
            "cta_text": "抢",
            "compliant": True,
        }
        entries = [dict(valid_entry) for _ in range(3)]
        entries[1]["product_thumbnail_present"] = False
        x_payload = valid_x_payload()
        x_payload["right_side"] = {
            "entry_count": 3,
            "entries_vertical": True,
            "entries": entries,
            "compliant": True,
        }
        fake = FakeAnalyzer(json.dumps(x_payload), json.dumps(y_payload))

        report = asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes())).to_dict()

        self.assertEqual(report["checks"]["3.5"]["status"], "fail")
        self.assertEqual(report["checks"]["3.8"]["status"], "fail")
        self.assertEqual(report["checks"]["3.8"]["details"]["entries"][1]["status"], "fail")
        self.assertEqual(report["summary"]["status"], "fail")

    def test_missing_required_annotation_coordinates_prevent_false_passes(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        x_payload = valid_x_payload()
        x_payload["navigation_bar_above"]["bbox_full_norm"] = None
        x_payload["cover_title_floor"]["bbox_norm"] = None
        y_payload = valid_y_payload()
        y_payload["cover_image"]["bbox_norm"] = None
        entry = {
            "tag_bar_present": True,
            "tag_text": "新品",
            "product_thumbnail_present": True,
            "product_name_present": True,
            "product_name_single_line": True,
            "price_row_present": True,
            "main_price_present": True,
            "cta_present": True,
            "cta_text": "抢",
        }
        x_payload["right_side"] = {"entry_count": 3, "entries": [dict(entry) for _ in range(3)]}
        fake = FakeAnalyzer(json.dumps(x_payload), json.dumps(y_payload))

        report = asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes())).to_dict()

        self.assertEqual(report["checks"]["3.3"]["status"], "uncertain")
        self.assertEqual(report["checks"]["3.5"]["status"], "uncertain")
        self.assertEqual(report["checks"]["3.6"]["status"], "uncertain")
        self.assertEqual(report["checks"]["3.8"]["status"], "uncertain")

    def test_overlay_must_cover_the_bottom_title_and_benefit(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        y_payload = valid_y_payload()
        y_payload["gradient_overlay"]["bbox_norm"] = [100, 210, 900, 400]
        fake = FakeAnalyzer(json.dumps(valid_x_payload()), json.dumps(y_payload))

        report = asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes())).to_dict()

        details = report["checks"]["3.5"]["details"]
        self.assertEqual(report["checks"]["3.5"]["status"], "fail")
        self.assertFalse(details["overlay_at_cover_bottom"])
        self.assertFalse(details["primary_focus_title_supported_by_overlay"])
        self.assertFalse(details["benefit_supported_by_overlay"])

    def test_subtitle_and_benefit_are_alternative_bottom_info_content(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        payload_without_subtitle = valid_y_payload()
        payload_without_subtitle["subtitle"] = {"present": False}
        payload_without_benefit = valid_y_payload()
        payload_without_benefit["benefit"] = {"present": False}

        for y_payload, expected_valid_component in (
            (payload_without_subtitle, "benefit_valid"),
            (payload_without_benefit, "subtitle_valid"),
        ):
            with self.subTest(valid_component=expected_valid_component):
                fake = FakeAnalyzer(json.dumps(valid_x_payload()), json.dumps(y_payload))
                report = asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes())).to_dict()
                details = report["checks"]["3.5"]["details"]

                self.assertEqual(report["checks"]["3.5"]["status"], "pass")
                self.assertTrue(details[expected_valid_component])
                self.assertTrue(details["bottom_info_has_subtitle_or_benefit"])

    def test_missing_both_subtitle_and_benefit_fails_bottom_info_content(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        y_payload = valid_y_payload()
        y_payload["subtitle"] = {"present": False}
        y_payload["benefit"] = {"present": False}
        fake = FakeAnalyzer(json.dumps(valid_x_payload()), json.dumps(y_payload))

        report = asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes())).to_dict()
        check = report["checks"]["3.5"]

        self.assertEqual(check["status"], "fail")
        self.assertFalse(check["details"]["bottom_info_has_subtitle_or_benefit"])
        self.assertIn("信息容器内的小标题或利益点", check["conclusion"])

    def test_top_badge_is_not_a_subtitle_and_is_not_annotated(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer, Y_REGION_PROMPT

        y_payload = valid_y_payload()
        y_payload["subtitle"] = {
            "present": True,
            "text": "新发布+",
            "icon_present": True,
            "bbox_norm": [90, 40, 350, 110],
        }
        fake = FakeAnalyzer(json.dumps(valid_x_payload()), json.dumps(y_payload))

        report = asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes())).to_dict()
        check = report["checks"]["3.5"]

        self.assertEqual(check["status"], "pass")
        self.assertFalse(check["details"]["subtitle_present"])
        self.assertTrue(check["details"]["subtitle_rejected_as_badge"])
        self.assertIsNone(check["details"]["subtitle_text"])
        self.assertIsNone(check["details"]["subtitle_icon_present"])
        self.assertIsNone(check["details"]["subtitle_valid"])
        self.assertTrue(check["details"]["benefit_valid"])
        self.assertNotIn("小标题", [item["label"] for item in check["annotations"]])
        self.assertIn("新发布+", Y_REGION_PROMPT)

    def test_real_subtitle_outside_bottom_info_fails_even_when_benefit_is_valid(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        y_payload = valid_y_payload()
        y_payload["subtitle"]["bbox_norm"] = [90, 40, 350, 110]
        fake = FakeAnalyzer(json.dumps(valid_x_payload()), json.dumps(y_payload))

        report = asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes())).to_dict()
        check = report["checks"]["3.5"]

        self.assertEqual(check["status"], "fail")
        self.assertFalse(check["details"]["subtitle_valid"])
        self.assertTrue(check["details"]["benefit_valid"])
        self.assertIn("小标题", [item["label"] for item in check["annotations"]])

    def test_present_benefit_must_be_valid_even_when_subtitle_is_valid(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        y_payload = valid_y_payload()
        y_payload["benefit"]["presentation"] = "none"
        fake = FakeAnalyzer(json.dumps(valid_x_payload()), json.dumps(y_payload))

        report = asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes())).to_dict()
        check = report["checks"]["3.5"]

        self.assertEqual(check["status"], "fail")
        self.assertTrue(check["details"]["subtitle_valid"])
        self.assertFalse(check["details"]["benefit_valid"])
        self.assertFalse(check["details"]["benefit_valid_when_present"])

    def test_format_is_error_when_four_product_floor_immediately_follows_x(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        x_payload = valid_x_payload()
        x_payload["following_four_product_floor"] = {
            "present": True,
            "immediately_below_x": True,
            "bbox_full_norm": [0, 610, 1000, 900],
            "evidence": "X区域下方紧接一行4商品楼层",
        }
        fake = FakeAnalyzer(json.dumps(x_payload), json.dumps(valid_y_payload()))

        report = asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes())).to_dict()
        check = report["checks"]["3.6"]

        self.assertEqual(check["status"], "fail")
        self.assertEqual(check["conclusion"], "格式错误")
        self.assertTrue(check["details"]["condition_1_cover_title_floor"])
        self.assertTrue(check["details"]["condition_2_four_product_floor_immediately_below"])
        self.assertEqual(len(check["annotations"]), 2)

    def test_format_is_error_when_x_is_not_cover_title_floor(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        x_payload = valid_x_payload()
        x_payload["cover_title_floor"]["cover_image_present"] = False
        fake = FakeAnalyzer(json.dumps(x_payload), json.dumps(valid_y_payload()))

        check = asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes())).to_dict()["checks"]["3.6"]

        self.assertEqual(check["status"], "fail")
        self.assertEqual(check["conclusion"], "格式错误")
        self.assertFalse(check["details"]["condition_1_cover_title_floor"])

    def test_absent_following_floor_does_not_emit_stale_annotation(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        x_payload = valid_x_payload()
        x_payload["following_four_product_floor"] = {
            "present": False,
            "immediately_below_x": False,
            "bbox_full_norm": [0, 600, 1000, 900],
        }
        fake = FakeAnalyzer(json.dumps(x_payload), json.dumps(valid_y_payload()))

        report = asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes())).to_dict()
        check = report["checks"]["3.6"]

        self.assertEqual(check["status"], "pass")
        self.assertEqual(check["conclusion"], "格式正确")
        self.assertEqual(
            [item["label"] for item in check["annotations"]],
            ["X区域封面图+首焦栏目标题"],
        )

    def test_absent_components_never_emit_stale_annotations(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        x_payload = valid_x_payload()
        x_payload["navigation_bar_above"]["present"] = False

        y_payload = valid_y_payload()
        y_payload["cover_image"]["present"] = False
        y_payload["gradient_overlay"]["present"] = None
        y_payload["benefit"]["present"] = False
        x_payload["right_side"] = {
            "entry_count": 3,
            "entries_vertical": True,
            "bbox_norm": [650, 100, 1000, 900],
            "entries": [
                {"bbox_norm": [650, 100, 1000, 300]},
                {"bbox_norm": [650, 350, 1000, 600]},
                {"bbox_norm": [650, 650, 1000, 900]},
            ],
        }
        x_payload["superstar_benefits"] = {
            "title_present": False,
            "title_bbox_norm": [600, 50, 950, 120],
            "star_module_count": 2,
            "star_modules": [
                {"bbox_norm": [600, 140, 950, 430]},
                {"bbox_norm": [600, 450, 950, 740]},
            ],
            "refresh_button_present": False,
            "refresh_button_bbox_norm": [750, 760, 900, 820],
            "other_section_present": False,
            "other_section_bbox_norm": [600, 830, 950, 950],
        }
        fake = FakeAnalyzer(json.dumps(x_payload), json.dumps(y_payload))

        report = asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes())).to_dict()

        self.assertEqual(
            [item["label"] for item in report["checks"]["3.3"]["annotations"]],
            ["Tab栏"],
        )
        self.assertEqual(
            [item["label"] for item in report["checks"]["3.5"]["annotations"]],
            ["首焦栏目标题", "底部信息容器", "小标题"],
        )
        self.assertEqual(report["checks"]["3.7"]["status"], "not_applicable")
        self.assertEqual(report["checks"]["3.7"]["annotations"], [])
        self.assertEqual(
            [item["label"] for item in report["checks"]["3.8"]["annotations"]],
            ["三入口组件1", "三入口组件2", "三入口组件3"],
        )
        self.assertEqual(report["checks"]["3.9"]["status"], "not_applicable")
        self.assertEqual(report["checks"]["3.9"]["annotations"], [])

    def test_superstar_annotations_only_include_present_components(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        x_payload = valid_x_payload()
        x_payload["superstar_benefits"] = {
            "title_present": True,
            "title_bbox_norm": [600, 50, 950, 120],
            "star_module_count": 2,
            "star_modules_vertical": True,
            "star_modules": [
                {"bbox_norm": [600, 140, 950, 430]},
                {"bbox_norm": [600, 450, 950, 740]},
            ],
            "refresh_button_present": False,
            "refresh_button_bbox_norm": [750, 760, 900, 820],
            "other_section_present": False,
            "other_section_bbox_norm": [600, 830, 950, 950],
        }
        fake = FakeAnalyzer(json.dumps(x_payload), json.dumps(valid_y_payload()))

        report = asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes())).to_dict()

        self.assertEqual(
            [item["label"] for item in report["checks"]["3.9"]["annotations"]],
            ["超级明星福利标题", "明星模块1", "明星模块2"],
        )

    def test_superstar_status_is_derived_from_atomic_facts(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        x_payload = valid_x_payload()
        x_payload["superstar_benefits"] = {
            "title_present": True,
            "star_module_count": 2,
            "star_modules_vertical": True,
            "refresh_button_present": True,
            "other_section_present": True,
            "compliant": True,
        }
        fake = FakeAnalyzer(json.dumps(x_payload), json.dumps(valid_y_payload()))

        report = asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes())).to_dict()

        self.assertEqual(report["checks"]["3.9"]["status"], "fail")

    def test_missing_superstar_title_is_not_applicable(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        fake = FakeAnalyzer(json.dumps(valid_x_payload()), json.dumps(valid_y_payload()))

        report = asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes())).to_dict()

        check = report["checks"]["3.9"]
        self.assertEqual(check["status"], "not_applicable")
        self.assertIn("未出现“超级明星福利”标题", check["conclusion"])

    def test_superstar_title_alone_triggers_the_check(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        x_payload = valid_x_payload()
        x_payload["superstar_benefits"] = {
            "title_present": True,
            "title_bbox_norm": [600, 50, 950, 120],
            "star_module_count": 2,
            "star_modules_vertical": True,
            "star_modules": [
                {"bbox_norm": [600, 140, 950, 430]},
                {"bbox_norm": [600, 450, 950, 740]},
            ],
            "refresh_button_present": True,
            "refresh_button_bbox_norm": [750, 760, 900, 820],
            "other_section_present": False,
        }
        fake = FakeAnalyzer(json.dumps(x_payload), json.dumps(valid_y_payload()))

        report = asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes())).to_dict()

        self.assertEqual(report["checks"]["3.9"]["status"], "pass")

    def test_invalid_json_raises_after_both_region_calls(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        fake = FakeAnalyzer("not json", json.dumps(valid_y_payload()), "still not json")
        with self.assertRaisesRegex(ValueError, "invalid JSON for x region"):
            asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes()))
        self.assertEqual(len(fake.calls), 3)

    def test_retries_one_empty_region_response(self):
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalyzer

        fake = FakeAnalyzer(
            "",
            json.dumps(valid_y_payload()),
            json.dumps(valid_x_payload()),
        )

        report = asyncio.run(JdNewFloorAnalyzer(fake).analyze_png(png_bytes())).to_dict()

        self.assertEqual(len(fake.calls), 3)
        self.assertEqual(report["checks"]["3.4"]["status"], "pass")


if __name__ == "__main__":
    unittest.main()
