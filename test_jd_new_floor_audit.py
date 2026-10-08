import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image


class JdNewFloorAuditTests(unittest.TestCase):
    def test_uses_screen_ratio_when_new_tab_is_not_accessible(self):
        from worker.jd_new_floor_audit import AdbFloorCapture

        class MissingElement:
            exists = False

        class FakeDevice:
            def __init__(self):
                self.clicked = None

            def __call__(self, **_selector):
                return MissingElement()

            def window_size(self):
                return 1080, 2400

            def click(self, x, y):
                self.clicked = (x, y)

        device = FakeDevice()
        method = AdbFloorCapture()._click_target_tab(device, "新品")

        self.assertEqual(method, "screen_ratio")
        self.assertEqual(device.clicked, (626, 134))

    def test_only_clicks_new_tab_when_match_is_in_top_navigation(self):
        from worker.jd_new_floor_audit import AdbFloorCapture

        class Element:
            def __init__(self, exists, bounds):
                self.exists = exists
                self.info = {"bounds": bounds}
                self.clicked = False

            def click(self):
                self.clicked = True

        middle = Element(True, {"left": 100, "top": 900, "right": 220, "bottom": 980})
        top = Element(True, {"left": 578, "top": 80, "right": 739, "bottom": 207})
        missing = Element(False, {})

        class FakeDevice:
            def __call__(self, **selector):
                if selector.get("text") == "新品":
                    return {0: middle, 1: top}.get(selector.get("instance"), missing)
                return missing

            def window_size(self):
                return 1080, 2400

        method = AdbFloorCapture()._click_target_tab(FakeDevice(), "新品")

        self.assertEqual(method, "accessibility")
        self.assertFalse(middle.clicked)
        self.assertTrue(top.clicked)

    def test_clicks_new_market_only_in_secondary_navigation_band(self):
        from worker.jd_new_floor_audit import AdbFloorCapture

        class Element:
            def __init__(self, exists, bounds):
                self.exists = exists
                self.info = {"bounds": bounds}
                self.clicked = False

            def click(self):
                self.clicked = True

        wrong = Element(True, {"left": 80, "top": 1300, "right": 260, "bottom": 1360})
        correct = Element(True, {"left": 238, "top": 439, "right": 402, "bottom": 497})
        missing = Element(False, {})

        class FakeDevice:
            def __call__(self, **selector):
                if selector.get("text") == "新奇集市":
                    return {0: wrong, 1: correct}.get(selector.get("instance"), missing)
                return missing

            def window_size(self):
                return 1080, 2400

        method = AdbFloorCapture()._click_secondary_tab(FakeDevice(), "新奇集市")

        self.assertEqual(method, "accessibility")
        self.assertFalse(wrong.clicked)
        self.assertTrue(correct.clicked)

    def test_does_not_guess_coordinates_for_unknown_tab(self):
        from worker.jd_new_floor_audit import AdbFloorCapture

        class MissingElement:
            exists = False

        class FakeDevice:
            def __call__(self, **_selector):
                return MissingElement()

        with self.assertRaisesRegex(RuntimeError, "Target tab not found: 其他"):
            AdbFloorCapture()._click_target_tab(FakeDevice(), "其他")

    def test_worker_routes_floor_audit_and_attaches_both_artifacts(self):
        from worker.client import FLOOR_ANALYSIS_TIMEOUT_SECONDS
        from worker.executor import _attach_result_artifact, _build_command

        command = _build_command(
            Path("/repo"),
            {"mode": "jd_new_floor_audit", "target_app": "京东"},
            "run-1",
            "task-1",
            "device-1",
            Path("/tmp/artifacts"),
        )
        self.assertIn("/repo/run_jd_new_floor_audit.py", command)
        self.assertEqual(command[command.index("--target-tab") + 1], "新品")
        self.assertGreaterEqual(FLOOR_ANALYSIS_TIMEOUT_SECONDS, 400)

        report = {
            "artifacts": {
                "raw": {"filename": "raw_fullscreen.png"},
                "annotated": {"filename": "annotated_floor_audit.png"},
            }
        }
        _attach_result_artifact(
            report,
            "annotated_floor_audit.png",
            {"image_id": "image-1", "file_path": "data/image.png", "oss_url": "https://example/image.png"},
        )
        self.assertEqual(report["artifacts"]["annotated"]["image_id"], "image-1")
        self.assertNotIn("image_id", report["artifacts"]["raw"])

        report["secondary_tab_audit"] = {
            "frames": {"z2_before": {"filename": "secondary_tab_z2_before.png"}}
        }
        _attach_result_artifact(
            report,
            "secondary_tab_z2_before.png",
            {"image_id": "image-2", "file_path": "data/z2.png", "oss_url": "https://example/z2.png"},
        )
        self.assertEqual(
            report["secondary_tab_audit"]["frames"]["z2_before"]["image_id"],
            "image-2",
        )

    def test_capture_analyze_annotate_and_close(self):
        from worker.jd_new_floor_audit import JdNewFloorAudit, JdNewFloorConfig

        class FakeCapture:
            def __init__(self):
                self.closed = False

            def open_app(self, config):
                self.opened = config.package

            def prepare_target(self, config):
                return {"popup_close_count": 2}

            def capture_fullscreen(self, config):
                from io import BytesIO

                buffer = BytesIO()
                Image.new("RGB", (1080, 2400), "white").save(buffer, format="PNG")
                return buffer.getvalue()

            def close_app(self, config):
                self.closed = True

        def analyze(_path):
            return {
                "report_type": "jd_new_floor_audit",
                "schema_version": 1,
                "capture": {},
                "regions": {
                    "x": {"bbox_px": [0, 510, 1080, 1090]},
                    "y": {"bbox_px": [0, 510, 540, 1090]},
                },
                "checks": {
                    "3.3": {
                        "id": "3.3",
                        "status": "pass",
                        "annotations": [{"label": "导航栏", "bbox_px": [0, 510, 1080, 590]}],
                    }
                },
                "summary": {"pass": 1, "fail": 0, "uncertain": 0, "not_applicable": 0},
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            capture = FakeCapture()
            result = JdNewFloorAudit(analyze=analyze, capture=capture).run(
                JdNewFloorConfig(
                    app_name="京东",
                    package="com.jingdong.app.mall",
                    device_serial="device-1",
                    output_dir=Path(temp_dir),
                )
            )

            self.assertTrue(capture.closed)
            self.assertTrue(result.raw_path.exists())
            self.assertTrue(result.annotated_path.exists())
            report = json.loads(result.report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["capture"]["popup_close_count"], 2)
            self.assertEqual(report["artifacts"]["raw"]["filename"], "raw_fullscreen.png")
            with Image.open(result.annotated_path) as annotated:
                self.assertEqual(annotated.getpixel((1079, 1090)), (255, 149, 0))
                self.assertEqual(annotated.getpixel((539, 1090)), (0, 163, 255))

    def test_combined_capture_preserves_old_report_and_adds_secondary_section(self):
        from io import BytesIO

        from worker.jd_new_floor_audit import JdNewFloorAudit, JdNewFloorConfig

        class FakeCapture:
            def __init__(self):
                self.swipes = []
                self.capture_count = 0
                self.events = []
                self.closed = False

            def open_app(self, _config):
                pass

            def prepare_target(self, _config):
                return {"navigation_method": "accessibility", "popup_close_count": 1}

            def enter_secondary_tab(self, _config, target_tab):
                self.events.append("enter_secondary_tab")
                self.secondary_target = target_tab
                return "accessibility"

            def capture_fullscreen(self, _config):
                self.capture_count += 1
                self.events.append(f"capture_{self.capture_count}")
                buffer = BytesIO()
                Image.new("RGB", (1080, 2400), "white").save(buffer, format="PNG")
                return buffer.getvalue()

            def swipe(self, _config, start_x, start_y, end_x, end_y, duration_ms):
                self.swipes.append((start_x, start_y, end_x, end_y, duration_ms))

            def close_app(self, _config):
                self.closed = True

        def analyze_floor(_path):
            return {
                "report_type": "jd_new_floor_audit",
                "schema_version": 1,
                "capture": {},
                "regions": {},
                "checks": {"3.3": {"id": "3.3", "status": "pass", "annotations": []}},
                "summary": {"status": "pass", "counts": {"pass": 1}},
            }

        analyzed_paths = {}
        analyzed_z1_bbox = None
        located_from = None

        def locate_secondary(path):
            nonlocal located_from
            located_from = path.name
            return {
                "report_type": "jd_secondary_tab_locator",
                "anchor_text": "推荐",
                "anchor_color": "red",
                "anchor_bbox_px": [45, 1036, 125, 1075],
                "bbox_px": [0, 1010, 1080, 1090],
                "visible_texts": ["推荐", "新奇AI"],
                "evidence": "红色推荐所在横向Tab行",
            }

        def analyze_secondary(paths, z1_bbox):
            nonlocal analyzed_z1_bbox
            analyzed_paths.update(paths)
            analyzed_z1_bbox = z1_bbox
            return {
                "report_type": "jd_secondary_tab_audit",
                "schema_version": 1,
                "capture": {},
                "regions": {},
                "frames": {
                    key: {"filename": path.name}
                    for key, path in paths.items()
                },
                "checks": {},
                "summary": {"status": "pass", "counts": {"pass": 6}},
            }

        with tempfile.TemporaryDirectory() as temp_dir, patch("worker.jd_new_floor_audit.time.sleep") as sleep:
            capture = FakeCapture()
            result = JdNewFloorAudit(
                analyze=analyze_floor,
                locate_secondary=locate_secondary,
                analyze_secondary=analyze_secondary,
                capture=capture,
            ).run(
                JdNewFloorConfig(
                    app_name="京东",
                    package="com.jingdong.app.mall",
                    device_serial="device-1",
                    output_dir=Path(temp_dir),
                )
            )

            self.assertTrue(capture.closed)
            self.assertEqual(capture.secondary_target, "新奇集市")
            self.assertEqual(capture.capture_count, 6)
            self.assertEqual(capture.events[:3], ["capture_1", "enter_secondary_tab", "capture_2"])
            self.assertEqual(located_from, "secondary_tab_z1_before.png")
            self.assertEqual(analyzed_z1_bbox, [0, 1010, 1080, 1090])
            sleep.assert_any_call(8.0)
            self.assertEqual(set(analyzed_paths), {
                "z1_before",
                "z1_after_left",
                "z2_before",
                "z2_after_left",
                "z3_before",
            })
            self.assertEqual(analyzed_paths["z1_before"].name, "secondary_tab_z1_before.png")
            self.assertEqual(len(capture.swipes), 6)
            self.assertEqual(capture.swipes[0][1], 1050)
            self.assertEqual(capture.swipes[0][2] - capture.swipes[0][0], -400)
            self.assertEqual(capture.swipes[2][3] - capture.swipes[2][1], -800)
            self.assertEqual(capture.swipes[5][3] - capture.swipes[5][1], 400)
            self.assertEqual(result.report["checks"]["3.3"]["status"], "pass")
            self.assertEqual(result.report["secondary_tab_audit"]["report_type"], "jd_secondary_tab_audit")
            self.assertEqual(
                result.report["secondary_tab_audit"]["capture"]["horizontal_swipe_distance_px"],
                400,
            )
            self.assertEqual(result.report["artifacts"]["raw"]["filename"], "raw_fullscreen.png")

    def test_closes_app_when_analysis_fails(self):
        from io import BytesIO

        from worker.jd_new_floor_audit import JdNewFloorAudit, JdNewFloorConfig

        class FakeCapture:
            closed = False

            def open_app(self, _config):
                pass

            def prepare_target(self, _config):
                return {}

            def capture_fullscreen(self, _config):
                buffer = BytesIO()
                Image.new("RGB", (1080, 2400), "white").save(buffer, format="PNG")
                return buffer.getvalue()

            def close_app(self, _config):
                self.closed = True

        capture = FakeCapture()
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(RuntimeError, "analysis failed"):
                JdNewFloorAudit(
                    analyze=lambda _path: (_ for _ in ()).throw(RuntimeError("analysis failed")),
                    capture=capture,
                ).run(
                    JdNewFloorConfig(
                        app_name="京东",
                        package="com.jingdong.app.mall",
                        device_serial="device-1",
                        output_dir=Path(temp_dir),
                    )
                )
        self.assertTrue(capture.closed)


if __name__ == "__main__":
    unittest.main()
