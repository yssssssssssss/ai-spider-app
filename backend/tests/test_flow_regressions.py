import asyncio
import json
import os
import subprocess
import sys
import unittest
import base64
import tempfile
from datetime import UTC, datetime, time, timedelta
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)


def utc_now():
    return datetime.now(UTC).replace(tzinfo=None)


class FlowRegressionTests(unittest.TestCase):
    def test_stitch_images_crops_adjacent_vertical_overlap(self):
        from PIL import Image
        from app.services.long_screenshot import stitch_images

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_path = root / "first.png"
            second_path = root / "second.png"
            output_path = root / "stitched.png"

            first = Image.new("RGB", (8, 10))
            for y in range(10):
                for x in range(8):
                    first.putpixel((x, y), (y, x, 0))
            first.save(first_path)

            second = Image.new("RGB", (8, 10))
            for y in range(10):
                source_row = y + 6
                for x in range(8):
                    second.putpixel((x, y), (source_row, x, 0))
            second.save(second_path)

            result = stitch_images([str(first_path), str(second_path)], str(output_path), min_overlap=2)

            self.assertEqual(result.crop_tops, [0, 4])
            with Image.open(output_path) as stitched:
                self.assertEqual(stitched.size, (8, 16))
                self.assertEqual([stitched.getpixel((0, y))[0] for y in range(16)], list(range(16)))

    def test_stitch_images_keeps_frames_without_clear_overlap(self):
        from PIL import Image
        from app.services.long_screenshot import stitch_images

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_path = root / "first.png"
            second_path = root / "second.png"
            output_path = root / "stitched.png"

            Image.new("RGB", (6, 5), (10, 20, 30)).save(first_path)
            Image.new("RGB", (6, 5), (200, 210, 220)).save(second_path)

            result = stitch_images([str(first_path), str(second_path)], str(output_path), min_overlap=2)

            self.assertEqual(result.crop_tops, [0, 0])
            with Image.open(output_path) as stitched:
                self.assertEqual(stitched.size, (6, 10))

    def test_task_runner_detects_product_detail_long_capture(self):
        from app.services.task_runner import product_detail_long_capture_count

        task = SimpleNamespace(
            name="手机商品详情长图",
            keyword="手机",
            target_scenario="商品详情页滚动 10 屏并拼接长图",
            generated_instruction="打开淘宝，搜索手机，进入一个商品详情页后停留并结束任务",
            request=SimpleNamespace(description="每一屏截图，重复区域裁切掉"),
        )

        self.assertEqual(product_detail_long_capture_count(task, task.generated_instruction), 10)

    def test_task_runner_does_not_trigger_long_capture_for_plain_detail_page(self):
        from app.services.task_runner import product_detail_long_capture_count

        task = SimpleNamespace(
            name="手机商品详情",
            keyword="手机",
            target_scenario="商品详情页首屏",
            generated_instruction="打开淘宝，搜索手机，进入一个商品详情页后停留并结束任务",
            request=SimpleNamespace(description="只看首屏"),
        )

        self.assertIsNone(product_detail_long_capture_count(task, task.generated_instruction))

    def test_task_runner_adds_navigation_only_rule_for_long_capture(self):
        from app.services.task_runner import apply_product_detail_long_capture_rule

        instruction = apply_product_detail_long_capture_rule("打开淘宝，搜索手机，进入商品详情页")

        self.assertIn("进入商品详情页首屏", instruction)
        self.assertIn("不要滚动详情页", instruction)
        self.assertIn("长图拼接由平台自动处理", instruction)

    def test_autoglm_runner_exposes_product_detail_long_capture_hook(self):
        source = Path(PROJECT_ROOT, "run_autoglm.py").read_text(encoding="utf-8")
        config_source = Path(PROJECT_ROOT, "backend", "app", "config.py").read_text(encoding="utf-8")

        self.assertIn("--post-capture-mode", source)
        self.assertIn("product_detail_long_image", source)
        self.assertIn("capture_product_detail_long_image", source)
        self.assertIn("MAX_AUTOGLM_STEPS = 30", source)
        self.assertIn('os.getenv("AUTOGLM_MAX_STEPS", "30")', config_source)

    def test_autoglm_runner_skips_long_capture_when_navigation_failed(self):
        import importlib.util

        sys.path.insert(0, PROJECT_ROOT)
        spec = importlib.util.spec_from_file_location("run_autoglm_module", os.path.join(PROJECT_ROOT, "run_autoglm.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        failed = SimpleNamespace(success=False, finished=True, message="Model error: blocked")
        unfinished = SimpleNamespace(success=True, finished=False, message="still running")
        finished = SimpleNamespace(success=True, finished=True, message="done")

        self.assertFalse(module._should_run_post_capture(failed, module.PRODUCT_DETAIL_LONG_CAPTURE_MODE))
        self.assertFalse(module._should_run_post_capture(unfinished, module.PRODUCT_DETAIL_LONG_CAPTURE_MODE))
        self.assertTrue(module._should_run_post_capture(finished, module.PRODUCT_DETAIL_LONG_CAPTURE_MODE))

    def test_manage_clean_accepts_explicit_dry_run_flag(self):
        result = subprocess.run(
            [sys.executable, "manage.py", "clean", "--dry-run", "--no-logs", "--no-pycache"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

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

    def test_image_card_detail_supports_long_image_preview_and_download(self):
        component = Path(PROJECT_ROOT, "frontend", "src", "components", "ImageCard.tsx").read_text(encoding="utf-8")
        styles = Path(PROJECT_ROOT, "frontend", "src", "styles", "index.css").read_text(encoding="utf-8")

        self.assertIn("image-detail-preview-pane", component)
        self.assertIn("image-detail-preview-scroll", component)
        self.assertIn("image-detail-image", component)
        self.assertIn("下载图片", component)
        self.assertIn("download={downloadFilename}", component)
        self.assertNotIn("maxHeight: '86vh'", component)
        self.assertIn(".image-detail-preview-pane", styles)
        self.assertIn("overflow-y: auto", styles)
        self.assertIn(".image-detail-image", styles)
        self.assertIn("width: clamp(360px, 38vw, 520px)", styles)

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
        old_plan_task = admin_router.plan_task
        admin_router.plan_task = fake_plan_task
        try:
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

            submitter_tasks = client.get("/api/admin/tasks", headers=submitter_headers).json()
            self.assertIn(body["id"], [row["id"] for row in submitter_tasks])
        finally:
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
        self.assertLessEqual(settings.AUTOGLM_MAX_STEPS, 30)

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

    def test_autoglm_prompt_says_screenshots_are_automatic_and_must_stop(self):
        import importlib.util

        sys.path.insert(0, PROJECT_ROOT)
        spec = importlib.util.spec_from_file_location("run_autoglm_module", os.path.join(PROJECT_ROOT, "run_autoglm.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        prompt = module._append_auto_screenshot_stop_rule("打开拼多多App，找到百亿补贴，并截图保存到本地")
        prompt_again = module._append_auto_screenshot_stop_rule(prompt)

        self.assertIn("平台会按任务配置自动采集截图并保存", prompt)
        self.assertIn("禁止打开系统设置、相册、文件管理、截图工具", prompt)
        self.assertIn("必须立即结束任务", prompt)
        self.assertEqual(prompt, prompt_again)

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

        self.assertIn("目标截图清单", prompt)
        self.assertIn("1. 限时秒杀", prompt)
        self.assertIn("2. 百亿补贴", prompt)
        self.assertIn("平台会在每一步自动截图并保存", prompt)
        self.assertIn("完成所有目标页后立即结束任务", prompt)

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


if __name__ == "__main__":
    unittest.main()
