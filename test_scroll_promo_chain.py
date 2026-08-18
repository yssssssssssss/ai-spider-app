import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image


class ScrollPromoChainTests(unittest.TestCase):
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

    def test_worker_executor_routes_scroll_promo_mode_to_chain(self):
        from worker.executor import _build_command

        command = _build_command(
            Path("/repo"),
            {"mode": "scroll_promo", "target_app": "京东"},
            "run-1",
            "task-1",
            "device-1",
            Path("/tmp/artifacts"),
        )

        self.assertIn("/repo/run_scroll_promo_chain.py", command)
        self.assertEqual(command[command.index("--package") + 1], "com.jingdong.app.mall")
        self.assertEqual(command[command.index("--max-frames") + 1], "6")

    def test_chain_keeps_at_most_six_motion_frames_and_draws_red_boxes(self):
        from worker.scroll_promo_chain import ScrollPromoChain, ScrollPromoConfig

        class FakeCapture:
            method = "fake_recording"

            def __init__(self):
                self.closed = False

            def open_app(self, package, device_serial, wait_seconds):
                self.opened = (package, device_serial)

            def capture_swipe(self, config, scratch_dir):
                frames = []
                for index in range(10):
                    path = scratch_dir / f"frame-{index:02d}.png"
                    Image.new("RGB", (100, 200), (index * 20, 30, 40)).save(path)
                    frames.append(path)
                return frames

            def close_app(self, package, device_serial):
                self.closed = True

        def detect(_path):
            return {
                "promo_present": True,
                "promo_state": "collapsed",
                "promo_bbox_norm": [800, 700, 980, 900],
                "promo_description": "促销贴片",
                "close_button_present": False,
                "close_button_bbox_norm": None,
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
                )
            )

            self.assertEqual(len(result.annotated_paths), 6)
            self.assertTrue(capture.closed)
            self.assertTrue(all(path.exists() for path in result.annotated_paths))
            self.assertTrue(all(item["promo_state"] == "collapsed" for item in result.detections))
            report = json.loads(result.report_path.read_text(encoding="utf-8"))
            self.assertEqual(report["capture_method"], "fake_recording")
            self.assertEqual(report["selected_frame_count"], 6)
            with Image.open(result.annotated_paths[0]) as annotated:
                self.assertEqual(annotated.getpixel((80, 140)), (255, 0, 0))


if __name__ == "__main__":
    unittest.main()
