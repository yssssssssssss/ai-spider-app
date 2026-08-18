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


if __name__ == "__main__":
    unittest.main()
