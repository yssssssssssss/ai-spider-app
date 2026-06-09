import asyncio
import json
import os
import subprocess
import sys
import unittest
import base64
import tempfile
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class FlowRegressionTests(unittest.TestCase):
    def test_analysis_skill_model_and_snapshot_fields_exist(self):
        from app import models
        from app.schemas import AnalysisOut, RequestCreate, RequestOut, TaskOut, WatchPlanCreate, WatchPlanOut

        self.assertTrue(hasattr(models, "AnalysisSkill"))
        self.assertTrue(hasattr(models.Analysis, "custom_analysis_json"))
        self.assertTrue(hasattr(models.Request, "analysis_skill_snapshots_json"))
        self.assertTrue(hasattr(models.Request, "schedule_enabled"))
        self.assertTrue(hasattr(models.Task, "scheduled_run_date"))
        self.assertTrue(hasattr(models.Task, "analysis_skill_snapshots_json"))
        self.assertTrue(hasattr(models.WatchPlan, "analysis_skill_snapshots_json"))
        self.assertTrue(hasattr(models.WatchPlan, "schedule_start_date"))
        self.assertTrue(hasattr(models.WatchPlan, "schedule_end_date"))
        self.assertTrue(hasattr(models.WatchPlan, "schedule_cycle"))
        self.assertIn("custom_analysis_json", AnalysisOut.model_fields)
        self.assertIn("analysis_skill_ids", RequestCreate.model_fields)
        self.assertIn("schedule_cycle", RequestCreate.model_fields)
        self.assertIn("schedule_enabled", RequestOut.model_fields)
        self.assertIn("analysis_skill_snapshots_json", RequestOut.model_fields)
        self.assertIn("scheduled_run_date", TaskOut.model_fields)
        self.assertIn("analysis_skill_snapshots_json", TaskOut.model_fields)
        self.assertIn("analysis_skill_ids", WatchPlanCreate.model_fields)
        self.assertIn("schedule_start_date", WatchPlanCreate.model_fields)
        self.assertIn("schedule_end_date", WatchPlanOut.model_fields)
        self.assertIn("schedule_cycle", WatchPlanOut.model_fields)
        self.assertIn("analysis_skill_snapshots_json", WatchPlanOut.model_fields)

    def test_parse_analysis_skill_markdown_uses_h1_as_name(self):
        from app.services.analysis_skills import parse_skill_markdown

        parsed = parse_skill_markdown("# 价格策略\n\n分析价格锚点、补贴、满减。")

        self.assertEqual(parsed["name"], "价格策略")
        self.assertIn("分析价格锚点", parsed["instruction_md"])

    def test_parse_analysis_skill_markdown_requires_name_without_h1(self):
        from app.services.analysis_skills import parse_skill_markdown

        parsed = parse_skill_markdown("分析会员价和限时价。", fallback_name="价格策略")

        self.assertEqual(parsed["name"], "价格策略")
        self.assertEqual(parsed["instruction_md"], "分析会员价和限时价。")

    def test_parse_analysis_skill_markdown_rejects_raw_oversize(self):
        from fastapi import HTTPException
        from app.services.analysis_skills import MAX_SKILL_MARKDOWN_LENGTH, parse_skill_markdown

        with self.assertRaises(HTTPException):
            parse_skill_markdown("# 价格策略\n" + (" " * MAX_SKILL_MARKDOWN_LENGTH))

    def test_user_can_create_and_list_own_analysis_skill(self):
        from app import crud, models
        from app.database import SessionLocal
        from app.services.auth import hash_password

        db = SessionLocal()
        username = f"skill-user-{uuid4().hex[:8]}"
        skill = None
        try:
            user = crud.create_user(db, username=username, password_hash=hash_password("pass"), role="viewer")
            skill = crud.create_analysis_skill(
                db,
                name="价格策略",
                instruction_md="# 价格策略\n分析价格。",
                owner_id=user.id,
            )

            rows = crud.list_visible_analysis_skills(db, user)

            self.assertIn(skill.id, [row.id for row in rows])
        finally:
            if skill:
                db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id == skill.id).delete()
            db.query(models.User).filter(models.User.username == username).delete()
            db.commit()
            db.close()

    def test_admin_can_mark_analysis_skill_official(self):
        from app import crud, models
        from app.database import SessionLocal
        from app.services.auth import hash_password

        db = SessionLocal()
        username = f"skill-admin-{uuid4().hex[:8]}"
        skill = None
        try:
            user = crud.create_user(db, username=username, password_hash=hash_password("pass"), role="admin")
            skill = crud.create_analysis_skill(
                db,
                name="价格策略",
                instruction_md="# 价格策略\n分析价格。",
                owner_id=user.id,
            )

            updated = crud.update_analysis_skill(db, skill.id, is_official=True)

            self.assertTrue(updated.is_official)
        finally:
            if skill:
                db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id == skill.id).delete()
            db.query(models.User).filter(models.User.username == username).delete()
            db.commit()
            db.close()

    def test_analysis_skill_update_rejects_invalid_values(self):
        from fastapi.testclient import TestClient
        from app import crud, models
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password

        db = SessionLocal()
        username = f"skill-update-{uuid4().hex[:8]}"
        user = skill = None
        try:
            user = crud.create_user(db, username=username, password_hash=hash_password("pass"), role="viewer")
            skill = crud.create_analysis_skill(
                db,
                name="价格策略",
                instruction_md="# 价格策略\n分析价格。",
                owner_id=user.id,
            )
            client = TestClient(app)
            headers = {"Authorization": f"Bearer {create_access_token(user)}"}

            empty_name = client.patch(
                f"/api/analysis-skills/{skill.id}",
                headers=headers,
                json={"name": ""},
            )
            bad_status = client.patch(
                f"/api/analysis-skills/{skill.id}",
                headers=headers,
                json={"status": "archived"},
            )

            self.assertEqual(empty_name.status_code, 400)
            self.assertEqual(bad_status.status_code, 400)
        finally:
            if skill:
                db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id == skill.id).delete()
            if user:
                db.delete(user)
            db.commit()
            db.close()

    def test_admin_mark_analysis_skill_official_rejects_duplicate_name(self):
        from fastapi.testclient import TestClient
        from app import crud, models
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password

        db = SessionLocal()
        suffix = uuid4().hex[:8]
        admin = official = custom = None
        try:
            admin = crud.create_user(
                db,
                username=f"skill-admin-conflict-{suffix}",
                password_hash=hash_password("pass"),
                role="admin",
            )
            name = f"价格策略-{suffix}"
            official = crud.create_analysis_skill(
                db,
                name=name,
                instruction_md=f"# {name}\n官方规则。",
                owner_id=None,
                is_official=True,
            )
            custom = crud.create_analysis_skill(
                db,
                name=name,
                instruction_md=f"# {name}\n自定义规则。",
                owner_id=admin.id,
            )
            client = TestClient(app)
            response = client.patch(
                f"/api/admin/analysis-skills/{custom.id}/official",
                headers={"Authorization": f"Bearer {create_access_token(admin)}"},
                json={"is_official": True},
            )

            self.assertEqual(response.status_code, 409)
        finally:
            for skill in (custom, official):
                if skill:
                    db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id == skill.id).delete()
            if admin:
                db.delete(admin)
            db.commit()
            db.close()

    def test_admin_can_create_analysis_skill_via_api(self):
        from fastapi.testclient import TestClient
        from app import crud, models
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password

        db = SessionLocal()
        admin = None
        skill_id = None
        try:
            admin = crud.create_user(
                db,
                username=f"skill-admin-create-{uuid4().hex[:8]}",
                password_hash=hash_password("pass"),
                role="admin",
            )
            client = TestClient(app)
            response = client.post(
                "/api/admin/analysis-skills",
                headers={"Authorization": f"Bearer {create_access_token(admin)}"},
                json={"name": "价格策略", "instruction_md": "# 价格策略\n分析价格。"},
            )

            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["owner_id"], None)
            skill_id = UUID(response.json()["id"])
        finally:
            if skill_id:
                db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id == skill_id).delete()
            if admin:
                db.delete(admin)
            db.commit()
            db.close()

    def test_admin_created_analysis_skill_is_selectable_on_request_form(self):
        from fastapi.testclient import TestClient
        from app import crud, models
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password

        db = SessionLocal()
        admin = None
        skill_id = None
        request_id = None
        try:
            admin = crud.create_user(
                db,
                username=f"skill-admin-select-{uuid4().hex[:8]}",
                password_hash=hash_password("pass"),
                role="admin",
            )
            client = TestClient(app)
            headers = {"Authorization": f"Bearer {create_access_token(admin)}"}
            name = f"价格策略-{uuid4().hex[:8]}"
            created = client.post(
                "/api/admin/analysis-skills",
                headers=headers,
                json={"name": name, "instruction_md": f"# {name}\n分析价格和补贴。"},
            )
            self.assertEqual(created.status_code, 200, created.text)
            skill_id = UUID(created.json()["id"])

            visible = client.get("/api/analysis-skills", headers=headers)
            self.assertEqual(visible.status_code, 200, visible.text)
            self.assertIn(str(skill_id), [row["id"] for row in visible.json()])

            submitted = client.post(
                "/api/requests",
                headers=headers,
                json={
                    "target_app": "淘宝",
                    "target_scenario": "搜索页",
                    "analysis_skill_ids": [str(skill_id)],
                },
            )
            self.assertEqual(submitted.status_code, 200, submitted.text)
            request_id = UUID(submitted.json()["id"])
            self.assertEqual(submitted.json()["analysis_skill_snapshots_json"][0]["name"], name)
        finally:
            if request_id:
                req = crud.get_request(db, request_id)
                if req:
                    db.delete(req)
            if skill_id:
                db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id == skill_id).delete()
            if admin:
                db.delete(admin)
            db.commit()
            db.close()

    def test_request_interpret_endpoint_returns_structured_fields(self):
        from fastapi.testclient import TestClient
        from app import crud
        from app.database import SessionLocal
        from app.main import app
        from app.routers import requests as requests_router
        from app.services.auth import create_access_token, hash_password

        async def fake_interpret_request_text(natural_language: str):
            return {
                "target_app": "淘宝、拼多多",
                "target_scenario": "淘宝百亿补贴会场、拼多多百亿补贴会场",
                "keywords": ["百亿补贴"],
                "description": "请依次打开淘宝和拼多多，分别进入百亿补贴会场并截图保存。",
            }

        db = SessionLocal()
        user = None
        previous = getattr(requests_router, "interpret_request_text", None)
        requests_router.interpret_request_text = fake_interpret_request_text
        try:
            user = crud.create_user(
                db,
                username=f"interpret-user-{uuid4().hex[:8]}",
                password_hash=hash_password("pass"),
                role="viewer",
            )
            client = TestClient(app)
            response = client.post(
                "/api/requests/interpret",
                headers={"Authorization": f"Bearer {create_access_token(user)}"},
                json={"natural_language": "打开淘宝和拼多多，然后进入百亿补贴会场，分别截图。"},
            )

            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body["target_app"], "淘宝、拼多多")
            self.assertEqual(body["keywords"], ["百亿补贴"])
            self.assertIn("拼多多", body["target_scenario"])
        finally:
            if previous is None:
                delattr(requests_router, "interpret_request_text")
            else:
                requests_router.interpret_request_text = previous
            if user:
                db.delete(user)
            db.commit()
            db.close()

    def test_request_interpreter_normalizes_llm_json(self):
        from app.services import request_interpreter

        class FakeCompletions:
            def create(self, **kwargs):
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=json.dumps({
                                    "target_app": "淘宝、拼多多",
                                    "target_scenario": "淘宝百亿补贴会场、拼多多百亿补贴会场",
                                    "keywords": "百亿补贴，补贴入口",
                                    "description": "两个会场都必须截图。",
                                }, ensure_ascii=False)
                            )
                        )
                    ]
                )

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        previous = request_interpreter._planner_client
        request_interpreter._planner_client = lambda: (fake_client, "fake-model")
        try:
            result = asyncio.run(request_interpreter.interpret_request_text("打开淘宝和拼多多，进入百亿补贴会场截图"))

            self.assertEqual(result["target_app"], "淘宝、拼多多")
            self.assertEqual(result["keywords"], ["百亿补贴", "补贴入口"])
            self.assertIn("拼多多", result["target_scenario"])
        finally:
            request_interpreter._planner_client = previous

    def test_request_interpreter_backfills_missing_scene_from_text(self):
        from app.services import request_interpreter

        class FakeCompletions:
            def create(self, **kwargs):
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=json.dumps({
                                    "target_app": "淘宝、拼多多",
                                    "target_scenario": "",
                                    "keywords": [],
                                    "description": "打开淘宝、拼多多，打开百亿会场截图",
                                }, ensure_ascii=False)
                            )
                        )
                    ]
                )

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        previous = request_interpreter._planner_client
        request_interpreter._planner_client = lambda: (fake_client, "fake-model")
        try:
            result = asyncio.run(request_interpreter.interpret_request_text("打开淘宝、拼多多，打开百亿会场截图"))

            self.assertEqual(result["target_app"], "淘宝、拼多多")
            self.assertIn("淘宝百亿会场", result["target_scenario"])
            self.assertIn("拼多多百亿会场", result["target_scenario"])
            self.assertIn("百亿会场", result["keywords"])
        finally:
            request_interpreter._planner_client = previous

    def test_jd_cloud_gpt55_chat_options_omit_temperature(self):
        from app.services.task_planner import chat_completion_options

        options = chat_completion_options(
            base_url="https://modelservice.jdcloud.com/v1/",
            model_name="GPT-5.5",
            model="GPT-5.5",
            messages=[],
            temperature=0.3,
            max_tokens=16,
        )

        self.assertNotIn("temperature", options)
        self.assertEqual(options["model"], "GPT-5.5")

    def test_non_jd_cloud_chat_options_keep_temperature(self):
        from app.services.task_planner import chat_completion_options

        options = chat_completion_options(
            base_url="https://api-inference.modelscope.cn/v1",
            model_name="Qwen/Qwen3-VL-8B-Instruct",
            model="Qwen/Qwen3-VL-8B-Instruct",
            messages=[],
            temperature=0.1,
            max_tokens=16,
        )

        self.assertEqual(options["temperature"], 0.1)

    def test_plan_task_falls_back_when_model_returns_empty_instruction(self):
        from app.services import task_planner

        class FakeCompletions:
            def create(self, **kwargs):
                return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=""))])

        fake_client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
        previous = task_planner._planner_client
        task_planner._planner_client = lambda: (fake_client, "fake-model")
        try:
            instruction = asyncio.run(task_planner.plan_task(
                target_app="淘宝",
                target_scenario="首页和百亿补贴会场",
                keywords=[],
                description=None,
            ))
        finally:
            task_planner._planner_client = previous

        self.assertIn("打开淘宝App", instruction)
        self.assertIn("找到首页和百亿补贴会场", instruction)
        self.assertFalse(instruction.startswith("，"))

    def test_admin_update_official_analysis_skill_rejects_duplicate_name(self):
        from fastapi.testclient import TestClient
        from app import crud, models
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password

        db = SessionLocal()
        suffix = uuid4().hex[:8]
        admin = left = right = None
        try:
            admin = crud.create_user(
                db,
                username=f"skill-admin-patch-conflict-{suffix}",
                password_hash=hash_password("pass"),
                role="admin",
            )
            left = crud.create_analysis_skill(
                db,
                name=f"官方策略A-{suffix}",
                instruction_md=f"# 官方策略A-{suffix}\n官方规则。",
                owner_id=None,
                is_official=True,
            )
            right = crud.create_analysis_skill(
                db,
                name=f"官方策略B-{suffix}",
                instruction_md=f"# 官方策略B-{suffix}\n官方规则。",
                owner_id=None,
                is_official=True,
            )
            client = TestClient(app)
            response = client.patch(
                f"/api/admin/analysis-skills/{right.id}",
                headers={"Authorization": f"Bearer {create_access_token(admin)}"},
                json={"instruction_md": f"# 官方策略A-{suffix}\n改名冲突。"},
            )

            self.assertEqual(response.status_code, 409)
        finally:
            for skill in (right, left):
                if skill:
                    db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id == skill.id).delete()
            if admin:
                db.delete(admin)
            db.commit()
            db.close()

    def test_request_creation_stores_analysis_skill_snapshots(self):
        from app import crud, models, schemas
        from app.database import SessionLocal
        from app.services.auth import hash_password
        from app.services.analysis_skills import build_skill_snapshots

        db = SessionLocal()
        username = f"snapshot-user-{uuid4().hex[:8]}"
        user = skill = req = None
        try:
            user = crud.create_user(db, username=username, password_hash=hash_password("pass"), role="viewer")
            skill = crud.create_analysis_skill(db, name="价格策略", instruction_md="# 价格策略\n分析价格。", owner_id=user.id)
            snapshots = build_skill_snapshots(db, [skill.id], user)
            req = crud.create_request(
                db,
                schemas.RequestCreate(
                    target_app="淘宝",
                    target_scenario="搜索页",
                    keywords=[],
                    description="",
                    analysis_skill_ids=[skill.id],
                ),
                user_id=str(user.id),
                analysis_skill_snapshots=snapshots,
            )

            self.assertEqual(req.analysis_skill_snapshots_json[0]["name"], "价格策略")
        finally:
            if req:
                db.delete(req)
            if skill:
                db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id == skill.id).delete()
            if user:
                db.delete(user)
            db.commit()
            db.close()

    def test_approve_request_copies_analysis_skill_snapshots_to_task(self):
        from app import crud, models, schemas
        from app.database import SessionLocal
        from app.services.auth import hash_password

        db = SessionLocal()
        username = f"copy-snapshot-{uuid4().hex[:8]}"
        user = req = task = None
        snapshot = {"skill_id": "x", "name": "价格策略", "instruction_md": "# 价格策略", "is_official": False}
        try:
            user = crud.create_user(db, username=username, password_hash=hash_password("pass"), role="viewer")
            req = crud.create_request(
                db,
                schemas.RequestCreate(target_app="淘宝", target_scenario="搜索页", keywords=[], description=""),
                user_id=str(user.id),
                analysis_skill_snapshots=[snapshot],
            )
            task = crud.create_task(
                db,
                name="Task",
                keyword="",
                target_app="淘宝",
                target_scenario="搜索页",
                request_id=req.id,
                analysis_skill_snapshots=req.analysis_skill_snapshots_json,
            )

            self.assertEqual(task.analysis_skill_snapshots_json[0]["name"], "价格策略")
        finally:
            if task:
                db.delete(task)
            if req:
                db.delete(req)
            if user:
                db.delete(user)
            db.commit()
            db.close()

    def test_request_api_rejects_unavailable_analysis_skill(self):
        from fastapi.testclient import TestClient
        from app import crud, models
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password

        db = SessionLocal()
        owner = other = skill = None
        try:
            owner = crud.create_user(db, username=f"skill-owner-{uuid4().hex[:8]}", password_hash=hash_password("pass"), role="viewer")
            other = crud.create_user(db, username=f"skill-other-{uuid4().hex[:8]}", password_hash=hash_password("pass"), role="viewer")
            skill = crud.create_analysis_skill(db, name="价格策略", instruction_md="# 价格策略\n分析价格。", owner_id=owner.id)
            client = TestClient(app)
            response = client.post(
                "/api/requests",
                headers={"Authorization": f"Bearer {create_access_token(other)}"},
                json={"target_app": "淘宝", "target_scenario": "搜索页", "analysis_skill_ids": [str(skill.id)]},
            )

            self.assertEqual(response.status_code, 400)
        finally:
            if skill:
                db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id == skill.id).delete()
            for user in (owner, other):
                if user:
                    db.delete(user)
            db.commit()
            db.close()

    def test_request_api_defaults_to_official_analysis_skill_snapshots(self):
        from fastapi.testclient import TestClient
        from app import crud, models
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password

        db = SessionLocal()
        user = request = None
        created_defaults = []
        try:
            for name in ("设计维度", "运营维度"):
                existing = crud.get_official_analysis_skill_by_name(db, name)
                if existing:
                    continue
                created_defaults.append(crud.create_analysis_skill(
                    db,
                    name=name,
                    instruction_md=f"# {name}\n默认规则。",
                    owner_id=None,
                    is_official=True,
                ))
            user = crud.create_user(
                db,
                username=f"default-skill-{uuid4().hex[:8]}",
                password_hash=hash_password("pass"),
                role="viewer",
            )
            client = TestClient(app)
            response = client.post(
                "/api/requests",
                headers={"Authorization": f"Bearer {create_access_token(user)}"},
                json={"target_app": "淘宝", "target_scenario": "搜索页"},
            )

            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            names = [row["name"] for row in body["analysis_skill_snapshots_json"]]
            self.assertEqual(names[:2], ["设计维度", "运营维度"])
            request = crud.get_request(db, UUID(body["id"]))
        finally:
            if request:
                db.delete(request)
            if user:
                db.delete(user)
            for skill in created_defaults:
                db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id == skill.id).delete()
            db.commit()
            db.close()

    def test_request_api_accepts_explicit_official_non_default_analysis_skill_snapshot(self):
        from fastapi.testclient import TestClient
        from app import crud, models
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password

        db = SessionLocal()
        suffix = uuid4().hex[:8]
        user = skill = request = None
        try:
            user = crud.create_user(
                db,
                username=f"official-skill-{suffix}",
                password_hash=hash_password("pass"),
                role="viewer",
            )
            skill = crud.create_analysis_skill(
                db,
                name=f"价格策略-{suffix}",
                instruction_md=f"# 价格策略-{suffix}\n分析价格。",
                owner_id=None,
                is_official=True,
            )
            client = TestClient(app)
            response = client.post(
                "/api/requests",
                headers={"Authorization": f"Bearer {create_access_token(user)}"},
                json={
                    "target_app": "淘宝",
                    "target_scenario": "搜索页",
                    "analysis_skill_ids": [str(skill.id)],
                },
            )

            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body["analysis_skill_snapshots_json"][0]["name"], skill.name)
            request = crud.get_request(db, UUID(body["id"]))
        finally:
            if request:
                db.delete(request)
            if skill:
                db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id == skill.id).delete()
            if user:
                db.delete(user)
            db.commit()
            db.close()

    def test_request_api_rejects_disabled_analysis_skill_snapshot(self):
        from fastapi.testclient import TestClient
        from app import crud, models
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password

        db = SessionLocal()
        user = skill = None
        try:
            user = crud.create_user(
                db,
                username=f"disabled-skill-{uuid4().hex[:8]}",
                password_hash=hash_password("pass"),
                role="viewer",
            )
            skill = crud.create_analysis_skill(
                db,
                name="价格策略",
                instruction_md="# 价格策略\n分析价格。",
                owner_id=user.id,
                status="disabled",
            )
            client = TestClient(app)
            response = client.post(
                "/api/requests",
                headers={"Authorization": f"Bearer {create_access_token(user)}"},
                json={
                    "target_app": "淘宝",
                    "target_scenario": "搜索页",
                    "analysis_skill_ids": [str(skill.id)],
                },
            )

            self.assertEqual(response.status_code, 400)
        finally:
            if skill:
                db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id == skill.id).delete()
            if user:
                db.delete(user)
            db.commit()
            db.close()

    def test_watch_plan_creation_stores_analysis_skill_snapshots(self):
        from fastapi.testclient import TestClient
        from app import crud, models
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password

        db = SessionLocal()
        operator = skill = plan = None
        try:
            operator = crud.create_user(
                db,
                username=f"watch-skill-{uuid4().hex[:8]}",
                password_hash=hash_password("pass"),
                role="operator",
            )
            skill = crud.create_analysis_skill(db, name="价格策略", instruction_md="# 价格策略\n分析价格。", owner_id=operator.id)
            client = TestClient(app)
            response = client.post(
                "/api/admin/watch-plans",
                headers={"Authorization": f"Bearer {create_access_token(operator)}"},
                json={
                    "name": "每日观察",
                    "target_app": "淘宝",
                    "target_page": "搜索页",
                    "entry_instruction": "打开淘宝进入搜索页",
                    "analysis_skill_ids": [str(skill.id)],
                },
            )

            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body["analysis_skill_snapshots_json"][0]["name"], "价格策略")
            plan = crud.get_watch_plan(db, UUID(body["id"]))
            listed = client.get(
                "/api/admin/watch-plans",
                headers={"Authorization": f"Bearer {create_access_token(operator)}"},
            )
            detail = client.get(
                f"/api/admin/watch-plans/{plan.id}",
                headers={"Authorization": f"Bearer {create_access_token(operator)}"},
            )
            self.assertEqual(listed.status_code, 200, listed.text)
            listed_plan = next(row for row in listed.json() if row["id"] == str(plan.id))
            self.assertIn("价格策略", [row["name"] for row in listed_plan["analysis_skill_snapshots_json"]])
            self.assertEqual(detail.status_code, 200, detail.text)
            self.assertEqual(detail.json()["plan"]["analysis_skill_snapshots_json"][0]["name"], "价格策略")
        finally:
            if plan:
                db.delete(plan)
            if skill:
                db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id == skill.id).delete()
            if operator:
                db.delete(operator)
            db.commit()
            db.close()

    def test_manage_clean_accepts_explicit_dry_run_flag(self):
        result = subprocess.run(
            [sys.executable, "manage.py", "clean", "--dry-run", "--no-logs", "--no-pycache"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_manage_reconcile_statuses_accepts_dry_run(self):
        result = subprocess.run(
            [sys.executable, "manage.py", "reconcile-statuses"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("收口任务状态", result.stdout)

    def test_manage_clean_dry_run_lists_allowed_generated_files_only(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("manage_module", os.path.join(PROJECT_ROOT, "manage.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".backend.log").write_text("log", encoding="utf-8")
            (root / "backend" / "app" / "__pycache__").mkdir(parents=True)
            (root / "backend" / "app" / "__pycache__" / "models.pyc").write_bytes(b"pyc")
            (root / "backend" / ".env").parent.mkdir(parents=True, exist_ok=True)
            (root / "backend" / ".env").write_text("SECRET=value", encoding="utf-8")
            (root / "data").mkdir()
            (root / "data" / "business.png").write_bytes(b"image")

            planned = module.plan_clean(root, logs=True, pycache=True, dist=False, exports=False)
            rel_paths = {path.relative_to(root).as_posix() for path in planned}

            self.assertIn(".backend.log", rel_paths)
            self.assertIn("backend/app/__pycache__", rel_paths)
            self.assertNotIn("backend/.env", rel_paths)
            self.assertNotIn("data/business.png", rel_paths)
            self.assertTrue((root / ".backend.log").exists())
            self.assertTrue((root / "backend" / "app" / "__pycache__").exists())

    def test_manage_clean_apply_removes_only_planned_files(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("manage_module", os.path.join(PROJECT_ROOT, "manage.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".frontend.log").write_text("log", encoding="utf-8")
            (root / "exports").mkdir()
            (root / "exports" / "report.json").write_text("{}", encoding="utf-8")
            (root / "data").mkdir()
            (root / "data" / "keep.png").write_bytes(b"image")

            removed = module.clean_generated_files(root, apply=True, logs=True, pycache=False, dist=False, exports=True)
            rel_removed = {path.relative_to(root).as_posix() for path in removed}

            self.assertIn(".frontend.log", rel_removed)
            self.assertIn("exports", rel_removed)
            self.assertFalse((root / ".frontend.log").exists())
            self.assertFalse((root / "exports").exists())
            self.assertTrue((root / "data" / "keep.png").exists())

    def test_task_run_backfill_skips_active_tasks_without_runs(self):
        from app import crud, models
        from app.database import SessionLocal, _ensure_task_runs_backfill

        db = SessionLocal()
        task = None
        try:
            task = crud.create_task(
                db,
                name=f"active-no-run-{uuid4().hex}",
                keyword="",
                target_app="京东",
                target_scenario="首页",
            )

            _ensure_task_runs_backfill(db.connection())

            runs = db.query(models.TaskRun).filter(models.TaskRun.task_id == task.id).all()
            self.assertEqual(runs, [])
        finally:
            if task:
                db.delete(task)
            db.commit()
            db.close()

    def test_manage_prune_task_logs_keeps_recent_logs(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("manage_module", os.path.join(PROJECT_ROOT, "manage.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            old_log = root / "logs" / "tasks" / "task-a" / "old.log"
            recent_log = root / "logs" / "tasks" / "task-b" / "recent.log"
            old_log.parent.mkdir(parents=True)
            recent_log.parent.mkdir(parents=True)
            old_log.write_text("old", encoding="utf-8")
            recent_log.write_text("recent", encoding="utf-8")
            old_time = (datetime.now() - timedelta(days=30)).timestamp()
            os.utime(old_log, (old_time, old_time))

            planned = module.plan_prune_task_logs(root, days=14)

            self.assertEqual([path.relative_to(root).as_posix() for path in planned], ["logs/tasks/task-a/old.log"])

    def test_manage_secret_scan_reports_paths_without_values(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("manage_module", os.path.join(PROJECT_ROOT, "manage.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            secret_file = root / "backend" / ".env"
            secret_file.parent.mkdir(parents=True)
            secret_file.write_text("OPENAI_API_KEY=sk-test-secret-value\nSAFE=value\n", encoding="utf-8")

            findings = module.scan_secret_risks(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["path"], "backend/.env")
            self.assertEqual(findings[0]["line"], 1)
            self.assertIn("OPENAI_API_KEY", findings[0]["reason"])
            self.assertNotIn("sk-test-secret-value", json.dumps(findings, ensure_ascii=False))

    def test_manage_secret_scan_reports_tracked_ignored_files(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("manage_module", os.path.join(PROJECT_ROOT, "manage.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        old_tracked = module._tracked_files
        module._tracked_files = lambda root: ["backend/.env", "frontend/dist/index.html", "backend/app/main.py"]
        try:
            findings = module.scan_tracked_ignored_files(Path(PROJECT_ROOT))
        finally:
            module._tracked_files = old_tracked

        self.assertEqual({item["path"] for item in findings}, {"backend/.env", "frontend/dist/index.html"})

    def test_pre_commit_allows_deleting_blocked_generated_paths(self):
        script = Path(PROJECT_ROOT) / "scripts" / "pre-commit-secret-check.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
            (root / ".backend.log").write_text("old log", encoding="utf-8")
            subprocess.run(["git", "add", ".backend.log"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-m", "seed"], cwd=root, check=True, capture_output=True, text=True)
            (root / ".backend.log").unlink()
            subprocess.run(["git", "rm", ".backend.log"], cwd=root, check=True, capture_output=True, text=True)

            result = subprocess.run(
                [sys.executable, str(script)],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_pre_commit_blocks_adding_blocked_generated_paths(self):
        script = Path(PROJECT_ROOT) / "scripts" / "pre-commit-secret-check.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True, text=True)
            (root / "frontend" / "dist").mkdir(parents=True)
            (root / "frontend" / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
            subprocess.run(["git", "add", "frontend/dist/index.html"], cwd=root, check=True)

            result = subprocess.run(
                [sys.executable, str(script)],
                cwd=root,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(result.returncode, 1)
            self.assertIn("frontend/dist/index.html: blocked generated or sensitive path", result.stdout)

    def test_search_page_requests_top_three_results(self):
        source = Path(PROJECT_ROOT, "frontend", "src", "components", "SearchBox.tsx").read_text(encoding="utf-8")

        self.assertIn("const SEARCH_RESULT_LIMIT = 3", source)
        self.assertIn("limit: SEARCH_RESULT_LIMIT", source)
        self.assertNotIn("limit: 20", source)

    def test_image_card_keeps_visible_placeholder_when_file_load_fails(self):
        source = Path(PROJECT_ROOT, "frontend", "src", "components", "ImageCard.tsx").read_text(encoding="utf-8")

        self.assertIn("图片暂不可预览", source)
        self.assertIn("setImageError(true)", source)
        self.assertNotIn("style.display = 'none'", source)

    def test_blackboard_publishes_task_results_for_anonymous_users(self):
        from fastapi.testclient import TestClient
        from app import crud, models, schemas
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password

        db = SessionLocal()
        user = task = image = post = None
        image_path = None
        try:
            user = crud.create_user(
                db,
                username=f"blackboard-user-{uuid4().hex[:8]}",
                password_hash=hash_password("pass"),
                role="viewer",
            )
            task = crud.create_task(
                db,
                name="blackboard task",
                keyword="百亿会场",
                target_app="淘宝",
                target_scenario="百亿会场",
                created_by=user.id,
            )
            image_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
            image_file.write(base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
            ))
            image_file.close()
            image_path = image_file.name
            image = crud.create_image(db, schemas.ImageCreate(file_path=image_path, task_id=task.id))
            crud.create_analysis(db, image.id, "设计分析", "运营分析", status="success")
            client = TestClient(app)

            self.assertEqual(client.get(f"/api/blackboard/tasks/{task.id}").status_code, 404)

            published = client.post(
                f"/api/admin/tasks/{task.id}/blackboard",
                headers={"Authorization": f"Bearer {create_access_token(user)}"},
            )
            self.assertEqual(published.status_code, 200, published.text)
            post = db.query(models.BlackboardPost).filter(models.BlackboardPost.task_id == task.id).first()

            rows = client.get("/api/blackboard").json()
            self.assertIn(str(task.id), [row["task_id"] for row in rows])
            detail = client.get(f"/api/blackboard/tasks/{task.id}")
            self.assertEqual(detail.status_code, 200, detail.text)
            images = client.get(f"/api/blackboard/tasks/{task.id}/images")
            self.assertEqual(images.status_code, 200, images.text)
            self.assertEqual(images.json()[0]["analysis"]["design_analysis"], "设计分析")
            file_response = client.get(f"/api/blackboard/images/{image.id}/file")
            self.assertEqual(file_response.status_code, 200, file_response.text)
        finally:
            if post:
                db.delete(post)
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.delete(analysis)
                db.delete(image)
            if task:
                db.delete(task)
            if user:
                db.delete(user)
            db.commit()
            db.close()
            if image_path and os.path.exists(image_path):
                os.unlink(image_path)

    def test_image_file_redirects_to_oss_when_local_file_is_missing(self):
        from fastapi.testclient import TestClient
        from app import crud, schemas
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password

        db = SessionLocal()
        user = task = image = None
        oss_url = "https://example.com/screenshots/missing-local.png"
        try:
            user = crud.create_user(
                db,
                username=f"image-oss-user-{uuid4().hex[:8]}",
                password_hash=hash_password("pass"),
                role="viewer",
            )
            task = crud.create_task(
                db,
                name="oss fallback task",
                keyword="会场",
                target_app="淘宝",
                target_scenario="会场",
                created_by=user.id,
            )
            image = crud.create_image(
                db,
                schemas.ImageCreate(
                    file_path=f"data/missing-{uuid4().hex}.png",
                    task_id=task.id,
                    oss_url=oss_url,
                ),
            )

            response = TestClient(app).get(
                f"/api/images/{image.id}/file",
                headers={"Authorization": f"Bearer {create_access_token(user)}"},
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 302, response.text)
            self.assertEqual(response.headers["location"], oss_url)
        finally:
            if image:
                db.delete(image)
            if task:
                db.delete(task)
            if user:
                db.delete(user)
            db.commit()
            db.close()

    def test_blackboard_image_file_redirects_to_oss_when_local_file_is_missing(self):
        from fastapi.testclient import TestClient
        from app import crud, schemas
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import hash_password

        db = SessionLocal()
        user = task = image = post = None
        oss_url = "https://example.com/screenshots/blackboard-missing-local.png"
        try:
            user = crud.create_user(
                db,
                username=f"blackboard-oss-user-{uuid4().hex[:8]}",
                password_hash=hash_password("pass"),
                role="viewer",
            )
            task = crud.create_task(
                db,
                name="blackboard oss fallback task",
                keyword="会场",
                target_app="淘宝",
                target_scenario="会场",
                created_by=user.id,
            )
            image = crud.create_image(
                db,
                schemas.ImageCreate(
                    file_path=f"data/missing-blackboard-{uuid4().hex}.png",
                    task_id=task.id,
                    oss_url=oss_url,
                ),
            )
            post = crud.publish_task_to_blackboard(db, task.id, user.id)

            response = TestClient(app).get(
                f"/api/blackboard/images/{image.id}/file",
                follow_redirects=False,
            )

            self.assertEqual(response.status_code, 302, response.text)
            self.assertEqual(response.headers["location"], oss_url)
        finally:
            if post:
                db.delete(post)
            if image:
                db.delete(image)
            if task:
                db.delete(task)
            if user:
                db.delete(user)
            db.commit()
            db.close()

    def test_frontend_does_not_expose_redundant_image_management_tab(self):
        app_source = Path(PROJECT_ROOT, "frontend", "src", "App.tsx").read_text(encoding="utf-8")
        api_source = Path(PROJECT_ROOT, "frontend", "src", "api.ts").read_text(encoding="utf-8")

        self.assertNotIn("图片管理", app_source)
        self.assertNotIn("AdminImages", app_source)
        self.assertIn('path="/admin/images"', app_source)
        self.assertIn('to="/search"', app_source)
        self.assertNotIn("listImages", api_source)
        self.assertFalse(Path(PROJECT_ROOT, "frontend", "src", "pages", "AdminImages.tsx").exists())

    def test_registration_frontend_contract_is_exposed(self):
        app_source = Path(PROJECT_ROOT, "frontend", "src", "App.tsx").read_text(encoding="utf-8")
        api_source = Path(PROJECT_ROOT, "frontend", "src", "api.ts").read_text(encoding="utf-8")
        login_source = Path(PROJECT_ROOT, "frontend", "src", "pages", "LoginPage.tsx").read_text(encoding="utf-8")
        register_path = Path(PROJECT_ROOT, "frontend", "src", "pages", "RegisterPage.tsx")
        admin_users_source = Path(PROJECT_ROOT, "frontend", "src", "pages", "AdminUsers.tsx").read_text(encoding="utf-8")

        self.assertIn("RegisterPage", app_source)
        self.assertIn('path="/register"', app_source)
        self.assertIn('to="/register"', login_source)
        self.assertTrue(register_path.exists())
        register_source = register_path.read_text(encoding="utf-8")
        self.assertIn("邀请码", register_source)
        self.assertIn("invite_code", register_source)
        self.assertIn("registerUser", api_source)
        self.assertIn("getRegistrationInviteCode", api_source)
        self.assertIn("updateRegistrationInviteCode", api_source)
        self.assertIn("注册邀请码", admin_users_source)

    def test_manage_log_secret_scan_does_not_return_secret_values(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("manage_module", os.path.join(PROJECT_ROOT, "manage.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".backend.log").write_text("OPENAI_API_KEY=sk-test-secret-value\n", encoding="utf-8")

            findings = module.scan_log_secret_risks(root)

            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0]["path"], ".backend.log")
            self.assertNotIn("sk-test-secret-value", json.dumps(findings, ensure_ascii=False))

    def test_image_out_exposes_task_id(self):
        from app.schemas import ImageOut

        self.assertIn("task_id", ImageOut.model_fields)

    def test_password_hash_does_not_store_plaintext_and_verifies(self):
        from app.services.auth import hash_password, verify_password

        password_hash = hash_password("secret-password")

        self.assertNotIn("secret-password", password_hash)
        self.assertTrue(verify_password("secret-password", password_hash))
        self.assertFalse(verify_password("wrong-password", password_hash))

    def test_auth_token_roundtrip_contains_user_identity(self):
        from app import crud
        from app.database import SessionLocal
        from app.services.auth import create_access_token, decode_access_token, hash_password

        db = SessionLocal()
        user = None
        username = f"auth-{uuid4().hex}"
        try:
            user = crud.create_user(
                db,
                username=username,
                display_name="Auth Test",
                password_hash=hash_password("secret-password"),
                role="operator",
            )

            token = create_access_token(user)
            payload = decode_access_token(token)

            self.assertEqual(payload["sub"], str(user.id))
            self.assertEqual(payload["role"], "operator")
        finally:
            if user:
                db.delete(user)
            db.commit()
            db.close()

    def test_admin_stats_requires_login_and_accepts_token(self):
        from fastapi.testclient import TestClient
        from app import crud
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password

        db = SessionLocal()
        user = None
        try:
            user = crud.create_user(
                db,
                username=f"client-{uuid4().hex}",
                password_hash=hash_password("secret-password"),
                role="viewer",
            )
            token = create_access_token(user)
            client = TestClient(app)

            self.assertEqual(client.get("/api/admin/stats").status_code, 401)
            self.assertEqual(client.get("/api/admin/stats", headers={"Authorization": f"Bearer {token}"}).status_code, 200)
        finally:
            if user:
                db.delete(user)
            db.commit()
            db.close()

    def test_low_role_cannot_manage_users(self):
        from fastapi.testclient import TestClient
        from app import crud
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password

        db = SessionLocal()
        user = None
        try:
            user = crud.create_user(
                db,
                username=f"viewer-{uuid4().hex}",
                password_hash=hash_password("secret-password"),
                role="viewer",
            )
            token = create_access_token(user)
            client = TestClient(app)

            response = client.get("/api/admin/users", headers={"Authorization": f"Bearer {token}"})

            self.assertEqual(response.status_code, 403)
        finally:
            if user:
                db.delete(user)
            db.commit()
            db.close()

    def test_user_update_can_disable_user(self):
        from app import crud
        from app.database import SessionLocal
        from app.services.auth import hash_password

        db = SessionLocal()
        user = None
        try:
            user = crud.create_user(
                db,
                username=f"disabled-{uuid4().hex}",
                password_hash=hash_password("secret-password"),
                role="viewer",
            )
            updated = crud.update_user(db, user.id, status="disabled")

            self.assertEqual(updated.status, "disabled")
        finally:
            if user:
                db.delete(user)
            db.commit()
            db.close()

    def test_public_registration_requires_configurable_invite_code(self):
        from fastapi.testclient import TestClient
        from app import crud
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password, verify_password

        db = SessionLocal()
        admin = None
        created_user = None
        previous_code = None
        username = f"registered-{uuid4().hex}"
        try:
            admin = crud.create_user(
                db,
                username=f"admin-{uuid4().hex}",
                password_hash=hash_password("secret-password"),
                role="admin",
            )
            admin_token = create_access_token(admin)
            client = TestClient(app)

            get_response = client.get(
                "/api/admin/settings/registration-invite-code",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            self.assertEqual(get_response.status_code, 200)
            previous_code = get_response.json()["invite_code"]

            invalid_update = client.patch(
                "/api/admin/settings/registration-invite-code",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"invite_code": "12345"},
            )
            self.assertEqual(invalid_update.status_code, 400)

            update_response = client.patch(
                "/api/admin/settings/registration-invite-code",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"invite_code": "2468"},
            )
            self.assertEqual(update_response.status_code, 200)
            self.assertEqual(update_response.json()["invite_code"], "2468")

            rejected = client.post(
                "/api/auth/register",
                json={"username": username, "password": "new-password", "invite_code": "1357"},
            )
            self.assertEqual(rejected.status_code, 403)

            accepted = client.post(
                "/api/auth/register",
                json={"username": username, "password": "new-password", "invite_code": "2468"},
            )
            self.assertEqual(accepted.status_code, 200)
            body = accepted.json()
            self.assertEqual(body["user"]["username"], username)
            self.assertEqual(body["user"]["role"], "viewer")
            self.assertIn("access_token", body)

            created_user = crud.get_user_by_username(db, username)
            self.assertIsNotNone(created_user)
            self.assertTrue(verify_password("new-password", created_user.password_hash))
        finally:
            if previous_code is not None:
                crud.set_registration_invite_code(db, previous_code, updated_by=admin.id if admin else None)
            if created_user:
                db.delete(created_user)
            if admin:
                db.delete(admin)
            db.commit()
            db.close()

    def test_business_data_is_scoped_to_current_user(self):
        from fastapi.testclient import TestClient
        from app import crud, schemas, models
        from app.database import SessionLocal
        from app.main import app
        from app.routers import search as search_router
        from app.services.auth import create_access_token, hash_password

        class FailingEmbedder:
            async def embed_single(self, text):
                raise RuntimeError("embedding disabled")

        old_embedder = search_router.embedder
        search_router.embedder = FailingEmbedder()

        db = SessionLocal()
        suffix = uuid4().hex
        user_a = user_b = None
        request_a = request_b = None
        task_a = task_b = None
        run_a = run_b = None
        image_a = image_b = None
        plan_a = plan_b = None
        try:
            user_a = crud.create_user(
                db,
                username=f"tenant-a-{suffix}",
                password_hash=hash_password("secret-password"),
                role="viewer",
            )
            user_b = crud.create_user(
                db,
                username=f"tenant-b-{suffix}",
                password_hash=hash_password("secret-password"),
                role="viewer",
            )
            request_a = crud.create_request(
                db,
                schemas.RequestCreate(target_app="淘宝", target_scenario="A 场景", keywords=["A隔离"]),
                user_id=str(user_a.id),
            )
            request_b = crud.create_request(
                db,
                schemas.RequestCreate(target_app="京东", target_scenario="B 场景", keywords=["B隔离"]),
                user_id=str(user_b.id),
            )
            task_a = crud.create_task(
                db,
                name="tenant-a-task",
                keyword="A隔离",
                target_app="淘宝",
                target_scenario="A 场景",
                request_id=request_a.id,
                created_by=user_a.id,
            )
            task_b = crud.create_task(
                db,
                name="tenant-b-task",
                keyword="B隔离",
                target_app="京东",
                target_scenario="B 场景",
                request_id=request_b.id,
                created_by=user_b.id,
            )
            run_a = crud.create_task_run(db, task_a.id, status="completed", created_by=user_a.id)
            run_b = crud.create_task_run(db, task_b.id, status="completed", created_by=user_b.id)
            image_a = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/tenant-a-{suffix}.png",
                task_id=task_a.id,
                task_run_id=run_a.id,
                source_app="淘宝",
                scenario="A 场景",
            ))
            image_b = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/tenant-b-{suffix}.png",
                task_id=task_b.id,
                task_run_id=run_b.id,
                source_app="京东",
                scenario="B 场景",
            ))
            crud.create_analysis(db, image_a.id, "A隔离设计内容", "A隔离运营内容")
            crud.create_analysis(db, image_b.id, "B隔离设计内容", "B隔离运营内容")
            plan_a = crud.create_watch_plan(db, schemas.WatchPlanCreate(
                name="tenant-a-watch",
                target_app="淘宝",
                target_page="A 页面",
                entry_instruction="打开淘宝进入 A 页面",
            ), created_by=user_a.id)
            plan_b = crud.create_watch_plan(db, schemas.WatchPlanCreate(
                name="tenant-b-watch",
                target_app="京东",
                target_page="B 页面",
                entry_instruction="打开京东进入 B 页面",
            ), created_by=user_b.id)

            client = TestClient(app)
            headers_a = {"Authorization": f"Bearer {create_access_token(user_a)}"}
            headers_b = {"Authorization": f"Bearer {create_access_token(user_b)}"}

            self.assertEqual(client.get("/api/admin/stats", headers=headers_a).json()["requests"], 1)
            self.assertEqual(client.get("/api/admin/stats", headers=headers_a).json()["tasks"], 1)
            request_ids = [row["id"] for row in client.get("/api/admin/requests", headers=headers_a).json()]
            task_ids = [row["id"] for row in client.get("/api/admin/tasks", headers=headers_a).json()]
            self.assertEqual(request_ids, [str(request_a.id)])
            self.assertEqual(task_ids, [str(task_a.id)])

            search_rows = client.post(
                "/api/search",
                headers=headers_a,
                json={"query": "隔离", "limit": 10, "offset": 0},
            ).json()
            self.assertEqual([row["image"]["id"] for row in search_rows], [str(image_a.id)])

            image_rows = client.get("/api/images", headers=headers_a).json()
            self.assertEqual([row["image"]["id"] for row in image_rows], [str(image_a.id)])
            self.assertEqual(client.get(f"/api/images/{image_b.id}", headers=headers_a).status_code, 404)
            self.assertEqual(client.get(f"/api/admin/tasks/{task_b.id}/images", headers=headers_a).status_code, 404)
            self.assertEqual(client.get(f"/api/admin/tasks/{task_b.id}/export?format=json", headers=headers_a).status_code, 404)

            watch_ids = [row["id"] for row in client.get("/api/admin/watch-plans", headers=headers_a).json()]
            self.assertEqual(watch_ids, [str(plan_a.id)])
            self.assertEqual(client.get(f"/api/admin/watch-plans/{plan_b.id}", headers=headers_a).status_code, 404)
            self.assertEqual(client.get(f"/api/admin/watch-plans/{plan_a.id}", headers=headers_b).status_code, 404)
        finally:
            search_router.embedder = old_embedder
            for image in (image_a, image_b):
                if image:
                    analysis = crud.get_analysis_by_image(db, image.id)
                    if analysis:
                        db.query(models.Embedding).filter(models.Embedding.analysis_id == analysis.id).delete()
                        db.delete(analysis)
                    db.delete(image)
            for run in (run_a, run_b):
                if run:
                    db.delete(run)
            for task in (task_a, task_b):
                if task:
                    db.delete(task)
            for request in (request_a, request_b):
                if request:
                    db.delete(request)
            for plan in (plan_a, plan_b):
                if plan:
                    db.delete(plan)
            for user in (user_a, user_b):
                if user:
                    db.delete(user)
            db.commit()
            db.close()

    def test_admin_can_review_all_user_requests_and_assign_task_to_submitter(self):
        from fastapi.testclient import TestClient
        from app import crud, schemas
        from app.config import settings
        from app.database import SessionLocal
        from app.main import app
        from app.routers import admin as admin_router
        from app.services.auth import create_access_token, hash_password

        async def fake_plan_task(**kwargs):
            return "打开拼多多，找到限时秒杀并截图"

        db = SessionLocal()
        suffix = uuid4().hex
        admin = submitter = None
        request = task = None
        old_mode = settings.EXECUTION_MODE
        old_plan_task = admin_router.plan_task
        admin_router.plan_task = fake_plan_task
        try:
            settings.EXECUTION_MODE = "worker"
            admin = crud.create_user(
                db,
                username=f"review-admin-{suffix}",
                password_hash=hash_password("secret-password"),
                role="admin",
            )
            submitter = crud.create_user(
                db,
                username=f"review-user-{suffix}",
                password_hash=hash_password("secret-password"),
                role="viewer",
            )
            request = crud.create_request(
                db,
                schemas.RequestCreate(target_app="拼多多", target_scenario="限时秒杀", keywords=["百亿补贴"]),
                user_id=str(submitter.id),
            )

            client = TestClient(app)
            admin_headers = {"Authorization": f"Bearer {create_access_token(admin)}"}
            submitter_headers = {"Authorization": f"Bearer {create_access_token(submitter)}"}

            review_rows = client.get("/api/admin/requests", headers=admin_headers).json()
            self.assertIn(str(request.id), [row["id"] for row in review_rows])
            self.assertGreaterEqual(client.get("/api/admin/stats", headers=admin_headers).json()["pending_requests"], 1)

            response = client.put(
                f"/api/admin/requests/{request.id}/approve",
                headers=admin_headers,
                json={"admin_id": admin.username, "mode": "uiautomator2"},
            )
            self.assertEqual(response.status_code, 200)
            body = response.json()
            task = crud.get_task(db, UUID(body["id"]))
            self.assertEqual(body["created_by"], str(submitter.id))
            self.assertEqual(body["approved_by"], str(admin.id))
            self.assertEqual(body["status"], "queued")
            self.assertEqual(body["execution_mode"], "worker")
            self.assertIsNotNone(body["latest_run_id"])
            run = crud.get_latest_task_run(db, task.id)
            self.assertEqual(run.status, "queued")
            self.assertEqual(run.execution_mode, "worker")

            submitter_tasks = client.get("/api/admin/tasks", headers=submitter_headers).json()
            self.assertIn(body["id"], [row["id"] for row in submitter_tasks])
        finally:
            settings.EXECUTION_MODE = old_mode
            admin_router.plan_task = old_plan_task
            if task:
                db.delete(task)
            if request:
                db.delete(request)
            for user in (admin, submitter):
                if user:
                    db.delete(user)
            db.commit()
            db.close()

    def test_request_submission_requires_login_and_records_owner(self):
        from fastapi.testclient import TestClient
        from app import crud
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password

        db = SessionLocal()
        owner = other = None
        request_id = None
        try:
            owner = crud.create_user(
                db,
                username=f"request-owner-{uuid4().hex}",
                password_hash=hash_password("secret-password"),
                role="viewer",
            )
            other = crud.create_user(
                db,
                username=f"request-other-{uuid4().hex}",
                password_hash=hash_password("secret-password"),
                role="viewer",
            )
            client = TestClient(app)
            payload = {"target_app": "淘宝", "target_scenario": "百亿补贴", "keywords": ["补贴"]}

            self.assertEqual(client.post("/api/requests", json=payload).status_code, 401)

            created = client.post(
                "/api/requests",
                headers={"Authorization": f"Bearer {create_access_token(owner)}"},
                json=payload,
            )
            self.assertEqual(created.status_code, 200)
            request_id = created.json()["id"]
            self.assertEqual(created.json()["user_id"], str(owner.id))

            other_read = client.get(
                f"/api/requests/{request_id}",
                headers={"Authorization": f"Bearer {create_access_token(other)}"},
            )
            self.assertEqual(other_read.status_code, 404)
        finally:
            if request_id:
                request = crud.get_request(db, UUID(request_id))
                if request:
                    db.delete(request)
            for user in (owner, other):
                if user:
                    db.delete(user)
            db.commit()
            db.close()

    def test_task_run_retry_creates_new_attempt_without_overwriting_old_run(self):
        from app import crud
        from app.database import SessionLocal

        db = SessionLocal()
        task = None
        try:
            task = crud.create_task(db, name="retry-test", keyword="", target_app="淘宝", target_scenario="首页")
            first = crud.create_task_run(db, task.id, status="failed", output_dir="data/old", log_path="logs/old.log")
            crud.update_task_run(db, first.id, status="failed", failure_reason="old failure")
            second = crud.create_task_run(db, task.id, status="pending", output_dir="data/new", log_path="logs/new.log")

            self.assertEqual(first.attempt_no, 1)
            self.assertEqual(second.attempt_no, 2)
            self.assertEqual(crud.get_task_run(db, first.id).failure_reason, "old failure")
        finally:
            if task:
                db.delete(task)
            db.commit()
            db.close()

    def test_device_acquire_skips_busy_devices_and_release_unlocks(self):
        from app import crud
        from app.database import SessionLocal

        db = SessionLocal()
        task = device = run = None
        try:
            task = crud.create_task(db, name="device-lock-test", keyword="", target_app="淘宝", target_scenario="首页")
            device = crud.upsert_device(db, serial=f"device-{uuid4().hex}", status="online")
            run = crud.create_task_run(db, task.id, device_id=device.id)

            self.assertIsNotNone(crud.acquire_device(db, device.id))
            crud.mark_device_busy(db, device.id, run.id)
            self.assertIsNone(crud.acquire_device(db, device.id))
            crud.release_device_for_run(db, run.id)
            self.assertIsNotNone(crud.acquire_device(db, device.id))
        finally:
            if task:
                db.delete(task)
            if device:
                db.delete(device)
            db.commit()
            db.close()

    def test_local_device_acquire_ignores_worker_devices(self):
        from app import crud, models
        from app.database import SessionLocal

        db = SessionLocal()
        local = worker = worker_node = None
        try:
            worker_node = crud.upsert_worker(db, node_key=f"worker-{uuid4().hex}", status="online")
            worker = crud.upsert_device(
                db,
                serial=f"worker-device-{uuid4().hex[:8]}",
                status="online",
                source="worker",
                worker_id=worker_node.id,
            )
            local = crud.upsert_device(
                db,
                serial=f"local-device-{uuid4().hex[:8]}",
                status="online",
                source="local",
            )

            self.assertEqual(crud.acquire_device(db, local.id).id, local.id)
            self.assertIsNone(crud.acquire_device(db, worker.id))
        finally:
            for device in (worker, local):
                if device:
                    db.query(models.TaskRun).filter(models.TaskRun.device_id == device.id).update({"device_id": None}, synchronize_session=False)
                    db.delete(device)
            if worker_node:
                db.delete(worker_node)
            db.commit()
            db.close()

    def test_starting_with_busy_device_returns_none_from_lock(self):
        from app import crud
        from app.database import SessionLocal

        db = SessionLocal()
        task = first = second = device = None
        try:
            task = crud.create_task(db, name="busy-device-test", keyword="", target_app="淘宝", target_scenario="首页")
            device = crud.upsert_device(db, serial=f"busy-{uuid4().hex}", status="online")
            first = crud.create_task_run(db, task.id, device_id=device.id)
            second = crud.create_task_run(db, task.id, device_id=device.id)
            crud.mark_device_busy(db, device.id, first.id)

            self.assertIsNone(crud.mark_device_busy(db, device.id, second.id))
        finally:
            if task:
                db.delete(task)
            if device:
                db.delete(device)
            db.commit()
            db.close()

    def test_export_task_json_excludes_raw_embedding_vectors(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.services.exporter import task_export_payload

        db = SessionLocal()
        task = image = None
        try:
            task = crud.create_task(db, name="export-test", keyword="红包", target_app="淘宝", target_scenario="首页")
            run = crud.create_task_run(db, task.id, status="completed")
            image = crud.create_image(db, schemas.ImageCreate(file_path=f"data/export-{uuid4().hex}.png", task_id=task.id, task_run_id=run.id))
            crud.create_analysis(db, image.id, "设计内容", "运营内容")

            payload = task_export_payload(db, task.id)
            encoded = json.dumps(payload, ensure_ascii=False)

            self.assertEqual(payload["task"]["id"], str(task.id))
            self.assertEqual(payload["runs"][0]["id"], str(run.id))
            self.assertIn("设计内容", encoded)
            self.assertNotIn("embedding\": [", encoded)
        finally:
            if task:
                db.delete(task)
            db.commit()
            db.close()

    def test_export_zip_records_missing_images(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.services.exporter import task_zip_bytes
        import zipfile

        db = SessionLocal()
        task = None
        try:
            task = crud.create_task(db, name="zip-export-test", keyword="", target_app="淘宝", target_scenario="首页")
            crud.create_image(db, schemas.ImageCreate(file_path=f"data/missing-{uuid4().hex}.png", task_id=task.id))

            content = task_zip_bytes(db, task.id)
            with zipfile.ZipFile(BytesIO(content)) as zf:
                missing = json.loads(zf.read("missing_files.json").decode("utf-8"))

            self.assertEqual(len(missing["missing_files"]), 1)
        finally:
            if task:
                db.delete(task)
            db.commit()
            db.close()

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
            "OPENAI_API_KEY": settings.OPENAI_API_KEY,
            "PHONE_AGENT_API_KEY": settings.PHONE_AGENT_API_KEY,
            "PHONE_AGENT_BASE_URL": settings.PHONE_AGENT_BASE_URL,
            "PHONE_AGENT_MODEL": settings.PHONE_AGENT_MODEL,
            "MODELSCOPE_VLM_MODEL": settings.MODELSCOPE_VLM_MODEL,
        }
        try:
            settings.VLM_API_KEY = ""
            settings.OPENAI_API_KEY = ""
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

    def test_llm_analyzer_prefers_openai_over_phone_agent_vlm(self):
        from app.config import settings
        from app.services.llm_analyzer import LLMAnalyzer

        old_values = {
            "VLM_API_KEY": settings.VLM_API_KEY,
            "OPENAI_API_KEY": settings.OPENAI_API_KEY,
            "OPENAI_BASE_URL": settings.OPENAI_BASE_URL,
            "VLM_MODEL": settings.VLM_MODEL,
            "PHONE_AGENT_API_KEY": settings.PHONE_AGENT_API_KEY,
            "PHONE_AGENT_BASE_URL": settings.PHONE_AGENT_BASE_URL,
            "MODELSCOPE_VLM_MODEL": settings.MODELSCOPE_VLM_MODEL,
        }
        try:
            settings.VLM_API_KEY = ""
            settings.OPENAI_API_KEY = "openai-key"
            settings.OPENAI_BASE_URL = "https://modelservice.jdcloud.com/v1/"
            settings.VLM_MODEL = "GPT-5.5"
            settings.PHONE_AGENT_API_KEY = "phone-key"
            settings.PHONE_AGENT_BASE_URL = "https://api-inference.modelscope.cn/v1"
            settings.MODELSCOPE_VLM_MODEL = "modelscope-vlm"

            analyzer = LLMAnalyzer()

            self.assertEqual([provider["name"] for provider in analyzer.providers], ["openai", "modelscope_vlm"])
            self.assertEqual(analyzer.api_key, "openai-key")
            self.assertEqual(analyzer.base_url, "https://modelservice.jdcloud.com/v1")
            self.assertEqual(analyzer.model, "GPT-5.5")
            self.assertEqual(analyzer.providers[1]["model"], "modelscope-vlm")
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

    def test_dynamic_analysis_prompt_mentions_each_skill(self):
        from app.services.llm_analyzer import LLMAnalyzer

        snapshots = [
            {"skill_id": "a", "name": "设计维度", "instruction_md": "# 设计维度\n分析布局。", "is_official": True},
            {"skill_id": "b", "name": "价格策略", "instruction_md": "# 价格策略\n分析价格。", "is_official": False},
        ]

        prompt = LLMAnalyzer()._build_dynamic_analysis_prompt(snapshots, {"target_app": "淘宝"})

        self.assertIn("设计维度", prompt)
        self.assertIn("价格策略", prompt)
        self.assertIn('"results"', prompt)

    def test_dynamic_analysis_result_syncs_default_fields(self):
        from app.services.llm_analyzer import normalize_dynamic_analysis_result

        normalized = normalize_dynamic_analysis_result(
            {"results": [
                {"skill_name": "设计维度", "analysis": "布局清晰"},
                {"skill_name": "运营维度", "analysis": "促销明显"},
                {"skill_name": "价格策略", "analysis": "补贴突出"},
            ]},
            [{"name": "设计维度"}, {"name": "运营维度"}, {"name": "价格策略"}],
        )

        self.assertEqual(normalized["design_analysis"], "布局清晰")
        self.assertEqual(normalized["ops_analysis"], "促销明显")
        self.assertEqual(normalized["status"], "success")
        self.assertEqual(len(normalized["custom_analysis_json"]["results"]), 3)

    def test_autoglm_prompts_do_not_ask_agent_to_save_screenshots(self):
        from app.routers.admin import build_autoglm_prompt
        from app.services.jd_comparison import build_jd_instruction
        from app.services.task_planner import _fallback_instruction, _strip_manual_capture_instruction

        task = SimpleNamespace(
            target_app="淘宝",
            keyword="",
            target_scenario="首页",
            request=None,
            target_goals_json=[],
        )

        prompts = [
            _fallback_instruction("淘宝", "首页", [], None),
            build_autoglm_prompt(task),
            build_jd_instruction("首页", [], None),
            _strip_manual_capture_instruction("打开京东App，进入首页，并截图保存到本地"),
        ]

        for prompt in prompts:
            self.assertNotIn("截图保存到本地", prompt)
            self.assertNotIn("并截图保存", prompt)
            self.assertIn("停留并结束任务", prompt)

    def test_jd_comparison_filters_app_specific_description_for_a_side(self):
        from app.services.jd_comparison import description_for_app

        description = (
            "淘宝必须回到底部主导航首页，并确认顶部分类Tab选中推荐；"
            "京东必须回到底部主导航首页，并确认顶部分类Tab选中首页；"
            "通用要求是到达页面后停留。"
        )

        taobao_description = description_for_app(description, "淘宝")
        jd_description = description_for_app(description, "京东")

        self.assertIn("淘宝必须", taobao_description)
        self.assertNotIn("京东必须", taobao_description)
        self.assertIn("通用要求", taobao_description)
        self.assertIn("京东必须", jd_description)
        self.assertNotIn("淘宝必须", jd_description)

    def test_dynamic_analysis_extracts_wrapped_results_json(self):
        from app.services.llm_analyzer import LLMAnalyzer

        parsed = LLMAnalyzer()._extract_json('结果如下：{"results":[{"skill_name":"价格策略","analysis":"补贴突出"}]}')

        self.assertEqual(parsed["results"][0]["analysis"], "补贴突出")

    def test_dynamic_analysis_text_consumers_include_custom_results(self):
        from app.backfill_embeddings import _analysis_text as embedding_analysis_text
        from app.services.goal_validator import _analysis_text as goal_analysis_text
        from app.services.watch_reporter import WatchReporter

        analysis = SimpleNamespace(
            status="success",
            design_analysis="",
            ops_analysis="",
            custom_analysis_json={"results": [{"skill_name": "价格策略", "analysis": "会员价补贴突出"}]},
        )
        image = SimpleNamespace(analysis=analysis)

        self.assertIn("会员价补贴突出", embedding_analysis_text(analysis)["combined"])
        self.assertIn("会员价补贴突出", goal_analysis_text(image))
        fallback = WatchReporter()._fallback_daily(
            SimpleNamespace(target_app="淘宝", target_page="搜索页"),
            SimpleNamespace(run_date=datetime.now().date()),
            "",
            "",
            multi="会员价补贴突出",
        )
        self.assertIn("会员价补贴突出", fallback["design_summary"])

    def test_dynamic_analysis_embedding_replace_rolls_back_on_failure(self):
        from app import crud, schemas, models
        from app.config import settings
        from app.database import SessionLocal

        db = SessionLocal()
        image = None
        try:
            image = crud.create_image(db, schemas.ImageCreate(file_path="data/rollback-embedding.png"))
            analysis = crud.create_analysis(db, image.id, "设计分析", "运营分析")
            crud.create_embedding(db, analysis.id, [0.1] * settings.effective_embedding_dim(), "combined")

            with self.assertRaises(Exception):
                crud.replace_embeddings(db, analysis.id, {"combined": [0.1]})

            rows = db.query(models.Embedding).filter(models.Embedding.analysis_id == analysis.id).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].content_type, "combined")
        finally:
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.query(models.Embedding).filter(models.Embedding.analysis_id == analysis.id).delete()
                    db.delete(analysis)
                db.delete(image)
            db.commit()
            db.close()

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

    def test_task_event_payloads_are_json(self):
        from app.services.task_events import task_event

        payload = task_event("new_image", count=2)

        self.assertEqual(json.loads(payload), {"type": "new_image", "count": 2})

    def test_task_event_parser_accepts_legacy_done(self):
        from app.services.task_events import task_event_type

        self.assertEqual(task_event_type("DONE"), "done")

    def test_autoglm_max_steps_setting_defaults_to_bounded_run(self):
        from app.config import settings

        self.assertGreater(settings.AUTOGLM_MAX_STEPS, 0)
        self.assertLessEqual(settings.AUTOGLM_MAX_STEPS, 10)

    def test_task_runner_passes_target_app_as_autoglm_source_app(self):
        from app import crud
        from app.database import SessionLocal
        from app.services import task_runner

        class FakeProcess:
            pass

        captured = {}

        def fake_popen(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["kwargs"] = kwargs
            return FakeProcess()

        db = SessionLocal()
        task = None
        old_popen = task_runner.subprocess.Popen
        old_watcher = task_runner.start_collection_watcher
        try:
            task = crud.create_task(
                db,
                name="autoglm-source-app-test",
                keyword="",
                target_app="京东",
                target_scenario="首页",
                mode="autoglm",
            )
            crud.update_task_instruction(db, task.id, "打开京东首页并截图")
            task = crud.get_task(db, task.id)

            task_runner.subprocess.Popen = fake_popen
            task_runner.start_collection_watcher = lambda *args, **kwargs: None
            task_runner.start_task_process(task)

            self.assertIn("--source-app", captured["cmd"])
            source_app_index = captured["cmd"].index("--source-app")
            self.assertEqual(captured["cmd"][source_app_index + 1], "京东")
        finally:
            task_runner.subprocess.Popen = old_popen
            task_runner.start_collection_watcher = old_watcher
            if task:
                db.delete(task)
            db.commit()
            db.close()

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

    def test_llm_analyzer_page_evidence_prompt_is_target_definition_driven(self):
        from app.services.llm_analyzer import LLMAnalyzer

        prompt = LLMAnalyzer()._build_page_evidence_prompt(
            [
                {
                    "target_key": "campaign_landing",
                    "target_name": "活动会场",
                    "target_type": "comparison_slot",
                    "description": "平台活动频道或营销会场首屏",
                    "goal_labels": ["活动会场"],
                }
            ],
            {"target_app": "任意App", "target_scenario": "活动会场"},
        )

        self.assertIn("matched_target_key", prompt)
        self.assertIn("campaign_landing", prompt)
        self.assertIn("活动会场", prompt)
        self.assertNotIn("百亿补贴", prompt)

    def test_llm_analyzer_page_evidence_prompt_requests_terminal_state_fields(self):
        from app.services.llm_analyzer import LLMAnalyzer

        prompt = LLMAnalyzer()._build_page_evidence_prompt(
            [
                {
                    "target_key": "campaign_landing",
                    "target_name": "活动会场",
                    "target_type": "comparison_slot",
                    "description": "平台活动频道或营销会场首屏",
                    "goal_labels": ["活动会场"],
                }
            ],
            {"target_app": "任意App", "target_scenario": "活动会场"},
        )

        self.assertIn("page_state", prompt)
        self.assertIn("target_role", prompt)
        self.assertIn("is_terminal_target", prompt)
        self.assertIn("needs_more_wait", prompt)

    def test_llm_analyzer_page_evidence_prompt_allows_complete_business_module_targets(self):
        from app.services.llm_analyzer import LLMAnalyzer

        prompt = LLMAnalyzer()._build_page_evidence_prompt(
            [
                {
                    "target_key": "campaign_landing",
                    "target_name": "活动会场",
                    "target_type": "page_goal",
                    "description": "可接受终态：独立频道/会场页面，或当前页面中完整露出的同名/等价业务模块。",
                    "goal_labels": ["活动会场"],
                }
            ],
            {"target_app": "任意App", "target_scenario": "活动会场"},
        )

        self.assertIn("完整业务模块", prompt)
        self.assertIn("单个入口按钮", prompt)
        self.assertIn("多个商品", prompt)

    def test_llm_analyzer_normalizes_page_evidence_string_booleans(self):
        from app.services.llm_analyzer import LLMAnalyzer

        evidence = LLMAnalyzer()._normalize_page_evidence(
            {
                "matched_target_key": "campaign_landing",
                "matched_target_name": "活动会场",
                "matched_goal_labels": ["活动会场"],
                "confidence": 0.9,
                "page_state": "intermediate",
                "target_role": "promo_entry",
                "is_terminal_target": "false",
                "needs_more_wait": "true",
            },
            [
                {
                    "target_key": "campaign_landing",
                    "target_name": "活动会场",
                    "goal_labels": ["活动会场"],
                }
            ],
            "{}",
        )

        self.assertFalse(evidence["is_terminal_target"])
        self.assertTrue(evidence["needs_more_wait"])

    def test_page_evidence_helper_rejects_string_false_terminal_flag(self):
        from app.services.page_evidence import slot_match_from_evidence

        match = slot_match_from_evidence(
            {
                "matched_target_key": "campaign_landing",
                "confidence": 0.9,
                "page_state": "target_page",
                "is_terminal_target": "false",
                "needs_more_wait": "false",
                "negative_evidence": [],
            },
            [{"slot_key": "campaign_landing", "name": "活动会场"}],
        )

        self.assertIsNone(match)

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

    def test_analyze_and_embed_stores_page_evidence(self):
        from app import crud, schemas
        from app.config import settings
        from app.database import SessionLocal
        from app.routers import images as images_router
        from app.services.task_goals import build_target_goals

        class FakeAnalyzer:
            async def is_target_page(self, image_path, context):
                return True, "目标页"

            async def extract_page_evidence(self, image_path, targets, context=None):
                self.targets = targets
                return {
                    "matched_target_key": "goal_1",
                    "matched_target_name": "活动会场",
                    "matched_goal_labels": ["活动会场"],
                    "confidence": 0.91,
                    "visible_text": ["活动会场"],
                    "strong_evidence": ["页面业务角色匹配活动会场"],
                    "weak_evidence": [],
                    "negative_evidence": [],
                    "reason": "命中目标定义",
                }

            async def analyze_with_skills(self, image_path, skill_snapshots, context=None):
                return {
                    "design_analysis": "活动页设计",
                    "ops_analysis": "活动页运营",
                    "status": "success",
                    "custom_analysis_json": {"results": []},
                }

        class FakeEmbedder:
            async def embed_single(self, text):
                return [0.0] * settings.effective_embedding_dim()

        fake_analyzer = FakeAnalyzer()
        old_analyzer = images_router.analyzer
        old_embedder = images_router.embedder
        images_router.analyzer = fake_analyzer
        images_router.embedder = FakeEmbedder()

        db = SessionLocal()
        task = image = None
        try:
            task = crud.create_task(
                db,
                name="page-evidence-store-test",
                keyword="",
                target_app="任意App",
                target_scenario="活动会场",
                target_goals_json=build_target_goals("任意App", "活动会场", [], None),
            )
            image = crud.create_image(db, schemas.ImageCreate(
                file_path="data/page-evidence-store.png",
                task_id=task.id,
                source_app="任意App",
            ))

            asyncio.run(images_router._analyze_and_embed(image.id))

            analysis = crud.get_analysis_by_image(db, image.id)
            self.assertEqual(analysis.status, "success")
            self.assertEqual(analysis.custom_analysis_json["page_evidence"]["matched_goal_labels"], ["活动会场"])
            self.assertEqual(fake_analyzer.targets[0]["target_name"], "活动会场")
        finally:
            images_router.analyzer = old_analyzer
            images_router.embedder = old_embedder
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.delete(analysis)
                db.delete(image)
            if task:
                db.delete(task)
            db.commit()
            db.close()

    def test_analyze_and_embed_records_embedding_failure(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.routers import images as images_router

        class FakeAnalyzer:
            async def is_target_page(self, image_path, context):
                return True, "目标页"

            async def analyze(self, image_path, context=None):
                return "设计分析", "运营分析", "success"

        class FailingEmbedder:
            async def embed_single(self, text):
                raise RuntimeError("embedding unavailable")

        old_analyzer = images_router.analyzer
        old_embedder = images_router.embedder
        images_router.analyzer = FakeAnalyzer()
        images_router.embedder = FailingEmbedder()

        db = SessionLocal()
        image = None
        try:
            image = crud.create_image(db, schemas.ImageCreate(file_path="data/embedding-failure.png"))

            asyncio.run(images_router._analyze_and_embed(image.id))

            analysis = crud.get_analysis_by_image(db, image.id)
            self.assertEqual(analysis.status, "success")
            self.assertEqual(analysis.embedding_status, "failed")
            self.assertIn("embedding unavailable", analysis.embedding_error)
        finally:
            images_router.analyzer = old_analyzer
            images_router.embedder = old_embedder
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.delete(analysis)
                db.delete(image)
            db.commit()
            db.close()

    def test_analyze_and_embed_records_dynamic_analysis_results(self):
        from app import crud, schemas, models
        from app.config import settings
        from app.database import SessionLocal
        from app.routers import images as images_router

        class FakeAnalyzer:
            def __init__(self):
                self.snapshots = None

            async def is_target_page(self, image_path, context):
                return True, "目标页"

            async def analyze_with_skills(self, image_path, skill_snapshots, context=None):
                self.snapshots = skill_snapshots
                return {
                    "design_analysis": "布局清晰",
                    "ops_analysis": "",
                    "status": "success",
                    "custom_analysis_json": {
                        "results": [
                            {"skill_name": "设计维度", "analysis": "布局清晰"},
                            {"skill_name": "价格策略", "analysis": "补贴突出"},
                        ]
                    },
                }

        class FakeEmbedder:
            def __init__(self):
                self.texts = []

            async def embed_single(self, text):
                self.texts.append(text)
                return [0.0] * settings.effective_embedding_dim()

        fake_analyzer = FakeAnalyzer()
        fake_embedder = FakeEmbedder()
        old_analyzer = images_router.analyzer
        old_embedder = images_router.embedder
        images_router.analyzer = fake_analyzer
        images_router.embedder = fake_embedder

        db = SessionLocal()
        request = task = image = None
        try:
            snapshot = [
                {"skill_id": "design", "name": "设计维度", "instruction_md": "# 设计维度\n分析布局。", "is_official": True},
                {"skill_id": "price", "name": "价格策略", "instruction_md": "# 价格策略\n分析价格。", "is_official": False},
            ]
            request = crud.create_request(db, schemas.RequestCreate(target_app="淘宝", target_scenario="搜索页"))
            task = crud.create_task(
                db,
                name="dynamic-analysis-test",
                keyword="",
                target_app="淘宝",
                target_scenario="搜索页",
                request_id=request.id,
                analysis_skill_snapshots=snapshot,
            )
            image = crud.create_image(db, schemas.ImageCreate(file_path="data/dynamic-analysis.png", task_id=task.id))

            asyncio.run(images_router._analyze_and_embed(image.id))

            analysis = crud.get_analysis_by_image(db, image.id)
            self.assertEqual(fake_analyzer.snapshots, snapshot)
            self.assertEqual(analysis.custom_analysis_json["results"][1]["skill_name"], "价格策略")
            self.assertIn("补贴突出", fake_embedder.texts[0])
            embeddings = db.query(models.Embedding).filter(models.Embedding.analysis_id == analysis.id).all()
            self.assertIn("combined", [embedding.content_type for embedding in embeddings])
        finally:
            images_router.analyzer = old_analyzer
            images_router.embedder = old_embedder
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.query(models.Embedding).filter(models.Embedding.analysis_id == analysis.id).delete()
                    db.delete(analysis)
                db.delete(image)
            if task:
                db.delete(task)
            if request:
                db.delete(request)
            db.commit()
            db.close()

    def test_search_by_text_finds_custom_analysis_json_result(self):
        from app import crud, models, schemas
        from app.database import SessionLocal

        db = SessionLocal()
        image = None
        try:
            image = crud.create_image(db, schemas.ImageCreate(file_path=f"data/custom-{uuid4().hex}.png"))
            crud.create_analysis(
                db,
                image.id,
                "",
                "",
                custom_analysis_json={"results": [{"skill_name": "价格策略", "analysis": "会员价补贴非常突出"}]},
            )

            rows = crud.search_by_text(db, "会员价补贴", limit=10)

            self.assertIn(image.id, [row_image.id for _, row_image in rows])
        finally:
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.query(models.Embedding).filter(models.Embedding.analysis_id == analysis.id).delete()
                    db.delete(analysis)
                db.delete(image)
            db.commit()
            db.close()

    def test_export_flattens_custom_analysis_results(self):
        from app.services.exporter import _flatten_analysis

        rows = _flatten_analysis({
            "id": "image-1",
            "file_path": "data/a.png",
            "analysis": {
                "id": "analysis-1",
                "custom_analysis_json": {
                    "results": [{"skill_name": "价格策略", "analysis": "补贴突出"}]
                },
            },
        })

        self.assertEqual(rows[0]["skill_name"], "价格策略")
        self.assertEqual(rows[0]["analysis_text"], "补贴突出")

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
        instruction = machine.next_instruction(finished=False)
        self.assertIn("X、×或“关闭”按钮", instruction)
        self.assertIn("禁止点击开心收下", instruction)
        self.assertNotIn("返回键", instruction)

    def test_autoglm_prompt_asks_agent_to_stop_without_screenshot_instructions(self):
        import importlib.util

        sys.path.insert(0, PROJECT_ROOT)
        spec = importlib.util.spec_from_file_location("run_autoglm_module", os.path.join(PROJECT_ROOT, "run_autoglm.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        prompt = module._append_auto_screenshot_stop_rule("打开拼多多App，找到百亿补贴")
        prompt_again = module._append_auto_screenshot_stop_rule(prompt)

        self.assertIn("到达目标页面后停留并结束任务", prompt)
        self.assertNotIn("截图保存到本地", prompt)
        self.assertNotIn("系统设置", prompt)
        self.assertEqual(prompt, prompt_again)

    def test_autoglm_pre_action_capture_policy_skips_finish_duplicates(self):
        import importlib.util

        sys.path.insert(0, PROJECT_ROOT)
        spec = importlib.util.spec_from_file_location("run_autoglm_module", os.path.join(PROJECT_ROOT, "run_autoglm.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertTrue(module._should_capture_before_action({"_metadata": "do", "action": "Tap"}))
        self.assertFalse(module._should_capture_before_action({"_metadata": "finish", "message": "done"}))
        self.assertFalse(module._should_capture_before_action({"_metadata": "do", "action": "Wait"}))
        self.assertFalse(module._should_capture_before_action({"_metadata": "do", "action": "Type"}))
        self.assertFalse(module._should_capture_before_action({"_metadata": "do", "action": "Launch"}))

    def test_autoglm_pre_action_capture_only_for_popup_close_tasks(self):
        import importlib.util

        sys.path.insert(0, PROJECT_ROOT)
        spec = importlib.util.spec_from_file_location("run_autoglm_module", os.path.join(PROJECT_ROOT, "run_autoglm.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertTrue(module._should_install_pre_action_capture("如果有弹窗先截图，然后关闭弹窗后再截图"))
        self.assertFalse(module._should_install_pre_action_capture("打开拼多多App，进入拼多多首页，再进入限时秒杀页面"))

    def test_autoglm_step_screenshot_skips_finished_step_duplicates(self):
        import importlib.util

        sys.path.insert(0, PROJECT_ROOT)
        spec = importlib.util.spec_from_file_location("run_autoglm_module", os.path.join(PROJECT_ROOT, "run_autoglm.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertTrue(module._should_save_step_screenshot(SimpleNamespace(success=True, finished=False)))
        self.assertFalse(module._should_save_step_screenshot(SimpleNamespace(success=True, finished=True)))
        self.assertFalse(module._should_save_step_screenshot(SimpleNamespace(success=False, finished=False)))

    def test_autoglm_resolves_app_package_for_exit(self):
        import importlib.util

        sys.path.insert(0, PROJECT_ROOT)
        spec = importlib.util.spec_from_file_location("run_autoglm_module", os.path.join(PROJECT_ROOT, "run_autoglm.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertEqual(module._resolve_app_package("拼多多"), "com.xunmeng.pinduoduo")
        self.assertEqual(module._resolve_app_package(" 拼多多 "), "com.xunmeng.pinduoduo")
        self.assertIsNone(module._resolve_app_package(""))
        self.assertIsNone(module._resolve_app_package("不存在的App"))

    def test_autoglm_force_stops_completed_app_on_device(self):
        import importlib.util

        sys.path.insert(0, PROJECT_ROOT)
        spec = importlib.util.spec_from_file_location("run_autoglm_module", os.path.join(PROJECT_ROOT, "run_autoglm.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        calls = []
        old_run = module.subprocess.run
        try:
            module.subprocess.run = lambda cmd, **kwargs: calls.append((cmd, kwargs)) or SimpleNamespace(returncode=0, stderr="")

            stopped = module._force_stop_app("拼多多", device_id="device-1")
        finally:
            module.subprocess.run = old_run

        self.assertTrue(stopped)
        self.assertEqual(calls[0][0], ["adb", "-s", "device-1", "shell", "am", "force-stop", "com.xunmeng.pinduoduo"])
        self.assertTrue(calls[0][1]["capture_output"])
        self.assertTrue(calls[0][1]["text"])

    def test_autoglm_pre_action_capture_wraps_execution_before_tap(self):
        import importlib.util

        sys.path.insert(0, PROJECT_ROOT)
        spec = importlib.util.spec_from_file_location("run_autoglm_module", os.path.join(PROJECT_ROOT, "run_autoglm.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        events = []

        class FakeHandler:
            def execute(self, action, width, height):
                events.append(("execute", action, width, height))
                return "result"

        agent = SimpleNamespace(
            action_handler=FakeHandler(),
            agent_config=SimpleNamespace(device_id="device-1"),
        )

        old_capture = module._capture_and_save
        try:
            module._capture_and_save = lambda *args, **kwargs: events.append(("capture", args, kwargs)) or "/tmp/pre.png"
            module._install_pre_action_screenshot_capture(
                agent,
                output_dir="/tmp/out",
                source_app="京东",
                task_id="task-1",
                task_run_id="run-1",
                db_device_id="db-device-1",
            )

            result = agent.action_handler.execute({"_metadata": "do", "action": "Tap"}, 1080, 2400)

            self.assertEqual(result, "result")
            self.assertEqual(events[0][0], "capture")
            self.assertEqual(events[1], ("execute", {"_metadata": "do", "action": "Tap"}, 1080, 2400))
            self.assertEqual(events[0][1][0], "pre_action_0")
            self.assertEqual(events[0][1][1], "/tmp/out")
            self.assertEqual(events[0][1][2], "京东")
            self.assertEqual(events[0][1][3], "device-1")
            self.assertEqual(events[0][1][4], "task-1")
            self.assertEqual(events[0][1][5], "run-1")
            self.assertEqual(events[0][1][6], "db-device-1")
        finally:
            module._capture_and_save = old_capture

    def test_autoglm_multi_goal_guard_rejects_first_step_finish(self):
        import importlib.util

        sys.path.insert(0, PROJECT_ROOT)
        spec = importlib.util.spec_from_file_location("run_autoglm_module", os.path.join(PROJECT_ROOT, "run_autoglm.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        guard = module.SequentialGoalFinishGuard(
            "目标页面顺序：1. 首页（判定条件：首页、底部主导航）；2. 百亿补贴会场（判定条件：百亿补贴会场）。"
        )

        self.assertFalse(guard.should_accept_finish())
        instruction = guard.next_instruction(finished=True)
        self.assertIn("多目标截图任务尚未按顺序完成", instruction)
        self.assertIn("第1个目标页面：首页", instruction)
        self.assertIn("当前页面只满足后续目标", instruction)

    def test_autoglm_multi_goal_guard_accepts_finish_after_navigation(self):
        import importlib.util

        sys.path.insert(0, PROJECT_ROOT)
        spec = importlib.util.spec_from_file_location("run_autoglm_module", os.path.join(PROJECT_ROOT, "run_autoglm.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        guard = module.SequentialGoalFinishGuard("目标页面顺序：1. 首页；2. 百亿补贴会场。")
        guard.record_action({"_metadata": "do", "action": "Tap"})

        self.assertTrue(guard.should_accept_finish())
        self.assertIsNone(guard.next_instruction(finished=True))

    def test_target_goal_builder_splits_multi_page_scenario(self):
        from app.services.task_goals import build_target_goals

        goals = build_target_goals(
            target_app="拼多多",
            target_scenario="限时秒杀，百亿补贴",
            keywords=[],
            description="针对“限时秒杀”和“百亿补贴”两个页面进行截图",
        )

        self.assertEqual([goal["label"] for goal in goals], ["限时秒杀", "百亿补贴"])
        self.assertTrue(all(goal["required"] for goal in goals))

    def test_goal_checklist_is_added_to_autoglm_prompt(self):
        from app.services.task_goals import append_target_goal_checklist, build_target_goals

        goals = build_target_goals("拼多多", "限时秒杀，百亿补贴", [], None)
        prompt = append_target_goal_checklist("打开拼多多App，找到限时秒杀，百亿补贴，并截图保存到本地", goals)

        self.assertIn("目标页面顺序", prompt)
        self.assertIn("1. 限时秒杀", prompt)
        self.assertIn("2. 百亿补贴", prompt)
        self.assertIn("到达最后一个目标页面后停留并结束任务", prompt)

    def test_goal_checklist_includes_structural_evidence_and_order_guard(self):
        from app.services.task_goals import append_target_goal_checklist, build_target_goals

        goals = build_target_goals("淘宝", "首页、百亿补贴会场", [], None)
        prompt = append_target_goal_checklist("打开淘宝App，进入首页，再进入百亿补贴会场", goals)

        self.assertIn("1. 首页（判定条件：首页、底部主导航、顶部分类Tab选中推荐）", prompt)
        self.assertIn("2. 百亿补贴会场（判定条件：百亿补贴会场）", prompt)
        self.assertIn("必须按顺序逐页完成", prompt)
        self.assertIn("当前页面只满足后续目标时，不算完成前序目标", prompt)
        self.assertIn("来源文案", prompt)

    def test_campaign_goal_checklist_allows_complete_business_module_terminal_state(self):
        from app.services.task_goals import append_target_goal_checklist, build_target_goals

        goals = build_target_goals("京东", "首页和活动会场", [], None)
        prompt = append_target_goal_checklist("打开京东App，进入首页，再进入活动会场", goals)
        campaign_goal = next(goal for goal in goals if goal["label"] == "活动会场")

        self.assertTrue(campaign_goal["accepts_business_module"])
        self.assertIn("完整露出与目标等价的业务模块", prompt)
        self.assertIn("不要继续点击“更多”", prompt)
        self.assertIn("单个入口按钮", prompt)

    def test_goal_validator_reports_missing_required_target(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.services.task_goals import build_target_goals
        from app.services.goal_validator import validate_task_run_goals

        db = SessionLocal()
        task = image = None
        try:
            task = crud.create_task(
                db,
                name="goal-validator-test",
                keyword="",
                target_app="拼多多",
                target_scenario="限时秒杀，百亿补贴",
                target_goals_json=build_target_goals("拼多多", "限时秒杀，百亿补贴", [], None),
            )
            image = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/goal-validator-{uuid4().hex}.png",
                task_id=task.id,
                source_app="拼多多",
                scenario="限时秒杀，百亿补贴",
            ))
            crud.create_analysis(db, image.id, "当前页面标题为限时秒杀", "运营信息为限时秒杀活动")
            db.refresh(task)

            validation = validate_task_run_goals(task, task.images)

            self.assertEqual(validation["status"], "missing")
            self.assertEqual(validation["missing"], ["百亿补贴"])
        finally:
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.delete(analysis)
                db.delete(image)
            if task:
                db.delete(task)
            db.commit()
            db.close()

    def test_goal_validator_does_not_count_negative_keyword_mentions(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.services.task_goals import build_target_goals
        from app.services.goal_validator import validate_task_run_goals

        db = SessionLocal()
        task = image = None
        try:
            task = crud.create_task(
                db,
                name="goal-negative-test",
                keyword="",
                target_app="拼多多",
                target_scenario="限时秒杀，百亿补贴",
                target_goals_json=build_target_goals("拼多多", "限时秒杀，百亿补贴", [], None),
            )
            image = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/goal-negative-{uuid4().hex}.png",
                task_id=task.id,
                source_app="拼多多",
                scenario="限时秒杀，百亿补贴",
            ))
            crud.create_analysis(db, image.id, "当前页面标题为限时秒杀", "未出现百亿补贴频道")
            db.refresh(task)

            validation = validate_task_run_goals(task, task.images)

            self.assertEqual(validation["status"], "missing")
            self.assertEqual(validation["missing"], ["百亿补贴"])
        finally:
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.delete(analysis)
                db.delete(image)
            if task:
                db.delete(task)
            db.commit()
            db.close()

    def test_goal_validator_uses_page_evidence_goal_labels(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.services.task_goals import build_target_goals
        from app.services.goal_validator import validate_task_run_goals

        db = SessionLocal()
        task = home_image = promo_image = None
        try:
            task = crud.create_task(
                db,
                name="goal-evidence-test",
                keyword="",
                target_app="京东",
                target_scenario="首页和百亿补贴会场",
                target_goals_json=build_target_goals("京东", "首页和百亿补贴会场", [], None),
            )
            home_image = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/goal-evidence-home-{uuid4().hex}.png",
                task_id=task.id,
                source_app="京东",
                scenario="首页和百亿补贴会场",
            ))
            promo_image = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/goal-evidence-promo-{uuid4().hex}.png",
                task_id=task.id,
                source_app="京东",
                scenario="首页和百亿补贴会场",
            ))
            crud.create_analysis(
                db,
                home_image.id,
                "页面是京东首页首屏",
                "首页展示补贴入口",
                custom_analysis_json={
                    "page_evidence": {
                        "matched_target_key": "home_page",
                        "matched_target_name": "首页",
                        "matched_goal_labels": ["首页"],
                        "confidence": 0.92,
                        "negative_evidence": [],
                    }
                },
            )
            crud.create_analysis(
                db,
                promo_image.id,
                "页面标题为挑好物逛京东",
                "页面出现国家补贴×百亿补贴和补贴价商品流",
                custom_analysis_json={
                    "page_evidence": {
                        "matched_target_key": "subsidy_landing",
                        "matched_target_name": "补贴商品会场",
                        "matched_goal_labels": ["百亿补贴会场"],
                        "confidence": 0.86,
                        "negative_evidence": [],
                    }
                },
            )
            db.refresh(task)

            validation = validate_task_run_goals(task, task.images)

            self.assertEqual(validation["status"], "matched")
            self.assertEqual(validation["missing"], [])
            self.assertEqual(sorted(validation["matched"]), ["百亿补贴会场", "首页"])
        finally:
            for image in (promo_image, home_image):
                if image:
                    analysis = crud.get_analysis_by_image(db, image.id)
                    if analysis:
                        db.delete(analysis)
                    db.delete(image)
            if task:
                db.delete(task)
            db.commit()
            db.close()

    def test_goal_validator_ignores_negative_evidence_for_other_goals(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.services.task_goals import build_target_goals
        from app.services.goal_validator import validate_task_run_goals

        db = SessionLocal()
        task = home_image = promo_image = None
        try:
            task = crud.create_task(
                db,
                name="goal-unrelated-negative-test",
                keyword="",
                target_app="淘宝",
                target_scenario="首页和百亿补贴会场",
                target_goals_json=build_target_goals("淘宝", "首页和百亿补贴会场", [], None),
            )
            home_image = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/goal-unrelated-negative-home-{uuid4().hex}.png",
                task_id=task.id,
                source_app="淘宝",
            ))
            promo_image = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/goal-unrelated-negative-promo-{uuid4().hex}.png",
                task_id=task.id,
                source_app="淘宝",
            ))
            crud.create_analysis(
                db,
                home_image.id,
                "截图显示淘宝首页首屏",
                "首页可见百亿补贴入口，但未进入百亿补贴会场",
                status="success",
                custom_analysis_json={
                    "page_evidence": {
                        "matched_target_name": "首页",
                        "matched_goal_labels": ["首页"],
                        "confidence": 0.96,
                        "page_state": "app_home",
                        "target_role": "home",
                        "is_terminal_target": True,
                        "needs_more_wait": False,
                        "negative_evidence": ["未进入百亿补贴会场，未见会场页标题"],
                    }
                },
            )
            crud.create_analysis(
                db,
                promo_image.id,
                "截图显示淘宝百亿补贴会场",
                "会场内可见补贴商品流",
                status="success",
                custom_analysis_json={
                    "page_evidence": {
                        "matched_target_name": "百亿补贴会场",
                        "matched_goal_labels": ["百亿补贴会场"],
                        "confidence": 0.95,
                        "page_state": "target_page",
                        "target_role": "promo_channel",
                        "is_terminal_target": True,
                        "needs_more_wait": False,
                        "negative_evidence": ["不是首页：未见淘宝底部主导航首页选中"],
                    }
                },
            )

            validation = validate_task_run_goals(task, [home_image, promo_image])

            self.assertEqual(validation["status"], "matched")
            self.assertEqual(validation["missing"], [])
        finally:
            for image in (promo_image, home_image):
                if image:
                    analysis = crud.get_analysis_by_image(db, image.id)
                    if analysis:
                        db.delete(analysis)
                    db.delete(image)
            if task:
                db.delete(task)
            db.commit()
            db.close()

    def test_goal_validator_rejects_non_terminal_home_keyword_mentions(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.services.goal_validator import validate_task_run_goals

        db = SessionLocal()
        task = image = None
        try:
            task = crud.create_task(
                db,
                name="goal-non-terminal-home-test",
                keyword="",
                target_app="淘宝",
                target_scenario="首页和活动会场",
                target_goals_json=[
                    {
                        "label": "首页",
                        "type": "page",
                        "required": True,
                        "evidence_keywords": ["首页"],
                    }
                ],
            )
            image = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/goal-non-terminal-home-{uuid4().hex}.png",
                task_id=task.id,
                source_app="淘宝",
                scenario="首页和活动会场",
            ))
            crud.create_analysis(
                db,
                image.id,
                "页面文案提示从淘宝首页来访，但当前是活动频道入口",
                "运营入口展示活动频道商品流",
                status="success",
                custom_analysis_json={
                    "page_evidence": {
                        "matched_target_key": "home_page",
                        "matched_target_name": "首页",
                        "matched_goal_labels": ["首页"],
                        "confidence": 0.9,
                        "page_state": "intermediate",
                        "target_role": "promo_entry",
                        "is_terminal_target": False,
                        "needs_more_wait": False,
                        "negative_evidence": ["当前只是入口页，不是首页终态截图"],
                    }
                },
            )
            db.refresh(task)

            validation = validate_task_run_goals(task, task.images)

            self.assertEqual(validation["status"], "missing")
            self.assertEqual(validation["missing"], ["首页"])
        finally:
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.delete(analysis)
                db.delete(image)
            if task:
                db.delete(task)
            db.commit()
            db.close()

    def test_build_target_goals_adds_app_specific_home_definition(self):
        from app.services.task_goals import build_target_goals

        taobao_home = next(
            goal
            for goal in build_target_goals("淘宝", "首页和百亿会场", [], None)
            if goal["label"] == "首页"
        )
        jd_home = next(
            goal
            for goal in build_target_goals("京东", "首页和百亿会场", [], None)
            if goal["label"] == "首页"
        )

        self.assertIn("底部主导航", taobao_home["evidence_keywords"])
        self.assertIn("顶部分类Tab选中推荐", taobao_home["evidence_keywords"])
        self.assertIn("底部主导航", jd_home["evidence_keywords"])
        self.assertIn("顶部分类Tab选中首页", jd_home["evidence_keywords"])

    def test_page_evidence_targets_include_structural_home_definition(self):
        from app import crud, schemas, models
        from app.database import SessionLocal
        from app.routers.images import _page_evidence_targets
        from app.services.task_goals import build_target_goals

        db = SessionLocal()
        task = image = None
        try:
            task = crud.create_task(
                db,
                name="home-definition-target-test",
                keyword="",
                target_app="淘宝",
                target_scenario="首页和百亿会场",
                target_goals_json=build_target_goals("淘宝", "首页和百亿会场", [], None),
            )
            image = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/home-definition-target-{uuid4().hex}.png",
                task_id=task.id,
                source_app="淘宝",
                scenario="首页和百亿会场",
            ))
            targets = _page_evidence_targets(db, image)
            home_target = next(target for target in targets if target["target_name"] == "首页")

            self.assertIn("底部主导航", home_target["description"])
            self.assertIn("顶部分类Tab选中推荐", home_target["description"])
        finally:
            if image:
                db.query(models.Image).filter(models.Image.id == image.id).delete()
            if task:
                db.query(models.Task).filter(models.Task.id == task.id).delete()
            db.commit()
            db.close()

    def test_page_evidence_targets_include_business_module_acceptance_for_campaign_goals(self):
        from app import crud, schemas, models
        from app.database import SessionLocal
        from app.routers.images import _page_evidence_targets
        from app.services.task_goals import build_target_goals

        db = SessionLocal()
        task = image = None
        try:
            task = crud.create_task(
                db,
                name="campaign-module-target-test",
                keyword="",
                target_app="京东",
                target_scenario="首页和活动会场",
                target_goals_json=build_target_goals("京东", "首页和活动会场", [], None),
            )
            image = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/campaign-module-target-{uuid4().hex}.png",
                task_id=task.id,
                source_app="京东",
                scenario="首页和活动会场",
            ))
            targets = _page_evidence_targets(db, image)
            campaign_target = next(target for target in targets if target["target_name"] == "活动会场")

            self.assertIn("完整露出", campaign_target["description"])
            self.assertIn("多个商品/权益", campaign_target["description"])
            self.assertIn("单个入口按钮", campaign_target["description"])
        finally:
            if image:
                db.query(models.Image).filter(models.Image.id == image.id).delete()
            if task:
                db.query(models.Task).filter(models.Task.id == task.id).delete()
            db.commit()
            db.close()

    def test_goal_validator_requires_goal_order(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.services.goal_validator import validate_task_run_goals

        db = SessionLocal()
        task = promo_image = home_image = None
        try:
            task = crud.create_task(
                db,
                name="goal-order-test",
                keyword="",
                target_app="淘宝",
                target_scenario="先首页再活动会场",
                target_goals_json=[
                    {"label": "首页", "type": "page", "required": True, "evidence_keywords": ["首页"]},
                    {"label": "活动会场", "type": "page", "required": True, "evidence_keywords": ["活动会场"]},
                ],
            )
            promo_image = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/goal-order-promo-{uuid4().hex}.png",
                task_id=task.id,
                source_app="淘宝",
            ))
            home_image = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/goal-order-home-{uuid4().hex}.png",
                task_id=task.id,
                source_app="淘宝",
            ))
            crud.create_analysis(
                db,
                promo_image.id,
                "活动会场首屏",
                "活动会场运营信息",
                status="success",
                custom_analysis_json={
                    "page_evidence": {
                        "matched_target_key": "promo_landing",
                        "matched_target_name": "活动会场",
                        "matched_goal_labels": ["活动会场"],
                        "confidence": 0.92,
                        "page_state": "target_page",
                        "target_role": "promo_channel",
                        "is_terminal_target": True,
                        "needs_more_wait": False,
                        "negative_evidence": [],
                    }
                },
            )
            crud.create_analysis(
                db,
                home_image.id,
                "淘宝首页首屏",
                "首页运营信息",
                status="success",
                custom_analysis_json={
                    "page_evidence": {
                        "matched_target_key": "home_page",
                        "matched_target_name": "首页",
                        "matched_goal_labels": ["首页"],
                        "confidence": 0.93,
                        "page_state": "app_home",
                        "target_role": "home",
                        "is_terminal_target": True,
                        "needs_more_wait": False,
                        "negative_evidence": [],
                    }
                },
            )

            validation = validate_task_run_goals(task, [promo_image, home_image])

            self.assertEqual(validation["status"], "missing")
            self.assertTrue(validation.get("order_error"))
            self.assertIn("活动会场", validation["missing"])
        finally:
            for image in (home_image, promo_image):
                if image:
                    analysis = crud.get_analysis_by_image(db, image.id)
                    if analysis:
                        db.delete(analysis)
                    db.delete(image)
            if task:
                db.delete(task)
            db.commit()
            db.close()

    def test_goal_validator_accepts_ordered_subsequence_after_noise(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.services.goal_validator import validate_task_run_goals

        def create_evidence(db, task, label, state, confidence=0.93):
            image = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/goal-order-noise-{label}-{uuid4().hex}.png",
                task_id=task.id,
                source_app="淘宝",
            ))
            crud.create_analysis(
                db,
                image.id,
                f"{label}首屏",
                f"{label}运营信息",
                status="success",
                custom_analysis_json={
                    "page_evidence": {
                        "matched_target_key": label,
                        "matched_target_name": label,
                        "matched_goal_labels": [label],
                        "confidence": confidence,
                        "page_state": state,
                        "target_role": "target",
                        "is_terminal_target": True,
                        "needs_more_wait": False,
                        "negative_evidence": [],
                    }
                },
            )
            return image

        db = SessionLocal()
        task = None
        images = []
        try:
            task = crud.create_task(
                db,
                name="goal-order-noise-test",
                keyword="",
                target_app="淘宝",
                target_scenario="先首页再活动会场",
                target_goals_json=[
                    {"label": "首页", "type": "page", "required": True, "evidence_keywords": ["首页"]},
                    {"label": "活动会场", "type": "page", "required": True, "evidence_keywords": ["活动会场"]},
                ],
            )
            images.append(create_evidence(db, task, "活动会场", "target_page"))
            images.append(create_evidence(db, task, "首页", "app_home"))
            images.append(create_evidence(db, task, "活动会场", "target_page", confidence=0.96))

            validation = validate_task_run_goals(task, images)

            self.assertEqual(validation["status"], "matched")
            self.assertFalse(validation.get("order_error"))
            self.assertEqual(validation["missing"], [])
        finally:
            for image in reversed(images):
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.delete(analysis)
                db.delete(image)
            if task:
                db.delete(task)
            db.commit()
            db.close()

    def test_finish_run_marks_missing_required_goal_as_failed(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.services.collector_bridge import _finish_run
        from app.services.task_goals import build_target_goals

        db = SessionLocal()
        task = image = run = None
        try:
            task = crud.create_task(
                db,
                name="goal-finish-test",
                keyword="",
                target_app="拼多多",
                target_scenario="限时秒杀，百亿补贴",
                target_goals_json=build_target_goals("拼多多", "限时秒杀，百亿补贴", [], None),
            )
            run = crud.create_task_run(db, task.id, status="running")
            image = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/goal-finish-{uuid4().hex}.png",
                task_id=task.id,
                task_run_id=run.id,
                source_app="拼多多",
                scenario="限时秒杀，百亿补贴",
            ))
            crud.create_analysis(db, image.id, "当前页面标题为限时秒杀", "未出现其他频道")

            _finish_run(db, task.id, run.id, "completed", exit_code=0)
            db.refresh(task)
            db.refresh(run)

            self.assertEqual(task.status, "failed")
            self.assertEqual(run.status, "failed")
            self.assertIn("缺少目标页截图：百亿补贴", run.failure_reason)
            self.assertEqual(run.goal_validation_json["status"], "missing")
        finally:
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.delete(analysis)
                db.delete(image)
            if run:
                db.delete(run)
                db.flush()
            if task:
                db.delete(task)
            db.commit()
            db.close()

    def test_goal_refresh_can_fail_completed_run_after_analysis_finishes(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.services.goal_validator import refresh_task_run_goal_validation
        from app.services.task_goals import build_target_goals

        db = SessionLocal()
        task = image = run = None
        try:
            task = crud.create_task(
                db,
                name="goal-refresh-test",
                keyword="",
                target_app="拼多多",
                target_scenario="限时秒杀，百亿补贴",
                target_goals_json=build_target_goals("拼多多", "限时秒杀，百亿补贴", [], None),
            )
            run = crud.create_task_run(db, task.id, status="completed")
            crud.update_task_status(db, task.id, "completed")
            image = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/goal-refresh-{uuid4().hex}.png",
                task_id=task.id,
                task_run_id=run.id,
                source_app="拼多多",
                scenario="限时秒杀，百亿补贴",
            ))
            crud.create_analysis(db, image.id, "当前页面标题为限时秒杀", "未出现其他频道")

            refresh_task_run_goal_validation(db, task.id, run.id)
            db.refresh(task)
            db.refresh(run)

            self.assertEqual(task.status, "failed")
            self.assertEqual(run.status, "failed")
            self.assertIn("百亿补贴", run.failure_reason)
        finally:
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.delete(analysis)
                db.delete(image)
            if run:
                db.delete(run)
            if task:
                db.delete(task)
            db.commit()
            db.close()

    def test_keyword_instruction_searches_only_for_search_scenes(self):
        from app.services.task_planner import keyword_instruction, requires_popup_close_flow, append_execution_rules

        self.assertEqual(keyword_instruction(["蓝牙耳机", "618"], "搜索结果页"), "搜索'蓝牙耳机、618'")
        self.assertEqual(keyword_instruction(["智能手表"], "商品详情页"), "搜索'智能手表'")
        self.assertEqual(keyword_instruction(["红包", "限时优惠"], "大促弹窗"), "重点关注'红包、限时优惠'相关内容")
        self.assertTrue(requires_popup_close_flow("如果有弹窗先截图，然后关闭弹窗后再截图"))

        prompt = append_execution_rules("打开淘宝秒杀，如果有弹窗先截图，然后关闭弹窗后再截图")

        self.assertIn("未完成弹窗页截图和关闭后页面截图前，禁止结束任务", prompt)
        self.assertIn("只点击明确的X、×或“关闭”按钮", prompt)
        self.assertIn("禁止点击开心收下", prompt)

    def test_goal_refresh_recovers_stale_missing_failure_when_goals_match(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.services.goal_validator import refresh_task_run_goal_validation

        db = SessionLocal()
        task = run = home_image = promo_image = None
        try:
            task = crud.create_task(
                db,
                name="goal-recovery-test",
                keyword="",
                target_app="淘宝",
                target_scenario="首页、活动会场",
                target_goals_json=[
                    {"label": "首页", "type": "page", "required": True, "evidence_keywords": ["首页"]},
                    {"label": "活动会场", "type": "page", "required": True, "evidence_keywords": ["活动会场"]},
                ],
            )
            run = crud.create_task_run(db, task.id, status="failed")
            crud.update_task_run(db, run.id, failure_reason="缺少目标页截图：活动会场")
            run = crud.get_task_run(db, run.id)
            crud.update_task_status(db, task.id, "failed")
            home_image = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/goal-recovery-home-{uuid4().hex}.png",
                task_id=task.id,
                task_run_id=run.id,
            ))
            promo_image = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/goal-recovery-promo-{uuid4().hex}.png",
                task_id=task.id,
                task_run_id=run.id,
            ))
            for image, label, state in ((home_image, "首页", "app_home"), (promo_image, "活动会场", "target_page")):
                crud.create_analysis(
                    db,
                    image.id,
                    f"{label}首屏",
                    f"{label}运营信息",
                    status="success",
                    custom_analysis_json={
                        "page_evidence": {
                            "matched_target_name": label,
                            "matched_goal_labels": [label],
                            "confidence": 0.93,
                            "page_state": state,
                            "is_terminal_target": True,
                            "needs_more_wait": False,
                            "negative_evidence": [],
                        }
                    },
                )

            validation = refresh_task_run_goal_validation(db, task.id, run.id)
            db.refresh(run)
            db.refresh(task)

            self.assertEqual(validation["status"], "matched")
            self.assertEqual(run.status, "completed")
            self.assertEqual(task.status, "completed")
        finally:
            for image in (promo_image, home_image):
                if image:
                    analysis = crud.get_analysis_by_image(db, image.id)
                    if analysis:
                        db.delete(analysis)
                    db.delete(image)
            if run:
                db.delete(run)
            if task:
                db.delete(task)
            db.commit()
            db.close()

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

    def test_images_list_supports_pagination_and_status_filters(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.routers import images as images_router

        db = SessionLocal()
        suffix = uuid4().hex
        task = None
        created_images = []
        try:
            task = crud.create_task(
                db,
                name=f"image-list-{suffix}",
                keyword="",
                target_app="淘宝",
                target_scenario="百亿补贴",
            )

            first = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/image-list-{suffix}-1.png",
                task_id=task.id,
                source_app="淘宝",
                scenario="百亿补贴",
            ))
            second = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/image-list-{suffix}-2.png",
                task_id=task.id,
                source_app="淘宝",
                scenario="百亿补贴",
            ))
            failed = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/image-list-{suffix}-failed.png",
                task_id=task.id,
                source_app="淘宝",
                scenario="百亿补贴",
            ))
            created_images.extend([first, second, failed])

            first.created_at = utc_now() + timedelta(seconds=1)
            second.created_at = utc_now() + timedelta(seconds=2)
            failed.created_at = utc_now() + timedelta(seconds=3)
            db.commit()

            first_analysis = crud.create_analysis(db, first.id, "设计 A", "运营 A", status="success")
            second_analysis = crud.create_analysis(db, second.id, "设计 B", "运营 B", status="success")
            failed_analysis = crud.create_analysis(db, failed.id, "", "分析失败", status="failed")
            crud.update_embedding_status(db, first_analysis.id, "success")
            crud.update_embedding_status(db, second_analysis.id, "success")
            crud.update_embedding_status(db, failed_analysis.id, "failed", "provider error")

            page = images_router.list_images(
                skip=1,
                limit=1,
                task_id=task.id,
                analysis_status="success",
                embedding_status="success",
                db=db,
            )
            failed_rows = images_router.list_images(
                skip=0,
                limit=10,
                task_id=task.id,
                analysis_status="failed",
                embedding_status="failed",
                db=db,
            )

            self.assertEqual(len(page), 1)
            self.assertEqual(page[0].image.id, first.id)
            self.assertEqual(page[0].analysis.status, "success")
            self.assertEqual(page[0].analysis.embedding_status, "success")
            self.assertEqual([row.image.id for row in failed_rows], [failed.id])
        finally:
            for image in created_images:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.delete(analysis)
                db.delete(image)
            if task:
                db.delete(task)
            db.commit()
            db.close()

    def test_images_list_treats_missing_analysis_as_pending(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.routers import images as images_router

        db = SessionLocal()
        suffix = uuid4().hex
        image = None
        try:
            image = crud.create_image(db, schemas.ImageCreate(
                file_path=f"data/pending-image-{suffix}.png",
                source_app="淘宝",
                scenario="待分析",
            ))

            analysis_pending = images_router.list_images(
                skip=0,
                limit=10,
                analysis_status="pending",
                db=db,
            )
            embedding_pending = images_router.list_images(
                skip=0,
                limit=10,
                embedding_status="pending",
                db=db,
            )

            self.assertIn(image.id, [row.image.id for row in analysis_pending])
            self.assertIn(image.id, [row.image.id for row in embedding_pending])
        finally:
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.delete(analysis)
                db.delete(image)
            db.commit()
            db.close()

    def test_embedder_normalizes_embedding_endpoint(self):
        from app.config import settings
        from app.services.embedder import Embedder

        old_values = {
            "OPENAI_BASE_URL": settings.OPENAI_BASE_URL,
            "EMBEDDING_API_KEY": settings.EMBEDDING_API_KEY,
            "EMBEDDING_BASE_URL": settings.EMBEDDING_BASE_URL,
            "AI_MATCH_TEXT_EMBEDDING_PROFILE": settings.AI_MATCH_TEXT_EMBEDDING_PROFILE,
            "AI_MATCH_TEXT_EMBEDDING_API_KEY": settings.AI_MATCH_TEXT_EMBEDDING_API_KEY,
            "AI_MATCH_TEXT_EMBEDDING_ENDPOINT": settings.AI_MATCH_TEXT_EMBEDDING_ENDPOINT,
        }
        try:
            settings.OPENAI_BASE_URL = "https://modelservice.jdcloud.com/v1/"
            settings.EMBEDDING_API_KEY = ""
            settings.EMBEDDING_BASE_URL = ""
            settings.AI_MATCH_TEXT_EMBEDDING_PROFILE = ""
            settings.AI_MATCH_TEXT_EMBEDDING_API_KEY = ""
            settings.AI_MATCH_TEXT_EMBEDDING_ENDPOINT = ""

            embedder = Embedder()

            self.assertEqual(embedder.embedding_url, "https://modelservice.jdcloud.com/v1/embeddings")
        finally:
            for name, value in old_values.items():
                setattr(settings, name, value)

    def test_embedder_health_returns_configuration_without_network_call(self):
        from app.config import settings
        from app.services.embedder import Embedder

        old_values = {
            "OPENAI_API_KEY": settings.OPENAI_API_KEY,
            "OPENAI_BASE_URL": settings.OPENAI_BASE_URL,
            "EMBEDDING_API_KEY": settings.EMBEDDING_API_KEY,
            "EMBEDDING_BASE_URL": settings.EMBEDDING_BASE_URL,
            "EMBEDDING_MODEL": settings.EMBEDDING_MODEL,
            "AI_MATCH_TEXT_EMBEDDING_PROFILE": settings.AI_MATCH_TEXT_EMBEDDING_PROFILE,
        }
        try:
            settings.OPENAI_API_KEY = "test-key"
            settings.OPENAI_BASE_URL = "https://example.com/v1/"
            settings.EMBEDDING_API_KEY = ""
            settings.EMBEDDING_BASE_URL = ""
            settings.EMBEDDING_MODEL = "embedding-model"
            settings.AI_MATCH_TEXT_EMBEDDING_PROFILE = ""

            health = Embedder().health()

            self.assertTrue(health["configured"])
            self.assertEqual(health["endpoint"], "https://example.com/v1/embeddings")
            self.assertEqual(health["model"], "embedding-model")
        finally:
            for name, value in old_values.items():
                setattr(settings, name, value)

    def test_embedder_prefers_embedding_specific_provider_config(self):
        from app.config import settings
        from app.services.embedder import Embedder

        old_values = {
            "OPENAI_API_KEY": settings.OPENAI_API_KEY,
            "OPENAI_BASE_URL": settings.OPENAI_BASE_URL,
            "EMBEDDING_API_KEY": settings.EMBEDDING_API_KEY,
            "EMBEDDING_BASE_URL": settings.EMBEDDING_BASE_URL,
            "AI_MATCH_TEXT_EMBEDDING_PROFILE": settings.AI_MATCH_TEXT_EMBEDDING_PROFILE,
        }
        try:
            settings.OPENAI_API_KEY = "openai-key"
            settings.OPENAI_BASE_URL = "https://openai.example/v1"
            settings.EMBEDDING_API_KEY = "embedding-key"
            settings.EMBEDDING_BASE_URL = "https://embedding.example/v1/"
            settings.AI_MATCH_TEXT_EMBEDDING_PROFILE = ""

            embedder = Embedder()

            self.assertEqual(embedder.api_key, "embedding-key")
            self.assertEqual(embedder.embedding_url, "https://embedding.example/v1/embeddings")
        finally:
            for name, value in old_values.items():
                setattr(settings, name, value)

    def test_embedder_accepts_ai_match_text_embedding_config(self):
        from app.config import settings
        from app.services.embedder import Embedder

        old_values = {
            "EMBEDDING_API_KEY": settings.EMBEDDING_API_KEY,
            "EMBEDDING_BASE_URL": settings.EMBEDDING_BASE_URL,
            "EMBEDDING_MODEL": settings.EMBEDDING_MODEL,
            "EMBEDDING_DIM": settings.EMBEDDING_DIM,
            "AI_MATCH_TEXT_EMBEDDING_API_KEY": settings.AI_MATCH_TEXT_EMBEDDING_API_KEY,
            "AI_MATCH_TEXT_EMBEDDING_ENDPOINT": settings.AI_MATCH_TEXT_EMBEDDING_ENDPOINT,
            "AI_MATCH_TEXT_EMBEDDING_MODEL": settings.AI_MATCH_TEXT_EMBEDDING_MODEL,
            "AI_MATCH_TEXT_EMBEDDING_PROFILE": settings.AI_MATCH_TEXT_EMBEDDING_PROFILE,
            "AI_MATCH_TEXT_VECTOR_DIMENSION": settings.AI_MATCH_TEXT_VECTOR_DIMENSION,
        }
        try:
            settings.EMBEDDING_API_KEY = ""
            settings.EMBEDDING_BASE_URL = ""
            settings.EMBEDDING_MODEL = ""
            settings.EMBEDDING_DIM = 0
            settings.AI_MATCH_TEXT_EMBEDDING_API_KEY = "ai-match-key"
            settings.AI_MATCH_TEXT_EMBEDDING_ENDPOINT = "https://ai-match.example/v1"
            settings.AI_MATCH_TEXT_EMBEDDING_MODEL = "ai-match-text-model"
            settings.AI_MATCH_TEXT_EMBEDDING_PROFILE = ""
            settings.AI_MATCH_TEXT_VECTOR_DIMENSION = 512

            embedder = Embedder()

            self.assertEqual(embedder.api_key, "ai-match-key")
            self.assertEqual(embedder.embedding_url, "https://ai-match.example/v1/embeddings")
            self.assertEqual(embedder.model, "ai-match-text-model")
            self.assertEqual(embedder.dim, 512)
        finally:
            for name, value in old_values.items():
                setattr(settings, name, value)

    def test_embedder_uses_doubao_profile_config(self):
        from app.config import settings
        from app.services.embedder import Embedder

        old_values = {
            "EMBEDDING_API_KEY": settings.EMBEDDING_API_KEY,
            "EMBEDDING_BASE_URL": settings.EMBEDDING_BASE_URL,
            "EMBEDDING_MODEL": settings.EMBEDDING_MODEL,
            "EMBEDDING_DIM": settings.EMBEDDING_DIM,
            "AI_MATCH_TEXT_EMBEDDING_PROFILE": settings.AI_MATCH_TEXT_EMBEDDING_PROFILE,
            "AI_MATCH_DOUBAO_EMBEDDING_API_KEY": settings.AI_MATCH_DOUBAO_EMBEDDING_API_KEY,
            "AI_MATCH_DOUBAO_EMBEDDING_ENDPOINT": settings.AI_MATCH_DOUBAO_EMBEDDING_ENDPOINT,
            "AI_MATCH_DOUBAO_EMBEDDING_MODEL": settings.AI_MATCH_DOUBAO_EMBEDDING_MODEL,
            "AI_MATCH_DOUBAO_VECTOR_DIMENSION": settings.AI_MATCH_DOUBAO_VECTOR_DIMENSION,
            "AI_MATCH_DOUBAO_SEND_DIMENSIONS": settings.AI_MATCH_DOUBAO_SEND_DIMENSIONS,
            "AI_MATCH_DOUBAO_EMBEDDING_FORMAT": settings.AI_MATCH_DOUBAO_EMBEDDING_FORMAT,
        }
        try:
            settings.EMBEDDING_API_KEY = "old-key"
            settings.EMBEDDING_BASE_URL = "https://old.example/v1"
            settings.EMBEDDING_MODEL = "old-model"
            settings.EMBEDDING_DIM = 512
            settings.AI_MATCH_TEXT_EMBEDDING_PROFILE = "doubao"
            settings.AI_MATCH_DOUBAO_EMBEDDING_API_KEY = "doubao-key"
            settings.AI_MATCH_DOUBAO_EMBEDDING_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3"
            settings.AI_MATCH_DOUBAO_EMBEDDING_MODEL = "Doubao-embedding"
            settings.AI_MATCH_DOUBAO_VECTOR_DIMENSION = 2048
            settings.AI_MATCH_DOUBAO_SEND_DIMENSIONS = 0
            settings.AI_MATCH_DOUBAO_EMBEDDING_FORMAT = ""

            embedder = Embedder()

            self.assertEqual(embedder.api_key, "doubao-key")
            self.assertEqual(embedder.embedding_url, "https://ark.cn-beijing.volces.com/api/v3/embeddings")
            self.assertEqual(embedder.model, "Doubao-embedding")
            self.assertEqual(embedder.dim, 2048)
            self.assertEqual(embedder.health()["provider"], "doubao")
        finally:
            for name, value in old_values.items():
                setattr(settings, name, value)

    def test_doubao_multimodal_format_uses_multimodal_endpoint_and_payload(self):
        from app.config import settings
        from app.services.embedder import Embedder

        old_values = {
            "AI_MATCH_TEXT_EMBEDDING_PROFILE": settings.AI_MATCH_TEXT_EMBEDDING_PROFILE,
            "AI_MATCH_DOUBAO_EMBEDDING_API_KEY": settings.AI_MATCH_DOUBAO_EMBEDDING_API_KEY,
            "AI_MATCH_DOUBAO_EMBEDDING_ENDPOINT": settings.AI_MATCH_DOUBAO_EMBEDDING_ENDPOINT,
            "AI_MATCH_DOUBAO_EMBEDDING_MODEL": settings.AI_MATCH_DOUBAO_EMBEDDING_MODEL,
            "AI_MATCH_DOUBAO_EMBEDDING_FORMAT": settings.AI_MATCH_DOUBAO_EMBEDDING_FORMAT,
        }
        try:
            settings.AI_MATCH_TEXT_EMBEDDING_PROFILE = "doubao"
            settings.AI_MATCH_DOUBAO_EMBEDDING_API_KEY = "doubao-key"
            settings.AI_MATCH_DOUBAO_EMBEDDING_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3"
            settings.AI_MATCH_DOUBAO_EMBEDDING_MODEL = "Doubao-embedding"
            settings.AI_MATCH_DOUBAO_EMBEDDING_FORMAT = "doubao-multimodal"

            embedder = Embedder()

            self.assertEqual(
                embedder.embedding_url,
                "https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal",
            )
            self.assertEqual(
                embedder._request_payload(["health check"]),
                {
                    "input": [{"type": "text", "text": "health check"}],
                    "model": "doubao-embedding-vision-251215",
                },
            )
            self.assertEqual(embedder.health()["model"], "Doubao-embedding")
        finally:
            for name, value in old_values.items():
                setattr(settings, name, value)

    def test_embedder_parses_doubao_multimodal_embedding_response(self):
        from app.services.embedder import Embedder

        embedder = Embedder()
        vectors = embedder._vectors_from_response({
            "data": {
                "embedding": [0.1, 0.2, 0.3],
                "object": "embedding",
            }
        })

        self.assertEqual(vectors, [[0.1, 0.2, 0.3]])

    def test_search_result_exposes_search_mode(self):
        from app.schemas import SearchResult

        self.assertIn("search_mode", SearchResult.model_fields)

    def test_database_vector_typmod_dim_helper(self):
        from app.database import _vector_dim_from_typmod

        self.assertEqual(_vector_dim_from_typmod(1536), 1536)
        self.assertIsNone(_vector_dim_from_typmod(-1))

    def test_effective_embedding_dim_uses_ai_match_fallback(self):
        from app.config import settings

        old_values = {
            "EMBEDDING_DIM": settings.EMBEDDING_DIM,
            "AI_MATCH_TEXT_EMBEDDING_PROFILE": settings.AI_MATCH_TEXT_EMBEDDING_PROFILE,
            "AI_MATCH_TEXT_VECTOR_DIMENSION": settings.AI_MATCH_TEXT_VECTOR_DIMENSION,
        }
        try:
            settings.EMBEDDING_DIM = 0
            settings.AI_MATCH_TEXT_EMBEDDING_PROFILE = ""
            settings.AI_MATCH_TEXT_VECTOR_DIMENSION = 512

            self.assertEqual(settings.effective_embedding_dim(), 512)
        finally:
            for name, value in old_values.items():
                setattr(settings, name, value)

    def test_create_embedding_is_idempotent_by_analysis_and_content_type(self):
        from app import crud, schemas, models
        from app.config import settings
        from app.database import SessionLocal

        db = SessionLocal()
        image = None
        try:
            dim = settings.effective_embedding_dim()
            image = crud.create_image(db, schemas.ImageCreate(file_path="data/idempotent-embedding.png"))
            analysis = crud.create_analysis(db, image.id, "设计分析", "运营分析")

            first = [0.1] * dim
            second = [0.2] * dim
            crud.create_embedding(db, analysis.id, first, "combined")
            embedding = crud.create_embedding(db, analysis.id, second, "combined")

            rows = db.query(models.Embedding).filter(
                models.Embedding.analysis_id == analysis.id,
                models.Embedding.content_type == "combined",
            ).all()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].id, embedding.id)
        finally:
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.query(models.Embedding).filter(models.Embedding.analysis_id == analysis.id).delete()
                    db.delete(analysis)
                db.delete(image)
            db.commit()
            db.close()

    def test_embedding_search_returns_one_result_per_analysis(self):
        from app import crud, schemas, models
        from app.config import settings
        from app.database import SessionLocal

        db = SessionLocal()
        image = None
        try:
            dim = settings.effective_embedding_dim()
            image = crud.create_image(db, schemas.ImageCreate(file_path="data/dedup-embedding-search.png"))
            analysis = crud.create_analysis(db, image.id, "设计分析", "运营分析")

            vector = [0.0] * dim
            crud.create_embedding(db, analysis.id, vector, "combined")
            crud.create_embedding(db, analysis.id, [0.01] * dim, "design")

            rows = crud.search_by_embedding(db, vector, limit=1000)
            analysis_ids = [row_analysis.id for _, row_analysis, _ in rows]

            self.assertEqual(analysis_ids.count(analysis.id), 1)
            self.assertEqual(len(analysis_ids), len(set(analysis_ids)))
        finally:
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.query(models.Embedding).filter(models.Embedding.analysis_id == analysis.id).delete()
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

            old_task.completed_at = utc_now() + timedelta(days=1)
            new_task.completed_at = utc_now() + timedelta(days=2)
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

    def test_admin_stats_counts_records_without_list_fetching(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.routers.admin import get_admin_stats

        db = SessionLocal()
        request = task = None
        try:
            request = crud.create_request(db, schemas.RequestCreate(target_app="淘宝", target_scenario="百亿补贴"))
            task = crud.create_task(db, name="stats task", keyword="", target_app="淘宝", target_scenario="百亿补贴")

            stats = get_admin_stats(db)

            self.assertGreaterEqual(stats["requests"], 1)
            self.assertGreaterEqual(stats["tasks"], 1)
            self.assertGreaterEqual(stats["pending_requests"], 1)
            self.assertGreaterEqual(stats["pending_tasks"], 1)
        finally:
            if task:
                db.delete(task)
            if request:
                db.delete(request)
            db.commit()
            db.close()

    def test_watch_plan_stats_include_run_count_and_latest_success(self):
        from app import crud, schemas
        from app.database import SessionLocal

        db = SessionLocal()
        plan = None
        try:
            plan = crud.create_watch_plan(db, schemas.WatchPlanCreate(
                name="stats watch",
                target_app="淘宝",
                target_page="百亿补贴",
                entry_instruction="打开淘宝，进入百亿补贴",
            ))
            yesterday = (datetime.now() - timedelta(days=1)).date()
            today = datetime.now().date()
            success_run = crud.create_watch_run(db, plan.id, yesterday)
            crud.update_watch_run(
                db,
                success_run.id,
                status="success",
                completed_at=datetime.now() - timedelta(days=1),
            )
            failed_run = crud.create_watch_run(db, plan.id, today)
            crud.update_watch_run(db, failed_run.id, status="failed", completed_at=datetime.now())

            stats = crud.get_watch_plan_stats(db, plan.id)

            self.assertEqual(stats["run_count"], 2)
            self.assertEqual(stats["latest_run_status"], "failed")
            self.assertIsNotNone(stats["latest_success_run_at"])
        finally:
            if plan:
                db.delete(plan)
            db.commit()
            db.close()

    def test_watch_detail_uses_latest_success_snapshot_when_latest_run_failed(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.routers import watch_plans as watch_plans_router

        db = SessionLocal()
        plan = image = None
        try:
            plan = crud.create_watch_plan(db, schemas.WatchPlanCreate(
                name="latest success watch",
                target_app="淘宝",
                target_page="百亿补贴",
                entry_instruction="打开淘宝，进入百亿补贴",
            ))
            yesterday = (datetime.now() - timedelta(days=1)).date()
            today = datetime.now().date()
            image = crud.create_image(db, schemas.ImageCreate(file_path="data/latest-success-watch.png"))
            crud.create_analysis(db, image.id, "昨日设计分析", "昨日运营分析")
            success_run = crud.create_watch_run(db, plan.id, yesterday)
            crud.create_watch_snapshot(db, success_run.id, image.id, is_primary=True)
            crud.create_watch_daily_summary(
                db,
                success_run.id,
                summary="昨日摘要",
                design_summary="昨日设计摘要",
                ops_summary="昨日运营摘要",
                key_modules_json=[],
                promotions_json=[],
                changes_from_previous_json={},
            )
            crud.update_watch_run(
                db,
                success_run.id,
                status="success",
                completed_at=datetime.now() - timedelta(days=1),
            )
            failed_run = crud.create_watch_run(db, plan.id, today)
            crud.update_watch_run(db, failed_run.id, status="failed", completed_at=datetime.now())

            detail = watch_plans_router._detail(plan, db)

            self.assertEqual(detail.latest_run.id, failed_run.id)
            self.assertEqual(detail.latest_success_run.id, success_run.id)
            self.assertEqual(detail.latest_snapshot.image.id, image.id)
            self.assertEqual(detail.latest_summary.summary, "昨日摘要")
        finally:
            if plan:
                db.delete(plan)
                db.flush()
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.delete(analysis)
                db.delete(image)
            db.commit()
            db.close()

    def test_watch_prompt_contains_fixed_page_first_screen_rules(self):
        from app.services.watch_service import build_watch_prompt

        plan = SimpleNamespace(
            target_app="淘宝",
            target_page="百亿补贴",
            entry_instruction="打开淘宝，从首页进入百亿补贴",
            focus_question="关注补贴利益点变化",
        )

        prompt = build_watch_prompt(plan)

        self.assertIn("目标 App：淘宝", prompt)
        self.assertIn("目标页面：百亿补贴", prompt)
        self.assertIn("只采集目标页面首屏", prompt)
        self.assertIn("不要滚动", prompt)
        self.assertIn("完成目标页首屏截图后结束", prompt)

    def test_watch_run_is_idempotent_per_plan_date(self):
        from app import crud, schemas
        from app.database import SessionLocal

        db = SessionLocal()
        plan = None
        try:
            plan = crud.create_watch_plan(db, schemas.WatchPlanCreate(
                name="idempotent watch",
                target_app="淘宝",
                target_page="百亿补贴",
                entry_instruction="打开淘宝，进入百亿补贴",
            ))
            first = crud.create_watch_run(db, plan.id, utc_now().date())
            second = crud.create_watch_run(db, plan.id, utc_now().date())

            self.assertEqual(first.id, second.id)
        finally:
            if plan:
                db.delete(plan)
            db.commit()
            db.close()

    def test_due_watch_scheduler_creates_one_run_without_process(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.services.watch_service import run_due_watch_plans

        db = SessionLocal()
        plan = task = None
        try:
            plan = crud.create_watch_plan(db, schemas.WatchPlanCreate(
                name="due watch",
                target_app="淘宝",
                target_page="秒杀",
                entry_instruction="打开淘宝，进入淘宝秒杀",
                schedule_time=time(10, 0),
            ))
            now = utc_now().replace(hour=10, minute=1, second=0, microsecond=0)
            plan.created_at = now.replace(hour=9, minute=0)
            db.commit()

            self.assertEqual(run_due_watch_plans(db, now=now, start_process=False), 1)
            self.assertEqual(run_due_watch_plans(db, now=now, start_process=False), 0)

            run = crud.get_watch_run_by_date(db, plan.id, now.date())
            task = crud.get_task(db, run.task_id)

            self.assertEqual(run.status, "running")
            self.assertEqual(task.mode, "autoglm")
            self.assertIn("固定页面观察任务", task.generated_instruction)
        finally:
            if plan:
                db.delete(plan)
                db.flush()
            if task:
                db.delete(task)
            db.commit()
            db.close()

    def test_due_watch_scheduler_skips_plans_created_after_today_schedule(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.services.watch_service import run_due_watch_plans

        db = SessionLocal()
        plan = None
        try:
            now = utc_now().replace(hour=15, minute=0, second=0, microsecond=0)
            plan = crud.create_watch_plan(db, schemas.WatchPlanCreate(
                name="late watch",
                target_app="淘宝",
                target_page="百亿补贴",
                entry_instruction="打开淘宝，进入百亿补贴",
                schedule_time=time(10, 0),
            ))
            plan.created_at = now.replace(hour=14, minute=59)
            db.commit()

            self.assertEqual(run_due_watch_plans(db, now=now, start_process=False), 0)
            self.assertIsNone(crud.get_watch_run_by_date(db, plan.id, now.date()))
        finally:
            if plan:
                db.delete(plan)
            db.commit()
            db.close()

    def test_watch_plan_due_logic_uses_selected_start_date(self):
        from app.services.watch_service import watch_plan_is_due_on

        weekly = SimpleNamespace(
            schedule_start_date=date(2026, 6, 2),
            schedule_end_date=date(2026, 6, 30),
            schedule_cycle="weekly",
        )
        monthly = SimpleNamespace(
            schedule_start_date=date(2026, 1, 31),
            schedule_end_date=date(2026, 3, 31),
            schedule_cycle="monthly",
        )

        self.assertTrue(watch_plan_is_due_on(weekly, date(2026, 6, 9)))
        self.assertFalse(watch_plan_is_due_on(weekly, date(2026, 6, 10)))
        self.assertTrue(watch_plan_is_due_on(monthly, date(2026, 3, 31)))
        self.assertFalse(watch_plan_is_due_on(monthly, date(2026, 2, 28)))

    def test_due_watch_scheduler_respects_weekly_cycle(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.services.watch_service import run_due_watch_plans

        db = SessionLocal()
        plan = None
        try:
            plan = crud.create_watch_plan(db, schemas.WatchPlanCreate(
                name="weekly watch",
                target_app="淘宝",
                target_page="百亿补贴",
                entry_instruction="打开淘宝，进入百亿补贴",
                schedule_time=time(10, 0),
                schedule_start_date=date(2026, 6, 2),
                schedule_end_date=date(2026, 6, 30),
                schedule_cycle="weekly",
            ))
            plan.created_at = datetime(2026, 6, 1, 9, 0)
            db.commit()

            self.assertEqual(run_due_watch_plans(db, now=datetime(2026, 6, 10, 10, 1), start_process=False), 0)
            self.assertEqual(run_due_watch_plans(db, now=datetime(2026, 6, 9, 10, 1), start_process=False), 1)
        finally:
            if plan:
                db.delete(plan)
            db.commit()
            db.close()

    def test_scheduled_request_due_logic_uses_selected_start_date(self):
        from app.services.request_scheduler import request_is_due_on

        weekly = SimpleNamespace(
            schedule_enabled=True,
            schedule_start_date=date(2026, 6, 2),
            schedule_end_date=date(2026, 6, 30),
            schedule_cycle="weekly",
        )
        monthly = SimpleNamespace(
            schedule_enabled=True,
            schedule_start_date=date(2026, 1, 31),
            schedule_end_date=date(2026, 3, 31),
            schedule_cycle="monthly",
        )

        self.assertTrue(request_is_due_on(weekly, date(2026, 6, 9)))
        self.assertFalse(request_is_due_on(weekly, date(2026, 6, 10)))
        self.assertTrue(request_is_due_on(monthly, date(2026, 3, 31)))
        self.assertFalse(request_is_due_on(monthly, date(2026, 2, 28)))

    def test_due_scheduled_request_creates_one_task_without_process(self):
        from app import crud, schemas
        from app.database import SessionLocal
        from app.services.request_scheduler import run_due_scheduled_requests

        db = SessionLocal()
        request = task = None
        try:
            request = crud.create_request(
                db,
                schemas.RequestCreate(
                    target_app="淘宝",
                    target_scenario="百亿补贴",
                    keywords=["补贴"],
                    description="关注利益点",
                    schedule_enabled=True,
                    schedule_start_date=date(2026, 6, 2),
                    schedule_end_date=date(2026, 6, 30),
                    schedule_time=time(10, 0),
                    schedule_cycle="weekly",
                ),
                user_id=str(uuid4()),
            )
            request = crud.approve_request(db, request.id, approved_task_mode="autoglm")
            now = datetime(2026, 6, 9, 10, 1)

            self.assertEqual(run_due_scheduled_requests(db, now=now, start_process=False), 1)
            self.assertEqual(run_due_scheduled_requests(db, now=now, start_process=False), 0)

            task = crud.get_scheduled_task_for_request_date(db, request.id, now.date())
            self.assertIsNotNone(task)
            self.assertEqual(task.mode, "autoglm")
            self.assertEqual(task.scheduled_run_date, now.date())
            self.assertEqual(task.status, "running")
            self.assertIn("百亿补贴", task.generated_instruction)
        finally:
            if task:
                db.delete(task)
            if request:
                db.delete(request)
            db.commit()
            db.close()

    def test_worker_api_requires_worker_token(self):
        from fastapi.testclient import TestClient
        from app.main import app

        client = TestClient(app)

        response = client.post("/api/worker/register", json={"node_key": f"worker-{uuid4().hex}"})

        self.assertEqual(response.status_code, 401)

    def test_worker_cli_parses_adb_devices(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("worker_main", os.path.join(PROJECT_ROOT, "worker", "main.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        devices = module.parse_adb_devices("List of devices attached\nabc123\tdevice\nxyz789\tunauthorized\n")

        self.assertEqual(devices[0]["serial"], "abc123")
        self.assertEqual(devices[0]["status"], "online")
        self.assertEqual(devices[1]["status"], "offline")

    def test_worker_claim_failure_does_not_crash_when_reporting_fails(self):
        import importlib.util
        import tempfile

        spec = importlib.util.spec_from_file_location("worker_main", os.path.join(PROJECT_ROOT, "worker", "main.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        class FailingClient:
            def __init__(self):
                self.log_attempts = 0
                self.finish_attempts = 0

            def upload_log(self, run_id, content):
                self.log_attempts += 1
                raise OSError("cloud log write failed")

            def finish(self, run_id, status, exit_code, failure_reason=None):
                self.finish_attempts += 1
                raise OSError("cloud finish failed")

        client = FailingClient()
        claim = {"run": {"id": "run-1"}, "task": {"id": "task-1"}}
        previous_run_claimed_task = module._run_claimed_task
        previous_log = module._log
        messages = []
        module._run_claimed_task = lambda *_args: (_ for _ in ()).throw(RuntimeError("boom"))
        module._log = messages.append
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                module._handle_claimed_task(client, claim, Path(temp_dir))
        finally:
            module._run_claimed_task = previous_run_claimed_task
            module._log = previous_log

        self.assertEqual(client.log_attempts, 1)
        self.assertEqual(client.finish_attempts, 1)
        self.assertTrue(any("Worker task failed" in message for message in messages))
        self.assertTrue(any("Worker failed to upload failure log" in message for message in messages))
        self.assertTrue(any("Worker failed to mark run failed" in message for message in messages))

    def test_worker_token_can_come_from_environment(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("worker_main", os.path.join(PROJECT_ROOT, "worker", "main.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        previous_token = os.environ.get("WORKER_API_TOKEN")
        os.environ["WORKER_API_TOKEN"] = "env-worker-token"
        try:
            args = module.parse_args(["--server", "http://example.test"])
        finally:
            if previous_token is None:
                os.environ.pop("WORKER_API_TOKEN", None)
            else:
                os.environ["WORKER_API_TOKEN"] = previous_token

        self.assertEqual(args.token, "env-worker-token")

    def test_worker_autoglm_command_passes_target_app_as_source_app(self):
        import importlib.util
        import tempfile

        spec = importlib.util.spec_from_file_location("worker_main", os.path.join(PROJECT_ROOT, "worker", "main.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        captured = {}
        old_run = module.subprocess.run
        try:
            def fake_run(cmd, **kwargs):
                captured["cmd"] = cmd
                log_file = kwargs.get("stdout")
                if log_file:
                    log_file.write("done")
                return SimpleNamespace(returncode=0)

            module.subprocess.run = fake_run
            claim = {
                "run": {"id": "run-1"},
                "task": {"id": "task-1", "mode": "autoglm", "target_app": "拼多多"},
                "prompt": "打开拼多多App，进入首页",
            }

            with tempfile.TemporaryDirectory() as temp_dir:
                module._run_claimed_task(claim, Path(temp_dir))
        finally:
            module.subprocess.run = old_run

        self.assertIn("--source-app", captured["cmd"])
        self.assertEqual(captured["cmd"][captured["cmd"].index("--source-app") + 1], "拼多多")

    def test_refresh_devices_marks_missing_busy_local_device_offline(self):
        from app import crud
        from app.database import SessionLocal
        from app.services import devices as device_service

        db = SessionLocal()
        stale = None
        previous_which = device_service.shutil.which
        previous_run = device_service.subprocess.run
        device_service.shutil.which = lambda name: "/usr/bin/adb"
        device_service.subprocess.run = lambda *args, **kwargs: SimpleNamespace(
            returncode=0,
            stdout="List of devices attached\nreal123\tdevice\n",
        )
        try:
            stale = crud.upsert_device(
                db,
                serial=f"missing-{uuid4().hex[:8]}",
                status="busy",
            )
            stale.current_task_run_id = uuid4()
            db.commit()

            device_service.refresh_devices(db)

            db.refresh(stale)
            self.assertEqual(stale.status, "offline")
            self.assertIsNone(stale.current_task_run_id)
            self.assertEqual(stale.notes, "not listed by adb")
        finally:
            device_service.shutil.which = previous_which
            device_service.subprocess.run = previous_run
            if stale:
                db.delete(stale)
            real = crud.get_device_by_serial(db, "real123")
            if real:
                db.delete(real)
            db.commit()
            db.close()

    def test_worker_register_heartbeat_and_device_report(self):
        from fastapi.testclient import TestClient
        from app import crud
        from app.config import settings
        from app.database import SessionLocal
        from app.main import app

        client = TestClient(app)
        headers = {"X-Worker-Token": settings.WORKER_API_TOKEN}
        node_key = f"worker-{uuid4().hex}"
        device_serial = f"adb-{uuid4().hex}"
        db = SessionLocal()
        try:
            registered = client.post(
                "/api/worker/register",
                headers=headers,
                json={"node_key": node_key, "name": "本机采集节点", "version": "test"},
            )
            self.assertEqual(registered.status_code, 200, registered.text)
            worker_id = registered.json()["id"]

            heartbeat = client.post(
                "/api/worker/heartbeat",
                headers=headers,
                json={"node_key": node_key, "status": "online"},
            )
            self.assertEqual(heartbeat.status_code, 200, heartbeat.text)

            reported = client.post(
                "/api/worker/devices",
                headers=headers,
                json={
                    "node_key": node_key,
                    "devices": [
                        {"serial": device_serial, "name": "Pixel", "status": "online", "notes": "device"}
                    ],
                },
            )
            self.assertEqual(reported.status_code, 200, reported.text)
            device_id = reported.json()["devices"][0]["id"]
            device = crud.get_device(db, UUID(device_id))

            self.assertEqual(str(device.worker_id), worker_id)
            self.assertEqual(device.source, "worker")
            self.assertEqual(device.status, "online")
        finally:
            for device in db.query(crud.models.Device).filter(crud.models.Device.serial == device_serial).all():
                db.query(crud.models.TaskRun).filter(crud.models.TaskRun.device_id == device.id).update({"device_id": None}, synchronize_session=False)
                db.delete(device)
            db.query(crud.models.Worker).filter(crud.models.Worker.node_key == node_key).delete(synchronize_session=False)
            db.commit()
            db.close()

    def test_worker_mode_queues_run_and_worker_can_claim_upload_and_complete(self):
        from fastapi.testclient import TestClient
        from app import crud
        from app.config import settings
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password

        client = TestClient(app)
        worker_headers = {"X-Worker-Token": settings.WORKER_API_TOKEN}
        db = SessionLocal()
        old_mode = settings.EXECUTION_MODE
        node_key = f"worker-{uuid4().hex}"
        admin = task = run = image = None
        try:
            settings.EXECUTION_MODE = "worker"
            for stale_device in db.query(crud.models.Device).filter(crud.models.Device.serial == "worker-device-test").all():
                db.query(crud.models.TaskRun).filter(crud.models.TaskRun.device_id == stale_device.id).update({"device_id": None}, synchronize_session=False)
                db.delete(stale_device)
            db.commit()
            admin = crud.create_user(
                db,
                username=f"worker-admin-{uuid4().hex}",
                password_hash=hash_password("secret-password"),
                role="admin",
            )
            task = crud.create_task(
                db,
                name="worker queued task",
                keyword="",
                target_app="拼多多",
                target_scenario="百亿补贴",
                mode="autoglm",
                created_by=admin.id,
                approved_by=admin.id,
            )
            crud.update_task_instruction(db, task.id, "打开拼多多App，找到百亿补贴，并截图保存到本地")
            token = create_access_token(admin)

            registered = client.post("/api/worker/register", headers=worker_headers, json={"node_key": node_key})
            self.assertEqual(registered.status_code, 200, registered.text)
            client.post(
                "/api/worker/devices",
                headers=worker_headers,
                json={"node_key": node_key, "devices": [{"serial": "worker-device-test", "status": "online"}]},
            )

            started = client.post(
                f"/api/admin/tasks/{task.id}/run",
                headers={"Authorization": f"Bearer {token}"},
                json={},
            )
            self.assertEqual(started.status_code, 200, started.text)
            run = crud.get_latest_task_run(db, task.id)
            self.assertEqual(run.status, "queued")
            self.assertEqual(run.execution_mode, "worker")

            claimed = client.post("/api/worker/task-runs/claim", headers=worker_headers, json={"node_key": node_key})
            self.assertEqual(claimed.status_code, 200, claimed.text)
            claim_body = claimed.json()
            self.assertEqual(claim_body["run"]["id"], str(run.id))
            self.assertIn("百亿补贴", claim_body["prompt"])
            db.refresh(run)
            db.refresh(task)
            self.assertEqual(run.status, "running")
            self.assertEqual(task.status, "running")

            log_response = client.post(
                f"/api/worker/task-runs/{run.id}/logs",
                headers=worker_headers,
                json={"node_key": node_key, "content": "worker log line\n"},
            )
            self.assertEqual(log_response.status_code, 200, log_response.text)

            uploaded = client.post(
                f"/api/worker/task-runs/{run.id}/images",
                headers=worker_headers,
                data={"node_key": node_key},
                files={"file": ("screen.png", b"not-a-real-image-but-enough-for-storage", "image/png")},
            )
            self.assertEqual(uploaded.status_code, 200, uploaded.text)
            image = crud.get_image(db, UUID(uploaded.json()["id"]))
            self.assertEqual(image.task_run_id, run.id)
            self.assertTrue(image.file_path.endswith("screen.png"))

            finished = client.post(
                f"/api/worker/task-runs/{run.id}/finish",
                headers=worker_headers,
                json={"node_key": node_key, "status": "completed", "exit_code": 0},
            )
            self.assertEqual(finished.status_code, 200, finished.text)
            db.refresh(run)
            db.refresh(task)
            self.assertEqual(run.status, "completed")
            self.assertEqual(task.status, "completed")
        finally:
            settings.EXECUTION_MODE = old_mode
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.delete(analysis)
                db.delete(image)
            if run:
                db.delete(run)
            if task:
                db.delete(task)
            if admin:
                db.delete(admin)
            for device in db.query(crud.models.Device).filter(crud.models.Device.serial == "worker-device-test").all():
                db.query(crud.models.TaskRun).filter(crud.models.TaskRun.device_id == device.id).update({"device_id": None}, synchronize_session=False)
                db.delete(device)
            db.query(crud.models.Worker).filter(crud.models.Worker.node_key == node_key).delete(synchronize_session=False)
            db.commit()
            db.close()

    def test_reconcile_stale_statuses_updates_active_task_from_terminal_run(self):
        from app import crud, models
        from app.database import SessionLocal
        from app.services.status_reconciler import reconcile_stale_statuses

        db = SessionLocal()
        task = run = None
        try:
            task = crud.create_task(
                db,
                name=f"stale-active-{uuid4().hex}",
                keyword="",
                target_app="淘宝",
                target_scenario="首页",
            )
            run = crud.create_task_run(db, task.id, status="failed")

            dry_run = reconcile_stale_statuses(db, apply=False, task_ids=[task.id])
            dry_task = next(row for row in dry_run["tasks"] if row["task_id"] == str(task.id))
            self.assertEqual(dry_task["new_status"], "failed")
            db.refresh(task)
            self.assertEqual(task.status, "pending")

            applied = reconcile_stale_statuses(db, apply=True, task_ids=[task.id])
            applied_task = next(row for row in applied["tasks"] if row["task_id"] == str(task.id))

            self.assertEqual(applied_task["task_id"], str(task.id))
            db.refresh(task)
            db.refresh(run)
            self.assertEqual(task.status, "failed")
            self.assertIsNotNone(task.completed_at)
            self.assertEqual(run.status, "failed")
        finally:
            if task:
                db.delete(task)
            db.commit()
            db.close()

    def test_reconcile_stale_statuses_fails_empty_active_task_without_run(self):
        from app import crud
        from app.database import SessionLocal
        from app.services.status_reconciler import reconcile_stale_statuses

        db = SessionLocal()
        task = None
        try:
            task = crud.create_task(
                db,
                name=f"empty-active-{uuid4().hex}",
                keyword="",
                target_app="淘宝",
                target_scenario="首页",
            )

            automatic = reconcile_stale_statuses(db, apply=False, task_ids=[task.id])
            self.assertFalse(any(row["task_id"] == str(task.id) for row in automatic["tasks"]))

            dry_run = reconcile_stale_statuses(db, apply=False, include_empty_tasks=True, task_ids=[task.id])
            dry_task = next(row for row in dry_run["tasks"] if row["task_id"] == str(task.id))
            self.assertEqual(dry_task["new_status"], "failed")
            self.assertIn("无运行记录", dry_task["reason"])

            reconcile_stale_statuses(db, apply=True, include_empty_tasks=True, task_ids=[task.id])

            db.refresh(task)
            self.assertEqual(task.status, "failed")
            self.assertIsNotNone(task.completed_at)
        finally:
            if task:
                db.delete(task)
            db.commit()
            db.close()

    def test_reconcile_stale_statuses_keeps_pending_comparison_task_without_run(self):
        from app import crud, models, schemas
        from app.database import SessionLocal
        from app.services.status_reconciler import reconcile_stale_statuses

        db = SessionLocal()
        request = group = a_task = jd_task = None
        try:
            request = crud.create_request(
                db,
                schemas.RequestCreate(target_app="淘宝", target_scenario="首页", keywords=[], description=""),
            )
            a_task = crud.create_task(db, name="A completed", keyword="", target_app="淘宝", target_scenario="首页", request_id=request.id)
            jd_task = crud.create_task(db, name="JD pending", keyword="", target_app="京东", target_scenario="首页", request_id=request.id)
            crud.update_task_status(db, a_task.id, "completed")
            group = crud.create_comparison_group(
                db,
                request_id=request.id,
                baseline_app="京东",
                jd_instruction="打开京东App，进入首页",
                status="running",
            )
            crud.create_comparison_group_app(db, group.id, "淘宝", a_task.id)
            crud.update_comparison_group_jd_task(db, group.id, jd_task.id, status="running")
            crud.update_task_status(db, jd_task.id, "pending")

            result = reconcile_stale_statuses(db, apply=True, include_empty_tasks=True, task_ids=[jd_task.id])

            self.assertFalse(any(row["task_id"] == str(jd_task.id) for row in result["tasks"]))
            db.refresh(jd_task)
            db.refresh(group)
            self.assertEqual(jd_task.status, "pending")
            self.assertEqual(group.status, "running")
        finally:
            if group:
                group.jd_task_id = None
                db.flush()
                db.query(models.ComparisonGroupApp).filter(models.ComparisonGroupApp.comparison_group_id == group.id).delete(synchronize_session=False)
                db.delete(group)
            for task in (jd_task, a_task):
                if task:
                    db.delete(task)
            if request:
                db.delete(request)
            db.commit()
            db.close()

    def test_reconcile_stale_statuses_closes_comparison_group_after_tasks_finish(self):
        from app import crud, models, schemas
        from app.database import SessionLocal
        from app.services.status_reconciler import reconcile_stale_statuses

        db = SessionLocal()
        request = group = a_task = jd_task = None
        try:
            request = crud.create_request(
                db,
                schemas.RequestCreate(target_app="淘宝", target_scenario="首页和百亿会场", keywords=[], description=""),
            )
            a_task = crud.create_task(db, name="A failed", keyword="", target_app="淘宝", target_scenario="首页", request_id=request.id)
            jd_task = crud.create_task(db, name="JD done", keyword="", target_app="京东", target_scenario="首页", request_id=request.id)
            crud.update_task_status(db, a_task.id, "failed")
            crud.update_task_status(db, jd_task.id, "completed")
            group = crud.create_comparison_group(
                db,
                request_id=request.id,
                baseline_app="京东",
                jd_instruction="打开京东App，进入首页",
                status="running",
            )
            crud.create_comparison_group_app(db, group.id, "淘宝", a_task.id)
            crud.update_comparison_group_jd_task(db, group.id, jd_task.id, status="running")

            applied = reconcile_stale_statuses(db, apply=True, comparison_group_ids=[group.id])
            applied_group = next(
                row for row in applied["comparison_groups"] if row["comparison_group_id"] == str(group.id)
            )

            self.assertEqual(applied_group["new_status"], "failed")
            db.refresh(group)
            self.assertEqual(group.status, "failed")
        finally:
            if group:
                group.jd_task_id = None
                db.flush()
                db.query(models.ComparisonGroupApp).filter(models.ComparisonGroupApp.comparison_group_id == group.id).delete(synchronize_session=False)
                db.delete(group)
            for task in (jd_task, a_task):
                if task:
                    db.delete(task)
            if request:
                db.delete(request)
            db.commit()
            db.close()

    def test_starting_comparison_task_reopens_failed_group(self):
        from app import crud, models, schemas
        from app.database import SessionLocal
        from app.routers import admin as admin_router
        from app.services.auth import hash_password

        class FakeTaskExecutor:
            def run(self, *args, **kwargs):
                return None

        db = SessionLocal()
        user = request = group = a_task = jd_task = None
        previous_task_executor = admin_router.task_executor
        previous_execution_mode = admin_router.execution_mode
        previous_select_device = admin_router._select_run_device
        admin_router.task_executor = lambda: FakeTaskExecutor()
        admin_router.execution_mode = lambda: "local"
        admin_router._select_run_device = lambda db, device_id, task, active_mode: None
        try:
            user = crud.create_user(
                db,
                username=f"group-retry-{uuid4().hex[:8]}",
                password_hash=hash_password("pass"),
                role="operator",
            )
            request = crud.create_request(
                db,
                schemas.RequestCreate(target_app="淘宝", target_scenario="活动会场", keywords=[], description=""),
                user_id=str(user.id),
            )
            a_task = crud.create_task(db, name="A", keyword="", target_app="淘宝", target_scenario="活动会场", request_id=request.id, created_by=user.id)
            jd_task = crud.create_task(db, name="JD", keyword="", target_app="京东", target_scenario="活动会场", request_id=request.id, mode="autoglm", created_by=user.id)
            crud.update_task_instruction(db, jd_task.id, "打开京东App，进入活动会场，到达目标页面后停留并结束任务")
            group = crud.create_comparison_group(
                db,
                request_id=request.id,
                baseline_app="京东",
                jd_instruction="打开京东App，进入活动会场",
                status="failed",
            )
            crud.create_comparison_group_app(db, group.id, "淘宝", a_task.id)
            crud.update_comparison_group_jd_task(db, group.id, jd_task.id, status="failed")
            crud.update_task_status(db, jd_task.id, "failed")

            admin_router._start_task(db, jd_task.id, user)

            db.refresh(group)
            self.assertEqual(group.status, "running")
        finally:
            admin_router.task_executor = previous_task_executor
            admin_router.execution_mode = previous_execution_mode
            admin_router._select_run_device = previous_select_device
            db.rollback()
            if group:
                group.jd_task_id = None
                db.flush()
                db.query(models.ComparisonGroupApp).filter(models.ComparisonGroupApp.comparison_group_id == group.id).delete(synchronize_session=False)
                db.delete(group)
            for task in (jd_task, a_task):
                if task:
                    db.query(models.TaskRun).filter(models.TaskRun.task_id == task.id).delete(synchronize_session=False)
                    db.delete(task)
            if request:
                db.delete(request)
            if user:
                db.delete(user)
            db.commit()
            db.close()

    def test_reconcile_stale_statuses_releases_orphan_busy_device(self):
        from app import crud
        from app.database import SessionLocal
        from app.services.status_reconciler import reconcile_stale_statuses

        db = SessionLocal()
        device = None
        try:
            missing_run_id = uuid4()
            device = crud.upsert_device(db, serial=f"orphan-device-{uuid4().hex[:8]}", status="busy")
            device.current_task_run_id = missing_run_id
            db.commit()

            result = reconcile_stale_statuses(db, apply=True)

            db.refresh(device)
            self.assertEqual(device.status, "online")
            self.assertIsNone(device.current_task_run_id)
            self.assertEqual(result["devices"][0]["reason"], "current task run is missing")
        finally:
            if device:
                db.delete(device)
            db.commit()
            db.close()

    def test_reconcile_stale_statuses_releases_terminal_run_busy_device(self):
        from app import crud
        from app.database import SessionLocal
        from app.services.status_reconciler import reconcile_stale_statuses

        db = SessionLocal()
        task = run = device = None
        try:
            task = crud.create_task(db, name="terminal-device-task", keyword="", target_app="淘宝", target_scenario="首页")
            run = crud.create_task_run(db, task.id, status="completed")
            device = crud.upsert_device(db, serial=f"terminal-device-{uuid4().hex[:8]}", status="busy")
            device.current_task_run_id = run.id
            db.commit()

            result = reconcile_stale_statuses(db, apply=True)

            db.refresh(device)
            self.assertEqual(device.status, "online")
            self.assertIsNone(device.current_task_run_id)
            self.assertEqual(result["devices"][0]["reason"], "current task run is terminal")
        finally:
            if device:
                db.delete(device)
            if task:
                db.delete(task)
            db.commit()
            db.close()

    def test_reconcile_stale_statuses_closes_finished_local_run_with_lost_watcher(self):
        from app import crud, models, schemas
        from app.database import SessionLocal
        from app.services.status_reconciler import LOCAL_RUN_IDLE_SECONDS, reconcile_stale_statuses

        db = SessionLocal()
        task = run = image = None
        log_path = Path("logs") / "tests" / f"lost-watcher-{uuid4().hex}.log"
        try:
            task = crud.create_task(
                db,
                name=f"lost-watcher-{uuid4().hex}",
                keyword="",
                target_app="京东",
                target_scenario="首页",
                target_goals_json=[],
            )
            run = crud.create_task_run(
                db,
                task.id,
                status="running",
                execution_mode="local",
                log_path=str(log_path),
            )
            image = crud.create_image(
                db,
                schemas.ImageCreate(
                    file_path="data/lost-watcher.png",
                    task_id=task.id,
                    task_run_id=run.id,
                    source_app="京东",
                ),
            )
            old_time = datetime.now() - timedelta(seconds=LOCAL_RUN_IDLE_SECONDS + 5)
            image.created_at = old_time
            image.captured_at = old_time
            full_log_path = Path(PROJECT_ROOT) / log_path
            full_log_path.parent.mkdir(parents=True, exist_ok=True)
            full_log_path.write_text("Parsing action: finish(message=\"done\")\n✅ 任务完成: done\n", encoding="utf-8")
            db.commit()

            result = reconcile_stale_statuses(db, apply=True, task_ids=[task.id])

            self.assertEqual(result["local_runs"][0]["new_run_status"], "completed")
            db.refresh(task)
            db.refresh(run)
            self.assertEqual(task.status, "completed")
            self.assertEqual(run.status, "completed")
            self.assertIsNotNone(run.completed_at)
        finally:
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.delete(analysis)
                db.delete(image)
            if run:
                db.delete(run)
            if task:
                db.delete(task)
            db.commit()
            db.close()
            full_log_path = Path(PROJECT_ROOT) / log_path
            if full_log_path.exists():
                full_log_path.unlink()

    def test_reconcile_stale_statuses_starts_next_comparison_task_after_lost_watcher(self):
        from app import crud, models, schemas
        from app.database import SessionLocal
        from app.services import collector_bridge
        from app.services.status_reconciler import LOCAL_RUN_IDLE_SECONDS, reconcile_stale_statuses

        class FakeTaskExecutor:
            calls = []

            def run(self, task, *args, **kwargs):
                self.calls.append(task.id)
                return None

        db = SessionLocal()
        request = group = a_task = jd_task = run = image = device = None
        log_path = Path("logs") / "tests" / f"lost-watcher-bridge-{uuid4().hex}.log"
        previous_task_executor = collector_bridge.task_executor
        previous_execution_mode = collector_bridge.execution_mode
        previous_refresh_devices = collector_bridge.refresh_devices
        collector_bridge.task_executor = lambda: FakeTaskExecutor()
        collector_bridge.execution_mode = lambda: "local"
        collector_bridge.refresh_devices = lambda db: (crud.list_devices(db), True)
        try:
            request = crud.create_request(
                db,
                schemas.RequestCreate(target_app="淘宝", target_scenario="首页", keywords=[], description=""),
            )
            a_task = crud.create_task(
                db,
                name="A lost watcher",
                keyword="",
                target_app="淘宝",
                target_scenario="首页",
                request_id=request.id,
                mode="autoglm",
            )
            jd_task = crud.create_task(
                db,
                name="JD pending",
                keyword="",
                target_app="京东",
                target_scenario="首页",
                request_id=request.id,
                mode="autoglm",
            )
            crud.update_task_instruction(db, jd_task.id, "打开京东App，进入首页，到达目标页面后停留并结束任务")
            run = crud.create_task_run(
                db,
                a_task.id,
                status="running",
                execution_mode="local",
                log_path=str(log_path),
            )
            image = crud.create_image(
                db,
                schemas.ImageCreate(
                    file_path="data/lost-watcher-bridge.png",
                    task_id=a_task.id,
                    task_run_id=run.id,
                    source_app="淘宝",
                ),
            )
            old_time = datetime.now() - timedelta(seconds=LOCAL_RUN_IDLE_SECONDS + 5)
            image.created_at = old_time
            image.captured_at = old_time
            full_log_path = Path(PROJECT_ROOT) / log_path
            full_log_path.parent.mkdir(parents=True, exist_ok=True)
            full_log_path.write_text("Parsing action: finish(message=\"done\")\n✅ 任务完成: done\n", encoding="utf-8")
            group = crud.create_comparison_group(
                db,
                request_id=request.id,
                baseline_app="京东",
                jd_instruction="打开京东App，进入首页，到达目标页面后停留并结束任务",
                status="running",
            )
            crud.create_comparison_group_app(db, group.id, "淘宝", a_task.id)
            crud.update_comparison_group_jd_task(db, group.id, jd_task.id, status="running")
            crud.update_task_status(db, jd_task.id, "pending")
            device = crud.upsert_device(db, serial=f"lost-watcher-bridge-{uuid4().hex[:8]}", status="online")
            db.commit()

            reconcile_stale_statuses(db, apply=True, task_ids=[a_task.id])

            db.refresh(a_task)
            db.refresh(jd_task)
            self.assertEqual(a_task.status, "completed")
            self.assertEqual(jd_task.status, "running")
            self.assertEqual(FakeTaskExecutor.calls, [jd_task.id])
        finally:
            collector_bridge.task_executor = previous_task_executor
            collector_bridge.execution_mode = previous_execution_mode
            collector_bridge.refresh_devices = previous_refresh_devices
            db.rollback()
            if group:
                group.jd_task_id = None
                db.flush()
                db.query(models.ComparisonGroupApp).filter(models.ComparisonGroupApp.comparison_group_id == group.id).delete(synchronize_session=False)
                db.delete(group)
            for task in (jd_task, a_task):
                if task:
                    db.query(models.TaskRun).filter(models.TaskRun.task_id == task.id).delete(synchronize_session=False)
                    db.delete(task)
            if image:
                analysis = crud.get_analysis_by_image(db, image.id)
                if analysis:
                    db.delete(analysis)
                db.delete(image)
            if request:
                db.delete(request)
            if device:
                db.delete(device)
            db.commit()
            db.close()
            full_log_path = Path(PROJECT_ROOT) / log_path
            if full_log_path.exists():
                full_log_path.unlink()

    def test_jd_comparison_model_and_schema_fields_exist(self):
        from app import models
        from app.schemas import RequestCreate, RequestInterpretOut, RequestOut

        self.assertTrue(hasattr(models, "ComparisonGroup"))
        self.assertTrue(hasattr(models, "ComparisonGroupApp"))
        self.assertTrue(hasattr(models, "ComparisonSlot"))
        self.assertTrue(hasattr(models, "ComparisonSlotMatch"))
        self.assertTrue(hasattr(models, "ComparisonPairAnalysis"))
        self.assertTrue(hasattr(models.Request, "compare_jd_enabled"))
        self.assertTrue(hasattr(models.Request, "comparison_config_json"))
        self.assertIn("compare_jd_enabled", RequestCreate.model_fields)
        self.assertIn("comparison", RequestCreate.model_fields)
        self.assertIn("a_apps", RequestInterpretOut.model_fields)
        self.assertIn("comparison_slots", RequestInterpretOut.model_fields)
        self.assertIn("jd_instruction", RequestInterpretOut.model_fields)
        self.assertIn("compare_jd_enabled", RequestOut.model_fields)
        self.assertIn("comparison_config_json", RequestOut.model_fields)

    def test_request_api_rejects_jd_in_a_side_apps(self):
        from fastapi.testclient import TestClient
        from app import crud
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password

        db = SessionLocal()
        user = None
        try:
            user = crud.create_user(
                db,
                username=f"jd-compare-{uuid4().hex[:8]}",
                password_hash=hash_password("pass"),
                role="viewer",
            )
            response = TestClient(app).post(
                "/api/requests",
                headers={"Authorization": f"Bearer {create_access_token(user)}"},
                json={
                    "target_app": "京东",
                    "target_scenario": "百亿补贴会场",
                    "compare_jd_enabled": True,
                    "comparison": {
                        "a_apps": ["京东"],
                        "jd_instruction": "打开京东App，进入百亿补贴会场并截图保存到本地",
                        "slots": [{"name": "会场首屏", "description": "活动会场首屏", "required": True}],
                    },
                },
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn("京东", response.text)
        finally:
            if user:
                db.delete(user)
            db.commit()
            db.close()

    def test_request_api_stores_normalized_jd_comparison_config(self):
        from fastapi.testclient import TestClient
        from app import crud
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password

        db = SessionLocal()
        user = request = None
        try:
            user = crud.create_user(
                db,
                username=f"jd-config-{uuid4().hex[:8]}",
                password_hash=hash_password("pass"),
                role="viewer",
            )
            response = TestClient(app).post(
                "/api/requests",
                headers={"Authorization": f"Bearer {create_access_token(user)}"},
                json={
                    "target_app": "淘宝、拼多多",
                    "target_scenario": "百亿补贴会场",
                    "keywords": ["百亿补贴"],
                    "description": "进入百亿补贴会场截图。",
                    "compare_jd_enabled": True,
                    "comparison": {
                        "a_apps": ["淘宝", "拼多多", "淘宝"],
                        "jd_instruction": "打开京东App，进入等价的百亿补贴会场，并截图保存到本地",
                        "slots": [{"name": "会场首屏", "description": "活动会场首屏", "required": True}],
                    },
                },
            )

            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertTrue(body["compare_jd_enabled"])
            self.assertEqual(body["comparison_config_json"]["a_apps"], ["淘宝", "拼多多"])
            self.assertEqual(body["comparison_config_json"]["slots"][0]["slot_key"], "hui_chang_shou_ping")
            request = crud.get_request(db, UUID(body["id"]))
        finally:
            if request:
                db.delete(request)
            if user:
                db.delete(user)
            db.commit()
            db.close()

    def test_approve_jd_comparison_request_creates_group_tasks_and_slots(self):
        from fastapi.testclient import TestClient
        from app import crud, models
        from app.database import SessionLocal
        from app.main import app
        from app.routers import admin as admin_router
        from app.services.auth import create_access_token, hash_password

        class FakeTaskExecutor:
            calls = []

            def run(self, task, *args, **kwargs):
                self.calls.append(task.id)
                return None

        async def fake_plan_task(target_app, target_scenario, keywords, description):
            return f"打开{target_app}App，进入{target_scenario}，并截图保存到本地"

        db = SessionLocal()
        operator = request = group = None
        previous_executor = admin_router.task_executor
        previous_plan_task = admin_router.plan_task
        previous_select_device = admin_router._select_run_device
        admin_router.task_executor = lambda: FakeTaskExecutor()
        admin_router.plan_task = fake_plan_task
        admin_router._select_run_device = lambda db, device_id, task, active_mode: None
        try:
            operator = crud.create_user(
                db,
                username=f"jd-approve-{uuid4().hex[:8]}",
                password_hash=hash_password("pass"),
                role="operator",
            )
            client = TestClient(app)
            headers = {"Authorization": f"Bearer {create_access_token(operator)}"}
            created = client.post(
                "/api/requests",
                headers=headers,
                json={
                    "target_app": "淘宝、拼多多",
                    "target_scenario": "百亿补贴会场",
                    "keywords": ["百亿补贴"],
                    "description": "分别进入百亿补贴会场截图。",
                    "compare_jd_enabled": True,
                    "comparison": {
                        "a_apps": ["淘宝", "拼多多"],
                        "jd_instruction": "打开京东App，进入等价的百亿补贴会场，并截图保存到本地",
                        "slots": [
                            {"slot_key": "promo_landing", "name": "会场首屏", "description": "活动会场首屏", "required": True},
                            {"slot_key": "product_detail", "name": "商品详情首屏", "description": "商品详情首屏", "required": False},
                        ],
                    },
                },
            )
            self.assertEqual(created.status_code, 200, created.text)
            request = crud.get_request(db, UUID(created.json()["id"]))

            approved = client.put(
                f"/api/admin/requests/{request.id}/approve",
                headers=headers,
                json={"admin_id": operator.username, "mode": "autoglm"},
            )

            self.assertEqual(approved.status_code, 200, approved.text)
            group = db.query(models.ComparisonGroup).filter(models.ComparisonGroup.request_id == request.id).first()
            self.assertIsNotNone(group)
            self.assertEqual(group.baseline_app, "京东")
            self.assertIsNotNone(group.jd_task_id)
            group_apps = db.query(models.ComparisonGroupApp).filter(models.ComparisonGroupApp.comparison_group_id == group.id).all()
            self.assertEqual(sorted(row.app_name for row in group_apps), ["拼多多", "淘宝"])
            self.assertEqual(len({row.task_id for row in group_apps}), 2)
            slots = db.query(models.ComparisonSlot).filter(models.ComparisonSlot.comparison_group_id == group.id).all()
            self.assertEqual([slot.slot_key for slot in sorted(slots, key=lambda item: item.sort_order)], ["promo_landing", "product_detail"])
            tasks = db.query(models.Task).filter(models.Task.request_id == request.id).all()
            self.assertEqual(sorted(task.target_app for task in tasks), ["京东", "拼多多", "淘宝"])
            self.assertEqual(len(FakeTaskExecutor.calls), 1)
        finally:
            admin_router.task_executor = previous_executor
            admin_router.plan_task = previous_plan_task
            admin_router._select_run_device = previous_select_device
            db.rollback()
            if not group and request and hasattr(models, "ComparisonGroup"):
                group = db.query(models.ComparisonGroup).filter(models.ComparisonGroup.request_id == request.id).first()
            if group and hasattr(models, "ComparisonPairAnalysis"):
                group.jd_task_id = None
                db.flush()
                db.query(models.ComparisonPairAnalysis).filter(models.ComparisonPairAnalysis.comparison_group_app_id.in_(
                    db.query(models.ComparisonGroupApp.id).filter(models.ComparisonGroupApp.comparison_group_id == group.id)
                )).delete(synchronize_session=False)
                db.query(models.ComparisonSlotMatch).filter(models.ComparisonSlotMatch.comparison_group_id == group.id).delete(synchronize_session=False)
                db.query(models.ComparisonSlot).filter(models.ComparisonSlot.comparison_group_id == group.id).delete(synchronize_session=False)
                db.query(models.ComparisonGroupApp).filter(models.ComparisonGroupApp.comparison_group_id == group.id).delete(synchronize_session=False)
                db.delete(group)
            if request:
                db.query(models.TaskRun).filter(models.TaskRun.task_id.in_(
                    db.query(models.Task.id).filter(models.Task.request_id == request.id)
                )).delete(synchronize_session=False)
                db.query(models.Task).filter(models.Task.request_id == request.id).delete(synchronize_session=False)
                db.delete(request)
            if operator:
                db.delete(operator)
            db.commit()
            db.close()

    def test_completed_a_side_comparison_task_starts_pending_jd_task_in_local_mode(self):
        from app import crud, models, schemas
        from app.database import SessionLocal
        from app.services import collector_bridge
        from app.services.auth import hash_password

        class FakeTaskExecutor:
            calls = []

            def run(self, task, *args, **kwargs):
                device = kwargs.get("device")
                self.calls.append((task.id, device.id if device else None))
                return None

        db = SessionLocal()
        user = request = group = a_task = jd_task = device = None
        previous_task_executor = collector_bridge.task_executor
        previous_execution_mode = collector_bridge.execution_mode
        previous_refresh_devices = collector_bridge.refresh_devices
        collector_bridge.task_executor = lambda: FakeTaskExecutor()
        collector_bridge.execution_mode = lambda: "local"
        collector_bridge.refresh_devices = lambda db: (crud.list_devices(db), True)
        try:
            user = crud.create_user(
                db,
                username=f"jd-bridge-{uuid4().hex[:8]}",
                password_hash=hash_password("pass"),
                role="operator",
            )
            request = crud.create_request(
                db,
                schemas.RequestCreate(target_app="淘宝", target_scenario="首页", keywords=[], description=""),
                user_id=str(user.id),
            )
            a_task = crud.create_task(
                db,
                name="Taobao side",
                keyword="",
                target_app="淘宝",
                target_scenario="首页",
                request_id=request.id,
                mode="autoglm",
                created_by=user.id,
            )
            jd_task = crud.create_task(
                db,
                name="JD side",
                keyword="",
                target_app="京东",
                target_scenario="首页",
                request_id=request.id,
                mode="autoglm",
                created_by=user.id,
            )
            crud.update_task_instruction(db, jd_task.id, "打开京东App，进入首页，到达目标页面后停留并结束任务")
            device = crud.upsert_device(db, serial=f"jd-bridge-{uuid4().hex[:8]}", status="online")
            group = crud.create_comparison_group(
                db,
                request_id=request.id,
                baseline_app="京东",
                jd_instruction="打开京东App，进入首页，到达目标页面后停留并结束任务",
                status="running",
            )
            crud.create_comparison_group_app(db, group.id, "淘宝", a_task.id)
            crud.update_comparison_group_jd_task(db, group.id, jd_task.id, status="running")
            crud.update_task_status(db, jd_task.id, "pending")

            collector_bridge._maybe_start_jd_comparison_task(db, a_task.id, final_status="completed")

            db.refresh(jd_task)
            self.assertEqual(jd_task.status, "running")
            self.assertEqual(len(FakeTaskExecutor.calls), 1)
            self.assertEqual(FakeTaskExecutor.calls[0][0], jd_task.id)
            self.assertIsNotNone(FakeTaskExecutor.calls[0][1])
        finally:
            collector_bridge.task_executor = previous_task_executor
            collector_bridge.execution_mode = previous_execution_mode
            collector_bridge.refresh_devices = previous_refresh_devices
            db.rollback()
            if group:
                group.jd_task_id = None
                db.flush()
                db.query(models.ComparisonGroupApp).filter(models.ComparisonGroupApp.comparison_group_id == group.id).delete(synchronize_session=False)
                db.delete(group)
            for task in (jd_task, a_task):
                if task:
                    db.query(models.TaskRun).filter(models.TaskRun.task_id == task.id).delete(synchronize_session=False)
                    db.delete(task)
            if request:
                db.delete(request)
            if user:
                db.delete(user)
            if device:
                db.delete(device)
            db.commit()
            db.close()

    def test_completed_a_side_comparison_task_starts_next_a_side_before_jd(self):
        from app import crud, models, schemas
        from app.database import SessionLocal
        from app.services import collector_bridge
        from app.services.auth import hash_password

        class FakeTaskExecutor:
            calls = []

            def run(self, task, *args, **kwargs):
                self.calls.append(task.target_app)
                return None

        db = SessionLocal()
        user = request = group = taobao_task = pdd_task = jd_task = device = None
        previous_task_executor = collector_bridge.task_executor
        previous_execution_mode = collector_bridge.execution_mode
        previous_refresh_devices = collector_bridge.refresh_devices
        collector_bridge.task_executor = lambda: FakeTaskExecutor()
        collector_bridge.execution_mode = lambda: "local"
        collector_bridge.refresh_devices = lambda db: (crud.list_devices(db), True)
        try:
            user = crud.create_user(
                db,
                username=f"jd-bridge-order-{uuid4().hex[:8]}",
                password_hash=hash_password("pass"),
                role="operator",
            )
            request = crud.create_request(
                db,
                schemas.RequestCreate(target_app="淘宝、拼多多", target_scenario="首页", keywords=[], description=""),
                user_id=str(user.id),
            )
            taobao_task = crud.create_task(db, name="Taobao", keyword="", target_app="淘宝", target_scenario="首页", request_id=request.id, mode="autoglm", created_by=user.id)
            pdd_task = crud.create_task(db, name="PDD", keyword="", target_app="拼多多", target_scenario="首页", request_id=request.id, mode="autoglm", created_by=user.id)
            jd_task = crud.create_task(db, name="JD", keyword="", target_app="京东", target_scenario="首页", request_id=request.id, mode="autoglm", created_by=user.id)
            for task in (pdd_task, jd_task):
                crud.update_task_instruction(db, task.id, f"打开{task.target_app}App，进入首页，到达目标页面后停留并结束任务")
            device = crud.upsert_device(db, serial=f"jd-bridge-order-{uuid4().hex[:8]}", status="online")
            group = crud.create_comparison_group(
                db,
                request_id=request.id,
                baseline_app="京东",
                jd_instruction="打开京东App，进入首页，到达目标页面后停留并结束任务",
                status="running",
            )
            crud.create_comparison_group_app(db, group.id, "淘宝", taobao_task.id)
            crud.create_comparison_group_app(db, group.id, "拼多多", pdd_task.id)
            crud.update_comparison_group_jd_task(db, group.id, jd_task.id, status="running")

            collector_bridge._maybe_start_jd_comparison_task(db, taobao_task.id, final_status="completed")

            db.refresh(pdd_task)
            db.refresh(jd_task)
            self.assertEqual(pdd_task.status, "running")
            self.assertEqual(jd_task.status, "pending")
            self.assertEqual(FakeTaskExecutor.calls, ["拼多多"])
        finally:
            collector_bridge.task_executor = previous_task_executor
            collector_bridge.execution_mode = previous_execution_mode
            collector_bridge.refresh_devices = previous_refresh_devices
            db.rollback()
            if group:
                group.jd_task_id = None
                db.flush()
                db.query(models.ComparisonGroupApp).filter(models.ComparisonGroupApp.comparison_group_id == group.id).delete(synchronize_session=False)
                db.delete(group)
            for task in (jd_task, pdd_task, taobao_task):
                if task:
                    db.query(models.TaskRun).filter(models.TaskRun.task_id == task.id).delete(synchronize_session=False)
                    db.delete(task)
            if request:
                db.delete(request)
            if user:
                db.delete(user)
            if device:
                db.delete(device)
            db.commit()
            db.close()

    def test_comparison_result_api_returns_paired_missing_and_unmatched_slots(self):
        from fastapi.testclient import TestClient
        from app import crud, models, schemas
        from app.database import SessionLocal
        from app.main import app
        from app.services.auth import create_access_token, hash_password

        db = SessionLocal()
        user = request = group = a_task = jd_task = a_image = jd_image = extra_image = None
        try:
            user = crud.create_user(
                db,
                username=f"jd-result-{uuid4().hex[:8]}",
                password_hash=hash_password("pass"),
                role="viewer",
            )
            request = crud.create_request(
                db,
                schemas.RequestCreate(target_app="淘宝", target_scenario="百亿补贴会场", keywords=[], description=""),
                user_id=str(user.id),
                analysis_skill_snapshots=[{"skill_id": "design", "name": "设计维度", "instruction_md": "# 设计维度", "is_official": True}],
            )
            a_task = crud.create_task(db, name="A", keyword="", target_app="淘宝", target_scenario="百亿补贴会场", request_id=request.id, created_by=user.id)
            jd_task = crud.create_task(db, name="JD", keyword="", target_app="京东", target_scenario="百亿补贴会场", request_id=request.id, created_by=user.id)
            group = crud.create_comparison_group(db, request_id=request.id, baseline_app="京东", jd_instruction="打开京东App，进入百亿补贴会场，并截图保存到本地")
            crud.update_comparison_group_jd_task(db, group.id, jd_task.id)
            group_app = crud.create_comparison_group_app(db, group.id, "淘宝", a_task.id)
            paired_slot = crud.create_comparison_slot(db, group.id, "promo_landing", "会场首屏", "活动会场首屏", True, 0)
            missing_slot = crud.create_comparison_slot(db, group.id, "product_detail", "商品详情首屏", "商品详情首屏", False, 1)
            a_image = crud.create_image(db, schemas.ImageCreate(file_path="a.png", task_id=a_task.id, source_app="淘宝"))
            jd_image = crud.create_image(db, schemas.ImageCreate(file_path="jd.png", task_id=jd_task.id, source_app="京东"))
            extra_image = crud.create_image(db, schemas.ImageCreate(file_path="extra.png", task_id=a_task.id, source_app="淘宝"))
            crud.create_analysis(db, a_image.id, "A设计", "A运营", status="success")
            crud.create_analysis(db, jd_image.id, "JD设计", "JD运营", status="success")
            crud.create_analysis(db, extra_image.id, "额外设计", "额外运营", status="success")
            crud.create_comparison_slot_match(db, group.id, paired_slot.id, "淘宝", a_task.id, a_image.id, 0.91, "matched", "A命中首屏")
            crud.create_comparison_slot_match(db, group.id, paired_slot.id, "京东", jd_task.id, jd_image.id, 0.9, "matched", "JD命中首屏")
            crud.create_comparison_slot_match(db, group.id, missing_slot.id, "淘宝", a_task.id, extra_image.id, 0.88, "matched", "A命中详情")
            crud.create_comparison_pair_analysis(
                db,
                group_app.id,
                paired_slot.id,
                a_image.id,
                jd_image.id,
                {"results": [{"skill_name": "设计维度", "analysis": "A和JD首屏差异"}], "errors": []},
                status="success",
            )

            response = TestClient(app).get(
                f"/api/comparison-groups/by-task/{a_task.id}",
                headers={"Authorization": f"Bearer {create_access_token(user)}"},
            )

            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body["baseline_app"], "京东")
            slots = body["apps"][0]["slots"]
            by_key = {slot["slot_key"]: slot for slot in slots}
            self.assertEqual(by_key["promo_landing"]["status"], "paired")
            self.assertEqual(by_key["promo_landing"]["pair_analysis"]["status"], "success")
            self.assertEqual(by_key["product_detail"]["status"], "missing_jd")
            self.assertIsNone(by_key["product_detail"]["pair_analysis"])
        finally:
            if group and hasattr(models, "ComparisonPairAnalysis"):
                group.jd_task_id = None
                db.flush()
                db.query(models.ComparisonPairAnalysis).filter(models.ComparisonPairAnalysis.comparison_group_app_id.in_(
                    db.query(models.ComparisonGroupApp.id).filter(models.ComparisonGroupApp.comparison_group_id == group.id)
                )).delete(synchronize_session=False)
                db.query(models.ComparisonSlotMatch).filter(models.ComparisonSlotMatch.comparison_group_id == group.id).delete(synchronize_session=False)
                db.query(models.ComparisonSlot).filter(models.ComparisonSlot.comparison_group_id == group.id).delete(synchronize_session=False)
                db.query(models.ComparisonGroupApp).filter(models.ComparisonGroupApp.comparison_group_id == group.id).delete(synchronize_session=False)
                db.delete(group)
            for image in (extra_image, jd_image, a_image):
                if image:
                    analysis = crud.get_analysis_by_image(db, image.id)
                    if analysis:
                        db.delete(analysis)
                    db.delete(image)
            for task in (jd_task, a_task):
                if task:
                    db.delete(task)
            if request:
                db.delete(request)
            if user:
                db.delete(user)
            db.commit()
            db.close()

    def test_process_image_for_comparison_uses_page_evidence_before_model_match(self):
        from app import crud, models, schemas
        from app.database import SessionLocal
        from app.services import jd_comparison

        class FailingAnalyzer:
            async def match_comparison_slot(self, *args, **kwargs):
                raise AssertionError("model slot matcher should not be called when page evidence is available")

        db = SessionLocal()
        request = group = task = image = None
        previous_analyzer = jd_comparison.analyzer if hasattr(jd_comparison, "analyzer") else None
        try:
            request = crud.create_request(
                db,
                schemas.RequestCreate(target_app="淘宝", target_scenario="任意活动会场"),
                analysis_skill_snapshots=[],
            )
            task = crud.create_task(db, name="A", keyword="", target_app="淘宝", target_scenario="任意活动会场", request_id=request.id)
            group = crud.create_comparison_group(db, request_id=request.id, baseline_app="京东", jd_instruction="打开京东等价页面并截图")
            crud.create_comparison_group_app(db, group.id, "淘宝", task.id)
            slot = crud.create_comparison_slot(db, group.id, "promo_landing", "活动会场", "平台活动会场首屏", True, 0)
            image = crud.create_image(db, schemas.ImageCreate(file_path="evidence-match.png", task_id=task.id, source_app="淘宝"))
            crud.create_analysis(
                db,
                image.id,
                "活动页设计",
                "活动页运营",
                status="success",
                custom_analysis_json={
                    "page_evidence": {
                        "matched_target_key": "promo_landing",
                        "matched_target_name": "活动会场",
                        "matched_goal_labels": ["活动会场"],
                        "confidence": 0.87,
                        "page_state": "target_page",
                        "target_role": "promo_channel",
                        "is_terminal_target": True,
                        "needs_more_wait": False,
                        "reason": "页面符合活动会场业务角色",
                        "negative_evidence": [],
                    }
                },
            )

            jd_comparison.analyzer = FailingAnalyzer()
            asyncio.run(jd_comparison.process_image_for_comparison(image.id))

            match = db.query(models.ComparisonSlotMatch).filter(models.ComparisonSlotMatch.image_id == image.id).first()
            self.assertIsNotNone(match)
            self.assertEqual(match.slot_id, slot.id)
            self.assertEqual(match.status, "matched")
            self.assertGreaterEqual(match.confidence, 0.87)
        finally:
            if previous_analyzer is not None:
                jd_comparison.analyzer = previous_analyzer
            if group and hasattr(models, "ComparisonPairAnalysis"):
                group.jd_task_id = None
                db.flush()
                db.query(models.ComparisonPairAnalysis).filter(models.ComparisonPairAnalysis.comparison_group_app_id.in_(
                    db.query(models.ComparisonGroupApp.id).filter(models.ComparisonGroupApp.comparison_group_id == group.id)
                )).delete(synchronize_session=False)
                db.query(models.ComparisonSlotMatch).filter(models.ComparisonSlotMatch.comparison_group_id == group.id).delete(synchronize_session=False)
                db.query(models.ComparisonSlot).filter(models.ComparisonSlot.comparison_group_id == group.id).delete(synchronize_session=False)
                db.query(models.ComparisonGroupApp).filter(models.ComparisonGroupApp.comparison_group_id == group.id).delete(synchronize_session=False)
                db.delete(group)
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

    def test_process_image_for_comparison_ignores_non_terminal_page_evidence(self):
        from app import crud, models, schemas
        from app.database import SessionLocal
        from app.services import jd_comparison

        class LowConfidenceAnalyzer:
            async def match_comparison_slot(self, *args, **kwargs):
                return {
                    "slot_key": "",
                    "confidence": 0.0,
                    "reason": "非终态页面不参与槽位匹配",
                }

        db = SessionLocal()
        request = group = task = image = None
        previous_analyzer = jd_comparison.analyzer if hasattr(jd_comparison, "analyzer") else None
        try:
            request = crud.create_request(
                db,
                schemas.RequestCreate(target_app="淘宝", target_scenario="任意活动会场"),
                analysis_skill_snapshots=[],
            )
            task = crud.create_task(db, name="A", keyword="", target_app="淘宝", target_scenario="任意活动会场", request_id=request.id)
            group = crud.create_comparison_group(db, request_id=request.id, baseline_app="京东", jd_instruction="打开京东等价页面并截图")
            crud.create_comparison_group_app(db, group.id, "淘宝", task.id)
            slot = crud.create_comparison_slot(db, group.id, "promo_landing", "活动会场", "平台活动会场首屏", True, 0)
            image = crud.create_image(db, schemas.ImageCreate(file_path="non-terminal-evidence.png", task_id=task.id, source_app="淘宝"))
            crud.create_analysis(
                db,
                image.id,
                "页面出现活动会场入口",
                "活动利益点入口",
                status="success",
                custom_analysis_json={
                    "page_evidence": {
                        "matched_target_key": "promo_landing",
                        "matched_target_name": "活动会场",
                        "matched_goal_labels": ["活动会场"],
                        "confidence": 0.91,
                        "page_state": "intermediate",
                        "target_role": "promo_entry",
                        "is_terminal_target": False,
                        "needs_more_wait": False,
                        "reason": "只是活动入口，不是目标会场终态",
                        "negative_evidence": [],
                    }
                },
            )

            jd_comparison.analyzer = LowConfidenceAnalyzer()
            asyncio.run(jd_comparison.process_image_for_comparison(image.id))

            match = db.query(models.ComparisonSlotMatch).filter(models.ComparisonSlotMatch.image_id == image.id).first()
            self.assertIsNotNone(match)
            self.assertNotEqual(match.slot_id, slot.id)
            self.assertEqual(match.status, "unmatched")
        finally:
            if previous_analyzer is not None:
                jd_comparison.analyzer = previous_analyzer
            if group and hasattr(models, "ComparisonPairAnalysis"):
                group.jd_task_id = None
                db.flush()
                db.query(models.ComparisonPairAnalysis).filter(models.ComparisonPairAnalysis.comparison_group_app_id.in_(
                    db.query(models.ComparisonGroupApp.id).filter(models.ComparisonGroupApp.comparison_group_id == group.id)
                )).delete(synchronize_session=False)
                db.query(models.ComparisonSlotMatch).filter(models.ComparisonSlotMatch.comparison_group_id == group.id).delete(synchronize_session=False)
                db.query(models.ComparisonSlot).filter(models.ComparisonSlot.comparison_group_id == group.id).delete(synchronize_session=False)
                db.query(models.ComparisonGroupApp).filter(models.ComparisonGroupApp.comparison_group_id == group.id).delete(synchronize_session=False)
                db.delete(group)
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

    def test_process_image_for_comparison_replaces_lower_quality_slot_match(self):
        from app import crud, models, schemas
        from app.database import SessionLocal
        from app.services import jd_comparison

        class FailingAnalyzer:
            async def match_comparison_slot(self, *args, **kwargs):
                raise AssertionError("terminal page evidence should be enough for replacement")

        db = SessionLocal()
        request = group = task = low_image = high_image = None
        previous_analyzer = jd_comparison.analyzer if hasattr(jd_comparison, "analyzer") else None
        try:
            request = crud.create_request(
                db,
                schemas.RequestCreate(target_app="淘宝", target_scenario="任意活动会场"),
                analysis_skill_snapshots=[],
            )
            task = crud.create_task(db, name="A", keyword="", target_app="淘宝", target_scenario="任意活动会场", request_id=request.id)
            group = crud.create_comparison_group(db, request_id=request.id, baseline_app="京东", jd_instruction="打开京东等价页面并截图")
            crud.create_comparison_group_app(db, group.id, "淘宝", task.id)
            slot = crud.create_comparison_slot(db, group.id, "promo_landing", "活动会场", "平台活动会场首屏", True, 0)
            low_image = crud.create_image(db, schemas.ImageCreate(file_path="low-quality.png", task_id=task.id, source_app="淘宝"))
            high_image = crud.create_image(db, schemas.ImageCreate(file_path="high-quality.png", task_id=task.id, source_app="淘宝"))
            crud.create_analysis(
                db,
                low_image.id,
                "活动入口",
                "弱命中活动入口",
                status="success",
                custom_analysis_json={
                    "page_evidence": {
                        "matched_target_key": "promo_landing",
                        "matched_target_name": "活动会场",
                        "matched_goal_labels": ["活动会场"],
                        "confidence": 0.76,
                        "page_state": "target_page",
                        "target_role": "promo_entry",
                        "is_terminal_target": True,
                        "needs_more_wait": False,
                        "reason": "弱命中首屏入口",
                        "negative_evidence": [],
                    }
                },
            )
            crud.create_analysis(
                db,
                high_image.id,
                "活动会场首屏",
                "明确活动会场商品流和利益点",
                status="success",
                custom_analysis_json={
                    "page_evidence": {
                        "matched_target_key": "promo_landing",
                        "matched_target_name": "活动会场",
                        "matched_goal_labels": ["活动会场"],
                        "confidence": 0.94,
                        "page_state": "target_page",
                        "target_role": "promo_channel",
                        "is_terminal_target": True,
                        "needs_more_wait": False,
                        "reason": "明确到达目标会场首屏",
                        "negative_evidence": [],
                    }
                },
            )

            jd_comparison.analyzer = FailingAnalyzer()
            asyncio.run(jd_comparison.process_image_for_comparison(low_image.id))
            asyncio.run(jd_comparison.process_image_for_comparison(high_image.id))

            matches = (
                db.query(models.ComparisonSlotMatch)
                .filter(models.ComparisonSlotMatch.comparison_group_id == group.id)
                .filter(models.ComparisonSlotMatch.slot_id == slot.id)
                .filter(models.ComparisonSlotMatch.app_name == "淘宝")
                .filter(models.ComparisonSlotMatch.status == "matched")
                .all()
            )
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0].image_id, high_image.id)
            self.assertGreater(matches[0].confidence, 0.9)
        finally:
            if previous_analyzer is not None:
                jd_comparison.analyzer = previous_analyzer
            if group and hasattr(models, "ComparisonPairAnalysis"):
                group.jd_task_id = None
                db.flush()
                db.query(models.ComparisonPairAnalysis).filter(models.ComparisonPairAnalysis.comparison_group_app_id.in_(
                    db.query(models.ComparisonGroupApp.id).filter(models.ComparisonGroupApp.comparison_group_id == group.id)
                )).delete(synchronize_session=False)
                db.query(models.ComparisonSlotMatch).filter(models.ComparisonSlotMatch.comparison_group_id == group.id).delete(synchronize_session=False)
                db.query(models.ComparisonSlot).filter(models.ComparisonSlot.comparison_group_id == group.id).delete(synchronize_session=False)
                db.query(models.ComparisonGroupApp).filter(models.ComparisonGroupApp.comparison_group_id == group.id).delete(synchronize_session=False)
                db.delete(group)
            for image in (high_image, low_image):
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

    def test_pair_analysis_uses_default_skills_when_empty(self):
        from app.services.llm_analyzer import normalize_dynamic_analysis_result

        result = normalize_dynamic_analysis_result(
            {
                "results": [
                    {"skill_name": "设计维度", "analysis": "A侧首屏更强调入口密度，京东更突出价格权益。"},
                    {"skill_name": "运营维度", "analysis": "A侧偏频道导流，京东偏补贴承接和商品转化。"},
                ]
            },
            [],
        )

        self.assertEqual(result["status"], "success")
        self.assertGreaterEqual(len(result["custom_analysis_json"]["results"]), 2)


if __name__ == "__main__":
    unittest.main()
