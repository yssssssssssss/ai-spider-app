import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from run_workflow import (
    DEFAULT_AFTER_CLICK_SECONDS,
    DEFAULT_APP_LOAD_SECONDS,
    JD_APP_PACKAGE,
    build_workflow_from_task_context,
)
from worker.executor import _build_env, _force_stop_target_app, execute_claim


class WorkerWorkflowTests(unittest.TestCase):
    def test_builds_jd_new_tab_workflow_from_task_context(self):
        workflow = build_workflow_from_task_context(
            {
                "name": "打开京东 app，点击新品tab，完成一次截屏",
                "keyword": "新品",
                "target_app": "京东",
                "target_scenario": "新品tab截图",
                "generated_instruction": "",
            }
        )

        self.assertEqual(workflow.name, "京东新品tab截图")
        self.assertEqual([step.action for step in workflow.steps], ["open_app", "click", "screenshot"])
        self.assertEqual(workflow.steps[0].package, JD_APP_PACKAGE)
        self.assertEqual(workflow.steps[0].duration, DEFAULT_APP_LOAD_SECONDS)
        self.assertEqual(workflow.steps[1].target_text, "新品")
        self.assertEqual(workflow.steps[1].duration, DEFAULT_AFTER_CLICK_SECONDS)
        self.assertTrue(workflow.steps[1].required)

    def test_unknown_uiautomator2_task_is_not_silently_mapped_to_demo_workflow(self):
        with self.assertRaises(ValueError):
            build_workflow_from_task_context(
                {
                    "name": "打开未知 app 截图",
                    "keyword": "",
                    "target_app": "未知",
                    "target_scenario": "",
                    "generated_instruction": "",
                }
            )

    def test_worker_force_stop_uses_target_app_package(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir, "worker.log")
            with patch("worker.executor.subprocess.run") as run:
                self.assertTrue(_force_stop_target_app({"target_app": "京东"}, "device-1", log_path))

            run.assert_called_once_with(
                ["adb", "-s", "device-1", "shell", "am", "force-stop", "com.jingdong.app.mall"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            self.assertIn("force-stopped 京东", log_path.read_text(encoding="utf-8"))

    def test_worker_force_stops_target_app_when_process_start_fails(self):
        claim = {
            "run": {"id": "run-1"},
            "task": {
                "id": "task-1",
                "name": "京东任务",
                "target_app": "京东",
                "target_scenario": "新品",
                "mode": "autoglm",
                "generated_instruction": "打开京东",
            },
            "device": {"serial": "device-1"},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir, "worker_runs", "run-1", "worker.log")
            with (
                patch("worker.executor.subprocess.Popen", side_effect=RuntimeError("start failed")),
                patch("worker.executor._force_stop_target_app") as force_stop,
            ):
                with self.assertRaisesRegex(RuntimeError, "start failed"):
                    execute_claim(Path(temp_dir), object(), "node-1", claim)

            force_stop.assert_called_once_with(claim["task"], "device-1", log_path)

    def test_start_script_loads_worker_env_and_uses_worker_venv(self):
        source = Path("scripts/start_local_worker.sh").read_text(encoding="utf-8")

        self.assertIn(".env.worker.local", source)
        self.assertIn(".venv-worker/bin/python", source)
        self.assertIn('exec "${WORKER_PYTHON}" -u -m worker.main', source)

    def test_worker_passes_task_context_to_workflow_script(self):
        env = _build_env(
            Path("/tmp/artifacts"),
            "task-1",
            "run-1",
            "device-1",
            {
                "name": "打开京东 app，点击新品tab，完成一次截屏",
                "keyword": "新品",
                "target_app": "京东",
                "target_scenario": "新品tab截图",
                "generated_instruction": None,
            },
        )

        self.assertEqual(env["WORKFLOW_TASK_NAME"], "打开京东 app，点击新品tab，完成一次截屏")
        self.assertEqual(env["WORKFLOW_TASK_KEYWORD"], "新品")
        self.assertEqual(env["WORKFLOW_TARGET_APP"], "京东")
        self.assertEqual(env["WORKFLOW_TARGET_SCENARIO"], "新品tab截图")
        self.assertEqual(env["WORKFLOW_GENERATED_INSTRUCTION"], "")

    def test_worker_child_uses_the_same_api_endpoint_and_token_as_parent(self):
        env = _build_env(
            Path("/tmp/artifacts"),
            "task-1",
            "run-1",
            "device-1",
            {},
            worker_base_url="http://127.0.0.1:8000/api/worker",
            worker_token="local-worker-token",
        )

        self.assertEqual(env["WORKER_BASE_URL"], "http://127.0.0.1:8000/api/worker")
        self.assertEqual(env["WORKER_API_TOKEN"], "local-worker-token")

    def test_worker_renews_lease_before_each_artifact_and_log_upload(self):
        class FinishedProcess:
            returncode = 0

            def poll(self):
                return 0

        class FakeClient:
            def __init__(self):
                self.calls = []

            def extend_lease(self, run_id, node_key):
                self.calls.append(("lease", run_id, node_key))

            def upload_artifact(self, run_id, node_key, path, **_kwargs):
                self.calls.append(("artifact", path.name))
                return {"image_id": f"image-{path.stem}", "file_path": str(path), "oss_url": ""}

            def upload_log(self, run_id, node_key, _text):
                self.calls.append(("log", run_id, node_key))

        claim = {
            "run": {"id": "run-1"},
            "task": {
                "id": "task-1",
                "target_app": "京东",
                "target_scenario": "新品楼层规范检查",
                "mode": "jd_new_floor_audit",
            },
            "device": {"serial": "device-1"},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            artifacts_dir = Path(temp_dir, "worker_runs", "run-1", "artifacts")
            artifacts_dir.mkdir(parents=True)
            Path(artifacts_dir, "raw_fullscreen.png").write_bytes(b"raw")
            Path(artifacts_dir, "annotated_floor_audit.png").write_bytes(b"annotated")
            secondary_frames = {
                "z1_before": {"filename": "secondary_tab_z1_before.png"},
                "z1_after_left": {"filename": "secondary_tab_z1_after_left.png"},
                "z2_before": {"filename": "secondary_tab_z2_before.png"},
                "z2_after_left": {"filename": "secondary_tab_z2_after_left.png"},
                "z3_before": {"filename": "secondary_tab_z3_before.png"},
            }
            for index, frame in enumerate(secondary_frames.values(), start=1):
                Path(artifacts_dir, frame["filename"]).write_bytes(f"secondary-{index}".encode())
            Path(artifacts_dir, "jd_new_floor_report.json").write_text(
                json.dumps(
                    {
                        "report_type": "jd_new_floor_audit",
                        "artifacts": {
                            "raw": {"filename": "raw_fullscreen.png"},
                            "annotated": {"filename": "annotated_floor_audit.png"},
                        },
                        "secondary_tab_audit": {
                            "report_type": "jd_secondary_tab_audit",
                            "frames": secondary_frames,
                        },
                    }
                ),
                encoding="utf-8",
            )
            client = FakeClient()
            with (
                patch("worker.executor.subprocess.Popen", return_value=FinishedProcess()),
                patch("worker.executor._force_stop_target_app"),
            ):
                result = execute_claim(Path(temp_dir), client, "node-1", claim)

        upload_indexes = [index for index, call in enumerate(client.calls) if call[0] in {"artifact", "log"}]
        self.assertTrue(upload_indexes)
        self.assertTrue(all(client.calls[index - 1][0] == "lease" for index in upload_indexes))
        self.assertEqual(result.uploaded_count, 7)
        self.assertEqual(
            result.result_json["secondary_tab_audit"]["frames"]["z3_before"]["image_id"],
            "image-secondary_tab_z3_before",
        )


if __name__ == "__main__":
    unittest.main()
