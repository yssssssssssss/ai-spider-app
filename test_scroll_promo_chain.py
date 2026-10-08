import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image


class ScrollPromoChainTests(unittest.TestCase):
    def test_static_confidence_uses_explicit_threshold(self):
        from worker.scroll_promo_chain import passes_static_confidence

        self.assertTrue(passes_static_confidence(True, 0.75))
        self.assertTrue(passes_static_confidence(True, 0.90))
        self.assertFalse(passes_static_confidence(True, 0.74))
        self.assertFalse(passes_static_confidence(False, 0.99))

    def test_collapsed_width_uses_strict_two_thirds_threshold(self):
        from worker.scroll_promo_chain import is_collapsed_width

        self.assertTrue(is_collapsed_width(66, 100))
        self.assertFalse(is_collapsed_width(2, 3))
        self.assertFalse(is_collapsed_width(67, 100))
        self.assertFalse(is_collapsed_width(None, 100))

    def test_capture_rejects_blank_screen(self):
        from io import BytesIO
        from worker.scroll_promo_chain import ScrcpyScrollCapture

        black = BytesIO()
        white = BytesIO()
        Image.new("RGB", (100, 200), "black").save(black, format="PNG")
        Image.new("RGB", (100, 200), "white").save(white, format="PNG")

        capture = ScrcpyScrollCapture()
        self.assertTrue(capture.is_blank_png(black.getvalue()))
        self.assertFalse(capture.is_blank_png(white.getvalue()))

    def test_executor_attaches_uploaded_image_ids_to_report_frames(self):
        from worker.executor import _attach_result_artifact

        result = {
            "step2": {"frames": [{"annotated_file": "static.png"}]},
            "step3": {"detections": [{"annotated_file": "motion.png"}]},
        }
        _attach_result_artifact(result, "motion.png", {"image_id": "image-1", "file_path": "data/image.png", "oss_url": "https://example/image.png"})

        self.assertEqual(result["step3"]["detections"][0]["image_id"], "image-1")
        self.assertNotIn("image_id", result["step2"]["frames"][0])

    def test_worker_executor_routes_scroll_promo_mode_to_chain(self):
        from worker.executor import _build_command

        command = _build_command(
            Path("/repo"),
            {"mode": "scroll_promo", "target_app": "京东", "scroll_promo_config_json": {
                "target_app": "京东",
                "target_tab": "新品",
                "static_scroll_distance_px": 777,
                "max_frames": 4,
                "fps": 8,
            }},
            "run-1",
            "task-1",
            "device-1",
            Path("/tmp/artifacts"),
        )

        self.assertIn("/repo/run_scroll_promo_chain.py", command)
        self.assertEqual(command[command.index("--package") + 1], "com.jingdong.app.mall")
        self.assertEqual(command[command.index("--max-frames") + 1], "4")
        self.assertEqual(command[command.index("--static-scroll-distance") + 1], "777")

    def test_chain_keeps_at_most_six_motion_frames_and_draws_red_boxes(self):
        from worker.scroll_promo_chain import ScrollPromoChain, ScrollPromoConfig

        class FakeCapture:
            method = "fake_recording"

            def __init__(self):
                self.closed = False
                self.still_count = 0
                self.static_scrolls = []

            def open_app(self, package, device_serial, wait_seconds):
                self.opened = (package, device_serial)

            def prepare_target(self, config):
                self.prepared = (config.target_tab, config.page_wait_seconds)
                return {"popup_closed": True}

            def capture_still(self, config, scratch_dir):
                self.still_count += 1
                path = scratch_dir / f"static-{self.still_count}.png"
                Image.new("RGB", (100, 200), (200, self.still_count * 20, 40)).save(path)
                return path

            def scroll_static(self, config, pixels):
                self.static_scrolls.append(pixels)

            def capture_swipe(self, config, scratch_dir):
                frames = []
                for index in range(10):
                    path = scratch_dir / f"frame-{index:02d}.png"
                    Image.new("RGB", (100, 200), (index * 20, 30, 40)).save(path)
                    frames.append(path)
                return frames

            def close_app(self, package, device_serial):
                self.closed = True

        def detect(path):
            if path.name == "static-1.png":
                bbox = None
                state = "none"
                close_present = False
                close_bbox = None
            elif path.name == "static-2.png":
                bbox = [650, 650, 950, 900]
                state = "expanded"
                close_present = False
                close_bbox = None
            elif path.name == "static-3.png":
                bbox = [680, 660, 930, 900]
                state = "expanded"
                close_present = True
                close_bbox = [760, 900, 840, 960]
            else:
                bbox = [800, 700, 950, 900]
                state = "expanded"
                close_present = False
                close_bbox = None
            return {
                "promo_present": bbox is not None,
                "promo_state": state,
                "promo_bbox_norm": bbox,
                "promo_description": "促销贴片",
                "close_button_present": close_present,
                "close_button_below_promo": close_present,
                "close_button_bbox_norm": close_bbox,
                "close_button_description": "",
                "confidence": 0.9,
                "image_width": 100,
                "image_height": 200,
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir, "artifacts")
            capture = FakeCapture()
            result = ScrollPromoChain(capture=capture, detect=detect).run(
                ScrollPromoConfig(
                    app_name="京东",
                    package="com.jingdong.app.mall",
                    device_serial="device-1",
                    output_dir=output_dir,
                    max_frames=6,
                    target_tab="新品",
                    page_wait_seconds=5,
                )
            )

            self.assertEqual(len(result.annotated_paths), 9)
            self.assertTrue(capture.closed)
            self.assertEqual(capture.prepared, ("新品", 5))
            self.assertEqual(capture.static_scrolls, [600, 600])
            self.assertTrue(all(path.exists() for path in result.annotated_paths))
            self.assertEqual(len(result.static_detections), 3)
            self.assertTrue(result.static_summary["promo_present"])
            self.assertTrue(result.static_summary["close_button_present"])
            self.assertEqual(result.static_summary["baseline_promo_width_norm"], 300)
            self.assertTrue(all(item["promo_state"] == "collapsed" for item in result.motion_detections))
            self.assertTrue(all(item["collapsed_by_width"] for item in result.motion_detections))
            report = json.loads(result.report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["capture_method"], "fake_recording")
            self.assertEqual(len(report["step2"]["frames"]), 3)
            self.assertEqual(report["step2"]["static_scroll_distance_px"], 600)
            self.assertTrue(report["step2"]["promo_present"])
            self.assertTrue(report["step2"]["close_button_present"])
            self.assertEqual(report["step2"]["confidence_threshold"], 0.75)
            self.assertEqual(report["step2"]["static_promo_widths_norm"], [300, 250])
            self.assertEqual(report["step3"]["candidate_frame_count"], 10)
            self.assertEqual(report["step3"]["selected_frame_count"], 6)
            self.assertEqual(report["summary"]["collapsed_frame_count"], 6)
            with Image.open(result.annotated_paths[1]) as annotated:
                self.assertEqual(annotated.getpixel((65, 130)), (255, 0, 0))


if __name__ == "__main__":
    unittest.main()
