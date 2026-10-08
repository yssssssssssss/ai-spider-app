import asyncio
import json
import os
import sys
import unittest
from io import BytesIO

from PIL import Image

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)


class PromotionDetectorTests(unittest.TestCase):
    def test_detect_png_returns_normalized_promotion_and_close_button_boxes(self):
        from app.services.promotion_detector import PromotionDetector

        class FakeAnalyzer:
            providers = [{"name": "fake"}]

            async def complete_images(self, prompt, images, preferred_provider=None):
                self.prompt = prompt
                self.images = images
                self.preferred_provider = preferred_provider
                return json.dumps({
                    "promo_present": True,
                    "promo_state": "collapsed",
                    "promo_bbox_norm": [938, 787, 1000, 838],
                    "promo_description": "右侧收起促销贴片",
                    "close_button_present": False,
                    "close_button_bbox_norm": None,
                    "close_button_description": "",
                    "confidence": 0.91,
                }, ensure_ascii=False)

        buffer = BytesIO()
        Image.new("RGB", (1280, 2769), "white").save(buffer, format="PNG")
        analyzer = FakeAnalyzer()
        detector = PromotionDetector(analyzer)

        result = asyncio.run(detector.detect_png(buffer.getvalue()))

        self.assertTrue(result.promo_present)
        self.assertEqual(result.promo_state, "collapsed")
        self.assertEqual(result.promo_bbox_norm, [938, 787, 1000, 838])
        self.assertIsNone(result.close_button_bbox_norm)
        self.assertEqual(result.image_width, 1280)
        self.assertEqual(result.image_height, 2769)
        self.assertEqual(len(analyzer.images), 1)
        self.assertEqual(analyzer.preferred_provider, "openai")
        self.assertIn("0-1000", analyzer.prompt)
    def test_state_is_expanded_when_overlay_is_fully_visible_with_close_button(self):
        from app.services.promotion_detector import PromotionDetector

        class FakeAnalyzer:
            providers = [{"name": "openai"}]

            async def complete_images(self, _prompt, _images, preferred_provider=None):
                return json.dumps({
                    "promo_present": True,
                    "promo_state": "collapsed",
                    "promo_bbox_norm": [875, 768, 976, 826],
                    "close_button_present": True,
                    "close_button_bbox_norm": [916, 838, 949, 856],
                    "confidence": 0.8,
                })

        buffer = BytesIO()
        Image.new("RGB", (1280, 2769), "white").save(buffer, format="PNG")
        result = asyncio.run(PromotionDetector(FakeAnalyzer()).detect_png(buffer.getvalue()))

        self.assertEqual(result.promo_state, "expanded")

    def test_detector_retries_bottom_right_crop_and_maps_bbox_to_full_image(self):
        from app.services.promotion_detector import PromotionDetector

        class FakeAnalyzer:
            providers = [{"name": "openai"}]

            def __init__(self):
                self.calls = 0

            async def complete_images(self, _prompt, _images, preferred_provider=None):
                self.calls += 1
                if self.calls == 1:
                    return json.dumps({
                        "promo_present": True,
                        "promo_state": "expanded",
                        "promo_bbox_norm": [500, 500, 900, 600],
                        "close_button_present": False,
                        "confidence": 0.8,
                    })
                return json.dumps({
                    "promo_present": True,
                    "promo_state": "expanded",
                    "promo_bbox_norm": [600, 500, 950, 700],
                    "close_button_present": True,
                    "close_button_bbox_norm": [780, 680, 880, 760],
                    "confidence": 0.95,
                })

        buffer = BytesIO()
        Image.new("RGB", (1280, 2769), "white").save(buffer, format="PNG")
        analyzer = FakeAnalyzer()
        result = asyncio.run(PromotionDetector(analyzer).detect_png(buffer.getvalue()))

        self.assertEqual(analyzer.calls, 2)
        self.assertTrue(result.promo_present)
        self.assertEqual(result.promo_bbox_norm, [840, 775, 980, 865])
        self.assertEqual(result.close_button_bbox_norm, [912, 856, 952, 892])

    def test_detector_rejects_overlay_outside_bottom_right_region(self):
        from app.services.promotion_detector import PromotionDetector

        class FakeAnalyzer:
            providers = [{"name": "fake"}]

            async def complete_images(self, _prompt, _images, preferred_provider=None):
                self.preferred_provider = preferred_provider
                return json.dumps({
                    "promo_present": True,
                    "promo_state": "expanded",
                    "promo_bbox_norm": [837, 16, 999, 75],
                    "close_button_present": False,
                    "confidence": 0.98,
                })

        buffer = BytesIO()
        Image.new("RGB", (1080, 2400), "white").save(buffer, format="PNG")
        result = asyncio.run(PromotionDetector(FakeAnalyzer()).detect_png(buffer.getvalue()))

        self.assertFalse(result.promo_present)
        self.assertEqual(result.promo_state, "none")
        self.assertIsNone(result.promo_bbox_norm)

    def test_scroll_promo_is_a_worker_phone_mode(self):
        from app.services import worker_dispatch

        self.assertIn("scroll_promo", worker_dispatch.PHONE_TASK_MODES)
        task = type("Task", (), {"mode": "scroll_promo"})()
        self.assertTrue(worker_dispatch._task_supported(task, {"scroll_promo"}))
        self.assertFalse(worker_dispatch._task_supported(task, {"autoglm"}))

    def test_scroll_promo_config_validates_motion_window_and_candidate_count(self):
        from pydantic import ValidationError
        from app.schemas import ScrollPromoConfigInput

        config = ScrollPromoConfigInput(static_scroll_distance_px=700, fps=10, motion_window_duration_seconds=1, max_frames=6)
        self.assertEqual(config.static_scroll_distance_px, 700)
        with self.assertRaises(ValidationError):
            ScrollPromoConfigInput(dynamic_swipe_duration_seconds=1, motion_window_offset_seconds=0.5, motion_window_duration_seconds=1)
        with self.assertRaises(ValidationError):
            ScrollPromoConfigInput(fps=5, motion_window_duration_seconds=1, max_frames=6)

    def test_task_management_and_report_expose_scroll_promo_details(self):
        from pathlib import Path

        tasks_source = Path(PROJECT_ROOT, "frontend", "src", "pages", "AdminTasks.tsx").read_text(encoding="utf-8")
        report_source = Path(PROJECT_ROOT, "frontend", "src", "pages", "ScrollPromoReport.tsx").read_text(encoding="utf-8")
        request_source = Path(PROJECT_ROOT, "frontend", "src", "components", "RequestForm.tsx").read_text(encoding="utf-8")
        self.assertIn("贴片报告", tasks_source)
        self.assertIn("scroll-promo-report", tasks_source)
        self.assertIn("静态置信度阈值", report_source)
        self.assertIn("收起宽度阈值", report_source)
        self.assertIn("静态最大宽度", report_source)
        static_promo = report_source.index('<span>静态贴片</span>')
        static_close = report_source.index('<span>静态关闭按钮</span>')
        collapsed = report_source.index('<span>收起态</span>')
        self.assertLess(static_promo, static_close)
        self.assertLess(static_close, collapsed)
        self.assertIn("promo-conclusion-stack", report_source)
        self.assertIn("滑动贴片模板已载入", request_source)
        self.assertIn("scroll_promo_config_json", request_source)
        self.assertIn("最终执行计划", request_source)

    def test_task_results_keep_scroll_promo_frames_even_when_analysis_is_skipped(self):
        from pathlib import Path

        source = Path(PROJECT_ROOT, "frontend", "src", "pages", "AdminTaskResults.tsx").read_text(encoding="utf-8")
        self.assertIn("促销贴片", source)
        self.assertIn("result?.image?.scenario", source)

    def test_worker_promotion_detection_endpoint_is_token_protected(self):
        from unittest.mock import AsyncMock, patch

        from fastapi.testclient import TestClient
        from app.config import settings
        from app.main import app
        from app.services.promotion_detector import PromotionDetection, promotion_detector

        buffer = BytesIO()
        Image.new("RGB", (100, 200), "white").save(buffer, format="PNG")
        image = buffer.getvalue()
        expected = PromotionDetection(
            promo_present=True,
            promo_state="expanded",
            promo_bbox_norm=[800, 700, 980, 900],
            promo_description="促销贴片",
            close_button_present=True,
            close_button_below_promo=True,
            close_button_bbox_norm=[920, 850, 960, 890],
            close_button_description="关闭按钮",
            confidence=0.88,
            image_width=100,
            image_height=200,
        )
        old_token = settings.WORKER_API_TOKEN
        settings.WORKER_API_TOKEN = "worker-test-token"
        try:
            client = TestClient(app)
            unauthorized = client.post(
                "/api/worker/promotion-detect",
                files={"file": ("frame.png", image, "image/png")},
            )
            self.assertEqual(unauthorized.status_code, 401)

            with patch.object(promotion_detector, "detect_png", new=AsyncMock(return_value=expected)):
                response = client.post(
                    "/api/worker/promotion-detect",
                    files={"file": ("frame.png", image, "image/png")},
                    headers={"X-Worker-Token": "worker-test-token"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["promo_state"], "expanded")
            self.assertEqual(response.json()["close_button_bbox_norm"], [920, 850, 960, 890])
        finally:
            settings.WORKER_API_TOKEN = old_token


if __name__ == "__main__":
    unittest.main()
