import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_DIR = os.path.join(PROJECT_ROOT, "backend")
sys.path.insert(0, BACKEND_DIR)


class JdNewFloorIntegrationTests(unittest.TestCase):
    def test_floor_audit_is_worker_only_phone_mode(self):
        from app.services import task_queue, worker_dispatch

        task = SimpleNamespace(mode="jd_new_floor_audit")
        self.assertIn("jd_new_floor_audit", worker_dispatch.PHONE_TASK_MODES)
        self.assertIn("jd_new_floor_audit", task_queue.WORKER_ONLY_TASK_MODES)
        self.assertTrue(worker_dispatch._task_supported(task, {"jd_new_floor_audit"}))
        self.assertFalse(worker_dispatch._task_supported(task, {"autoglm"}))

    def test_floor_audit_cannot_finish_without_report(self):
        from app.services import worker_dispatch

        run = SimpleNamespace(
            id="run-1",
            task_id="task-1",
            worker_node_key="node-1",
            status="running",
            artifact_count=1,
            result_json={},
            task=SimpleNamespace(mode="jd_new_floor_audit"),
        )
        failed = SimpleNamespace(status="failed")
        with (
            patch.object(worker_dispatch.crud, "get_task_run", return_value=run),
            patch.object(worker_dispatch.crud, "update_task_status"),
            patch.object(worker_dispatch.crud, "update_task_run", return_value=failed) as update_run,
            patch.object(worker_dispatch.crud, "release_device_for_run"),
            patch.object(worker_dispatch, "push_event"),
            patch.object(worker_dispatch, "_finish_queue_tail"),
        ):
            result = worker_dispatch.finish_worker_run(object(), run.id, "node-1", 0, 1)

        self.assertIs(result, failed)
        self.assertEqual(update_run.call_args.kwargs["failure_reason"], "floor audit report is missing")

    def test_floor_audit_cannot_finish_without_both_run_images(self):
        from app.services import worker_dispatch

        run_id = uuid4()
        raw_id = uuid4()
        run = SimpleNamespace(
            id=run_id,
            task_id=uuid4(),
            worker_node_key="node-1",
            status="running",
            artifact_count=1,
            result_json={
                "report_type": "jd_new_floor_audit",
                "artifacts": {"raw": {"image_id": str(raw_id)}, "annotated": {}},
            },
            task=SimpleNamespace(mode="jd_new_floor_audit"),
        )
        failed = SimpleNamespace(status="failed")
        with (
            patch.object(worker_dispatch.crud, "get_task_run", return_value=run),
            patch.object(worker_dispatch.crud, "get_image", return_value=SimpleNamespace(task_run_id=run_id)),
            patch.object(worker_dispatch.crud, "update_task_status"),
            patch.object(worker_dispatch.crud, "update_task_run", return_value=failed) as update_run,
            patch.object(worker_dispatch.crud, "release_device_for_run"),
            patch.object(worker_dispatch, "push_event"),
            patch.object(worker_dispatch, "_finish_queue_tail"),
        ):
            result = worker_dispatch.finish_worker_run(object(), run.id, "node-1", 0, 1)

        self.assertIs(result, failed)
        self.assertEqual(
            update_run.call_args.kwargs["failure_reason"],
            "floor audit annotated image is missing from this run",
        )

    def test_floor_audit_finishes_with_both_images_attached_to_run(self):
        from app.services import worker_dispatch

        run_id = uuid4()
        run = SimpleNamespace(
            id=run_id,
            task_id=uuid4(),
            worker_node_key="node-1",
            status="running",
            artifact_count=2,
            result_json={
                "report_type": "jd_new_floor_audit",
                "artifacts": {
                    "raw": {"image_id": str(uuid4())},
                    "annotated": {"image_id": str(uuid4())},
                },
            },
            task=SimpleNamespace(mode="jd_new_floor_audit"),
        )
        completed = SimpleNamespace(status="completed")
        with (
            patch.object(worker_dispatch.crud, "get_task_run", return_value=run),
            patch.object(worker_dispatch.crud, "get_image", return_value=SimpleNamespace(task_run_id=run_id)),
            patch.object(worker_dispatch.crud, "update_task_status"),
            patch.object(worker_dispatch.crud, "update_task_run", return_value=completed),
            patch.object(worker_dispatch.crud, "release_device_for_run"),
            patch.object(worker_dispatch, "push_event"),
            patch.object(worker_dispatch, "_finish_queue_tail"),
        ):
            result = worker_dispatch.finish_worker_run(object(), run.id, "node-1", 0, 2)

        self.assertIs(result, completed)

    def test_floor_audit_rejects_incomplete_secondary_evidence_when_section_exists(self):
        from app.services import worker_dispatch

        run_id = uuid4()
        run = SimpleNamespace(
            id=run_id,
            task_id=uuid4(),
            worker_node_key="node-1",
            status="running",
            artifact_count=7,
            result_json={
                "report_type": "jd_new_floor_audit",
                "artifacts": {
                    "raw": {"image_id": str(uuid4())},
                    "annotated": {"image_id": str(uuid4())},
                },
                "secondary_tab_audit": {
                    "report_type": "jd_secondary_tab_audit",
                    "frames": {"z1_before": {"image_id": str(uuid4())}},
                },
            },
            task=SimpleNamespace(mode="jd_new_floor_audit"),
        )
        failed = SimpleNamespace(status="failed")
        with (
            patch.object(worker_dispatch.crud, "get_task_run", return_value=run),
            patch.object(worker_dispatch.crud, "get_image", return_value=SimpleNamespace(task_run_id=run_id)),
            patch.object(worker_dispatch.crud, "update_task_status"),
            patch.object(worker_dispatch.crud, "update_task_run", return_value=failed) as update_run,
            patch.object(worker_dispatch.crud, "release_device_for_run"),
            patch.object(worker_dispatch, "push_event"),
            patch.object(worker_dispatch, "_finish_queue_tail"),
        ):
            result = worker_dispatch.finish_worker_run(object(), run.id, "node-1", 0, 7)

        self.assertIs(result, failed)
        self.assertEqual(
            update_run.call_args.kwargs["failure_reason"],
            "secondary Tab z1_after_left image is missing from this run",
        )

    def test_floor_audit_rejects_a_local_device_before_creating_a_run(self):
        from app.services import task_queue

        task = SimpleNamespace(mode="jd_new_floor_audit", status="pending")
        with (
            patch.object(task_queue.crud, "get_device", return_value=SimpleNamespace(notes="local adb")),
            patch.object(task_queue.crud, "create_task_run") as create_run,
        ):
            with self.assertRaisesRegex(task_queue.TaskQueueError, "registered worker device"):
                task_queue.start_or_enqueue_task(
                    object(),
                    task,
                    created_by=None,
                    requested_device_id=uuid4(),
                )
        create_run.assert_not_called()

    def test_worker_analysis_endpoint_is_token_protected(self):
        from fastapi.testclient import TestClient

        from app.config import settings
        from app.main import app
        from app.services.jd_new_floor_analyzer import JdNewFloorAnalysis, jd_new_floor_analyzer

        expected = JdNewFloorAnalysis(
            report_type="jd_new_floor_audit",
            schema_version=1,
            capture={"format": "PNG", "width": 1080, "height": 2400},
            regions={"x": {"bbox_px": [0, 510, 1080, 1090]}, "y": {"bbox_px": [0, 510, 540, 1090]}},
            checks={},
            summary={"status": "pass", "counts": {}},
        )
        old_token = settings.WORKER_API_TOKEN
        settings.WORKER_API_TOKEN = "worker-test-token"
        try:
            client = TestClient(app)
            unauthorized = client.post(
                "/api/worker/jd-new-floor-analyze",
                files={"file": ("frame.png", b"png", "image/png")},
            )
            self.assertEqual(unauthorized.status_code, 401)

            with patch.object(jd_new_floor_analyzer, "analyze_png", new=AsyncMock(return_value=expected)):
                response = client.post(
                    "/api/worker/jd-new-floor-analyze",
                    files={"file": ("frame.png", b"png", "image/png")},
                    headers={"X-Worker-Token": "worker-test-token"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["report_type"], "jd_new_floor_audit")
        finally:
            settings.WORKER_API_TOKEN = old_token

    def test_worker_secondary_tab_locator_endpoint_is_token_protected(self):
        from fastapi.testclient import TestClient

        from app.config import settings
        from app.main import app
        from app.services.jd_secondary_tab_analyzer import jd_secondary_tab_analyzer

        expected = {
            "report_type": "jd_secondary_tab_locator",
            "anchor_text": "推荐",
            "anchor_color": "red",
            "anchor_bbox_px": [45, 1036, 125, 1075],
            "bbox_px": [0, 1010, 1080, 1090],
            "visible_texts": ["推荐", "新奇AI"],
            "evidence": "红色推荐所在横向Tab行",
        }
        old_token = settings.WORKER_API_TOKEN
        settings.WORKER_API_TOKEN = "worker-test-token"
        try:
            client = TestClient(app)
            unauthorized = client.post(
                "/api/worker/jd-secondary-tab-locate",
                files={"file": ("frame.png", b"png", "image/png")},
            )
            self.assertEqual(unauthorized.status_code, 401)

            with patch.object(
                jd_secondary_tab_analyzer,
                "locate_z1_png",
                new=AsyncMock(return_value=expected),
            ):
                response = client.post(
                    "/api/worker/jd-secondary-tab-locate",
                    files={"file": ("frame.png", b"png", "image/png")},
                    headers={"X-Worker-Token": "worker-test-token"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["bbox_px"], [0, 1010, 1080, 1090])
        finally:
            settings.WORKER_API_TOKEN = old_token

    def test_worker_secondary_tab_endpoint_is_token_protected(self):
        from fastapi.testclient import TestClient

        from app.config import settings
        from app.main import app
        from app.services.jd_secondary_tab_analyzer import (
            FRAME_KEYS,
            JdSecondaryTabAnalysis,
            jd_secondary_tab_analyzer,
        )

        expected = JdSecondaryTabAnalysis(
            report_type="jd_secondary_tab_audit",
            schema_version=1,
            capture={"format": "PNG", "width": 1080, "height": 2400},
            regions={},
            frames={},
            checks={},
            summary={"status": "pass", "counts": {}},
        )
        files = {key: (f"{key}.png", b"png", "image/png") for key in FRAME_KEYS}
        old_token = settings.WORKER_API_TOKEN
        settings.WORKER_API_TOKEN = "worker-test-token"
        try:
            client = TestClient(app)
            unauthorized = client.post(
                "/api/worker/jd-secondary-tab-analyze",
                data={"z1_top": "1010", "z1_bottom": "1090"},
                files=files,
            )
            self.assertEqual(unauthorized.status_code, 401)

            with patch.object(
                jd_secondary_tab_analyzer,
                "analyze_pngs",
                new=AsyncMock(return_value=expected),
            ):
                response = client.post(
                    "/api/worker/jd-secondary-tab-analyze",
                    data={"z1_top": "1010", "z1_bottom": "1090"},
                    files=files,
                    headers={"X-Worker-Token": "worker-test-token"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["report_type"], "jd_secondary_tab_audit")
        finally:
            settings.WORKER_API_TOKEN = old_token


if __name__ == "__main__":
    unittest.main()
