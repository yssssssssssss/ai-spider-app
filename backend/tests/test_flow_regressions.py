import asyncio
import os
import sys
import unittest
import base64
import tempfile
from datetime import datetime, timedelta
from io import BytesIO
from types import SimpleNamespace


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)


class FlowRegressionTests(unittest.TestCase):
    def test_image_out_exposes_task_id(self):
        from app.schemas import ImageOut

        self.assertIn("task_id", ImageOut.model_fields)

    def test_oss_public_url_quotes_object_key_segments(self):
        from app.services.oss_uploader import OssUploader

        uploader = OssUploader(
            endpoint="https://s3.example.com",
            bucket="bucket",
            access_key_id="ak",
            secret_access_key="sk",
        )

        url = uploader._build_public_url("uploads/screenshots/中文 file.png")

        self.assertEqual(
            url,
            "https://s3.example.com/bucket/uploads/screenshots/%E4%B8%AD%E6%96%87%20file.png",
        )

    def test_llm_analyzer_resolves_relative_paths_from_project_root(self):
        from app.config import settings
        from app.services.llm_analyzer import LLMAnalyzer

        analyzer = LLMAnalyzer()

        self.assertEqual(
            analyzer._resolve_image_path("data/demo.png"),
            os.path.join(settings.PROJECT_ROOT, "data", "demo.png"),
        )

    def test_llm_analyzer_uses_modelscope_vlm_when_vlm_key_missing(self):
        from app.config import settings
        from app.services.llm_analyzer import LLMAnalyzer

        old_values = {
            "VLM_API_KEY": settings.VLM_API_KEY,
            "PHONE_AGENT_API_KEY": settings.PHONE_AGENT_API_KEY,
            "PHONE_AGENT_BASE_URL": settings.PHONE_AGENT_BASE_URL,
            "PHONE_AGENT_MODEL": settings.PHONE_AGENT_MODEL,
            "MODELSCOPE_VLM_MODEL": settings.MODELSCOPE_VLM_MODEL,
        }
        try:
            settings.VLM_API_KEY = ""
            settings.PHONE_AGENT_API_KEY = "phone-key"
            settings.PHONE_AGENT_BASE_URL = "https://phone.example/v1"
            settings.PHONE_AGENT_MODEL = "phone-vlm"
            settings.MODELSCOPE_VLM_MODEL = "modelscope-vlm"

            analyzer = LLMAnalyzer()

            self.assertEqual(analyzer.api_key, "phone-key")
            self.assertEqual(analyzer.base_url, "https://phone.example/v1")
            self.assertEqual(analyzer.model, "modelscope-vlm")
        finally:
            for name, value in old_values.items():
                setattr(settings, name, value)

    def test_llm_analyzer_downscales_large_phone_screenshots(self):
        from PIL import Image
        from app.services.llm_analyzer import LLMAnalyzer, MAX_VLM_IMAGE_SIDE

        analyzer = LLMAnalyzer()
        with tempfile.NamedTemporaryFile(suffix=".png") as temp:
            Image.new("RGB", (1080, 2400), "white").save(temp.name)
            encoded = analyzer._encode_image(temp.name)

        decoded = base64.b64decode(encoded)
        with Image.open(BytesIO(decoded)) as img:
            self.assertLessEqual(max(img.size), MAX_VLM_IMAGE_SIDE)
            self.assertEqual(img.size, (921, 2048))

    def test_llm_analyzer_parses_concatenated_chunk_response(self):
        import json
        from app.services.llm_analyzer import LLMAnalyzer

        analyzer = LLMAnalyzer()
        chunk_1 = {"choices": [{"delta": {"content": "设计"}}]}
        chunk_2 = {"choices": [{"delta": {"content": "分析"}}]}

        content = analyzer._response_content(json.dumps(chunk_1) + json.dumps(chunk_2))

        self.assertEqual(content, "设计分析")

    def test_llm_analyzer_extracts_finish_wrapped_sections(self):
        from app.services.llm_analyzer import LLMAnalyzer

        analyzer = LLMAnalyzer()
        text = 'finish(message="任务完成！\\n\\n**设计分析：**\\n布局清晰。\\n\\n**运营分析：**\\n促销明显。")'

        stripped = analyzer._strip_finish_wrapper(text)
        parsed = analyzer._extract_text_sections(stripped)

        self.assertEqual(parsed["design_analysis"], "布局清晰。")
        self.assertEqual(parsed["ops_analysis"], "促销明显。")

    def test_llm_analyzer_extracts_markdown_sections_with_parenthetical_titles(self):
        from app.services.llm_analyzer import LLMAnalyzer

        analyzer = LLMAnalyzer()
        text = "## **设计分析（UI布局、交互细节等）**\n布局清晰。\n\n## **运营分析（促销策略、价格策略等）**\n促销明显。"

        parsed = analyzer._extract_text_sections(text)

        self.assertEqual(parsed["design_analysis"], "布局清晰。")
        self.assertEqual(parsed["ops_analysis"], "促销明显。")

    def test_collector_ignores_temp_screenshots(self):
        from app.services.collector_bridge import _is_collectable_image_file

        self.assertFalse(_is_collectable_image_file("_temp_step_4.png"))
        self.assertTrue(_is_collectable_image_file("autoglm_step_4.png"))

    def test_task_images_filter_hides_temp_screenshots(self):
        from app.routers.admin import _is_visible_task_image

        self.assertFalse(_is_visible_task_image(SimpleNamespace(file_path="data/task/autoglm/_temp_step_4.png")))
        self.assertTrue(_is_visible_task_image(SimpleNamespace(file_path="data/task/autoglm/autoglm_step_4.png")))

    def test_progress_visible_image_filter_matches_task_images_filter(self):
        from app.routers.admin import _is_visible_task_image

        images = [
            SimpleNamespace(file_path="data/task/autoglm/_temp_step_4.png"),
            SimpleNamespace(file_path="data/task/autoglm/autoglm_step_4.png"),
        ]

        self.assertEqual(sum(1 for image in images if _is_visible_task_image(image)), 1)

    def test_autoglm_max_steps_setting_defaults_to_bounded_run(self):
        from app.config import settings

        self.assertGreater(settings.AUTOGLM_MAX_STEPS, 0)
        self.assertLessEqual(settings.AUTOGLM_MAX_STEPS, 10)

    def test_llm_analyzer_prompt_includes_focus_question(self):
        from app.services.llm_analyzer import LLMAnalyzer

        prompt = LLMAnalyzer()._build_analysis_prompt({
            "target_app": "淘宝",
            "target_scenario": "大促弹窗",
            "keywords": ["红包", "限时优惠"],
            "focus_question": "只看红色弹窗利益点",
        })

        self.assertIn("目标App：淘宝", prompt)
        self.assertIn("目标场景：大促弹窗", prompt)
        self.assertIn("关键词/关注点：红包、限时优惠", prompt)
        self.assertIn("关注问题：只看红色弹窗利益点", prompt)

    def test_analyze_and_embed_skips_non_target_images(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.routers import images as images_router

        class FakeAnalyzer:
            def __init__(self):
                self.context = None

            async def is_target_page(self, image_path, context):
                self.context = context
                return False, "当前截图是启动页，不是目标弹窗"

            async def analyze(self, image_path, context=None):
                raise AssertionError("non-target image should not be analyzed")

        fake_analyzer = FakeAnalyzer()
        old_analyzer = images_router.analyzer
        images_router.analyzer = fake_analyzer

        db = SessionLocal()
        request = task = image = None
        try:
            request = crud.create_request(db, schemas.RequestCreate(
                target_app="淘宝",
                target_scenario="大促弹窗",
                keywords=["红包"],
                description="只看红色弹窗利益点",
            ))
            task = crud.create_task(
                db,
                name="target-filter-test",
                keyword="红包",
                target_app="淘宝",
                target_scenario="大促弹窗",
                request_id=request.id,
            )
            image = crud.create_image(db, schemas.ImageCreate(
                file_path="data/target-filter-test.png",
                task_id=task.id,
            ))

            asyncio.run(images_router._analyze_and_embed(image.id))
            db.refresh(image)
            analysis = crud.get_analysis_by_image(db, image.id)

            self.assertEqual(analysis.status, "skipped")
            self.assertIn("不是目标弹窗", analysis.ops_analysis)
            self.assertEqual(fake_analyzer.context["focus_question"], "只看红色弹窗利益点")
        finally:
            images_router.analyzer = old_analyzer
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.delete(analysis)
                db.delete(image)
            if task:
                db.delete(task)
            if request:
                db.delete(request)
            db.commit()
            db.close()

    def test_near_duplicate_pages_are_skipped_before_llm_analysis(self):
        from PIL import Image
        from app import crud, schemas
        from app.database import SessionLocal
        from app.routers import images as images_router

        class FakeAnalyzer:
            async def is_target_page(self, image_path, context):
                return True, "目标页"

            async def analyze(self, image_path, context=None):
                return "设计分析", "运营分析", "success"

        old_analyzer = images_router.analyzer
        images_router.analyzer = FakeAnalyzer()

        db = SessionLocal()
        request = task = first = second = None
        first_path = os.path.join(PROJECT_ROOT, "data", "duplicate-test-1.png")
        second_path = os.path.join(PROJECT_ROOT, "data", "duplicate-test-2.png")
        os.makedirs(os.path.dirname(first_path), exist_ok=True)
        try:
            Image.new("RGB", (80, 120), "white").save(first_path)
            Image.new("RGB", (80, 120), "white").save(second_path)

            request = crud.create_request(db, schemas.RequestCreate(target_app="淘宝", target_scenario="秒杀页"))
            task = crud.create_task(db, name="duplicate-test", keyword="", target_app="淘宝", target_scenario="秒杀页", request_id=request.id)
            first = crud.create_image(db, schemas.ImageCreate(file_path="data/duplicate-test-1.png", task_id=task.id))
            second = crud.create_image(db, schemas.ImageCreate(file_path="data/duplicate-test-2.png", task_id=task.id))

            asyncio.run(images_router._analyze_and_embed(first.id))
            asyncio.run(images_router._analyze_and_embed(second.id))

            first_analysis = crud.get_analysis_by_image(db, first.id)
            second_analysis = crud.get_analysis_by_image(db, second.id)

            self.assertEqual(first_analysis.status, "success")
            self.assertEqual(second_analysis.status, "skipped")
            self.assertIn("近似页面", second_analysis.ops_analysis)
        finally:
            images_router.analyzer = old_analyzer
            for image in (second, first):
                if image:
                    analysis = crud.get_analysis_by_image(db, image.id)
                    if analysis:
                        db.delete(analysis)
                    db.delete(image)
            if task:
                db.delete(task)
            if request:
                db.delete(request)
            db.commit()
            db.close()
            for path in (first_path, second_path):
                if os.path.exists(path):
                    os.remove(path)

    def test_popup_state_machine_switches_close_strategy_after_repeated_failures(self):
        import importlib.util

        sys.path.insert(0, PROJECT_ROOT)
        spec = importlib.util.spec_from_file_location("run_autoglm_module", os.path.join(PROJECT_ROOT, "run_autoglm.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        machine = module.PopupFlowStateMachine("如果有弹窗先截图，然后关闭弹窗后再截图")

        self.assertEqual(machine.next_instruction(finished=False), None)
        machine.record_close_attempt(changed=False)
        self.assertIn("返回键", machine.next_instruction(finished=False))

    def test_keyword_instruction_searches_only_for_search_scenes(self):
        from app.services.task_planner import keyword_instruction, requires_popup_close_flow, append_execution_rules

        self.assertEqual(keyword_instruction(["蓝牙耳机", "618"], "搜索结果页"), "搜索'蓝牙耳机、618'")
        self.assertEqual(keyword_instruction(["智能手表"], "商品详情页"), "搜索'智能手表'")
        self.assertEqual(keyword_instruction(["红包", "限时优惠"], "大促弹窗"), "重点关注'红包、限时优惠'相关内容")
        self.assertTrue(requires_popup_close_flow("如果有弹窗先截图，然后关闭弹窗后再截图"))

        prompt = append_execution_rules("打开淘宝秒杀，如果有弹窗先截图，然后关闭弹窗后再截图")

        self.assertIn("未完成弹窗页截图和关闭后页面截图前，禁止结束任务", prompt)

    def test_text_search_finds_analysis_when_embedding_is_unavailable(self):
        from app import crud, schemas
        from app.database import SessionLocal

        db = SessionLocal()
        image = None
        try:
            existing = crud.get_image_by_file_and_task(db, "data/search-fallback-demo.png", None)
            if existing:
                existing_analysis = crud.get_analysis_by_image(db, existing.id)
                if existing_analysis:
                    db.delete(existing_analysis)
                db.delete(existing)
                db.commit()

            image = crud.create_image(db, schemas.ImageCreate(file_path="data/search-fallback-demo.png"))
            crud.create_analysis(db, image.id, "蓝牙耳机卡片布局清晰", "国家补贴和618促销明显")

            rows = crud.search_by_text(db, "蓝牙耳机", limit=5)

            self.assertTrue(any(row_image.id == image.id for _, row_image in rows))
        finally:
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.delete(analysis)
                db.delete(image)
                db.commit()
            db.close()

    def test_list_tasks_orders_latest_completed_first(self):
        from app import crud
        from app.database import SessionLocal

        db = SessionLocal()
        old_task = new_task = None
        try:
            old_task = crud.create_task(db, name="old completed task", keyword="", target_app="淘宝", target_scenario="百亿补贴")
            new_task = crud.create_task(db, name="new completed task", keyword="", target_app="淘宝", target_scenario="淘宝秒杀")

            old_task.completed_at = datetime.utcnow() + timedelta(days=1)
            new_task.completed_at = datetime.utcnow() + timedelta(days=2)
            db.commit()

            tasks = crud.list_tasks(db, limit=2)

            self.assertEqual(tasks[0].id, new_task.id)
            self.assertEqual(tasks[1].id, old_task.id)
        finally:
            for task in (new_task, old_task):
                if task:
                    db.delete(task)
            db.commit()
            db.close()


if __name__ == "__main__":
    unittest.main()
