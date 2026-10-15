import asyncio
import base64
import json
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

import run_autoglm as runner
from app.services import target_verifier
from app.services.llm_analyzer import LLMAnalyzer
from app.services.model_trace import capture_model_calls
from worker import executor


GOALS = [{"label": "新奇集市", "evidence_keywords": ["新品"], "required": True}]


def frame(shade):
    buffer = BytesIO()
    Image.new("RGB", (32, 64), (shade, shade, shade)).save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return SimpleNamespace(base64_data=encoded, original_base64_data=encoded)


def verdict(value, reason="画面证据"):
    return {"verdict": value, "reason": reason, "model": "fake-vision"}


class ScriptedAgent:
    """Model the SDK's pre-action screenshot and copied context property."""
    def __init__(self, plan):
        self.plan = iter(plan)
        self.step_count = 0
        self._context = []
        self.contexts_seen = []
        self.current_screen = frame(0)
        self.last_screenshot = None
        self.model_client = object()

    @property
    def context(self):
        return self._context.copy()

    def step(self, task=None):
        self.contexts_seen.append(self.context)
        self.last_screenshot = self.current_screen
        shade, finished, message = next(self.plan)
        self.current_screen = frame(shade)
        self.step_count += 1
        self._context.append({"role": "assistant", "content": "finish" if finished else "tap"})
        return SimpleNamespace(success=True, finished=finished, message=message, action={})


@pytest.fixture
def navigation(tmp_path, monkeypatch):
    monkeypatch.setenv("CAPTURE_SINK", "local_files")
    monkeypatch.setattr(runner, "set_device_type", Mock())
    monkeypatch.setattr("worker.model_trace.trace_phone_client", Mock())
    state = SimpleNamespace(output=tmp_path)

    def run(plan, checks=None, *, goals=GOALS, **kwargs):
        state.agent = ScriptedAgent(plan)
        monkeypatch.setattr(runner, "PhoneAgent", Mock(return_value=state.agent))
        state.device = Mock()
        state.device.get_screenshot.side_effect = lambda _: state.agent.current_screen
        monkeypatch.setattr(runner, "get_device_factory", Mock(return_value=state.device))
        if checks is not None:
            state.verify = AsyncMock(side_effect=[verdict(item) for item in checks])
            monkeypatch.setattr(target_verifier, "verify_target", state.verify)
        return runner.run_with_autoglm(
            kwargs.pop("task", "打开京东新奇集市"), output_dir=str(tmp_path),
            exit_app=False, target_goals_json=goals, target_app="京东", scenario="新奇集市", **kwargs,
        )

    state.run = run
    state.report = lambda: json.loads((tmp_path / "autoglm_result.json").read_text())
    return state


def test_stops_on_reached_step_and_saves_post_action_screen(navigation):
    navigation.run([(80, False, "仍想滑动"), (160, False, "再滑动")], ["reached"], final_capture=True)
    assert navigation.agent.step_count == 1
    assert navigation.verify.call_args.args[0] == navigation.agent.current_screen.base64_data
    saved = list(navigation.output.glob("autoglm_step_*.png"))
    assert len(saved) == 1
    with Image.open(saved[0]) as image:
        assert image.getpixel((0, 0)) == (80, 80, 80)
    report = navigation.report()
    assert report["target_verification"] == "reached"
    assert report["target_verification_records"] == [
        {"step": 1, "trigger": "screen_change", **verdict("reached")},
    ]


def test_rejects_false_finish_injects_context_then_reaches(navigation):
    navigation.run([(20, True, "完成"), (120, False, "点击目标")], ["not_reached", "reached"])
    assert navigation.agent.step_count == 2
    assert navigation.agent.contexts_seen[1][-1] == {
        "role": "user", "content": "目标尚未到达：画面证据，继续操作",
    }
    assert navigation.report()["target_verification"] == "reached"


def test_third_false_finish_fails_with_reason_and_report(navigation):
    with pytest.raises(RuntimeError, match="目标页未到达"):
        navigation.run([(20, True, "完成")] * 4, ["not_reached"] * 3)
    assert navigation.agent.step_count == 3
    assert navigation.verify.await_count == 3
    report = navigation.report()
    assert report["target_verification"] == "not_reached"
    assert "目标页未到达" in report["failure_reason"]
    assert [record["step"] for record in report["target_verification_records"]] == [1, 2, 3]


def test_uncertain_finish_is_accepted(navigation):
    navigation.run([(20, True, "完成")], ["uncertain"])
    assert navigation.report()["target_verification"] == "uncertain"


def test_active_checks_are_bounded_but_finish_is_still_verified(navigation):
    limit = runner.MAX_ACTIVE_TARGET_CHECKS
    plan = [(20 if i % 2 else 220, False, "滑动") for i in range(limit + 3)]
    navigation.run(plan + [(100, True, "完成")], ["not_reached"] * limit + ["uncertain"])
    assert navigation.verify.await_count == limit + 1
    assert navigation.agent.step_count == limit + 4
    records = navigation.report()["target_verification_records"]
    assert sum(record["trigger"] == "screen_change" for record in records) == limit
    assert records[-1]["trigger"] == "finish"


def test_unchanged_or_small_changes_are_compared_to_last_check(navigation):
    navigation.run(
        [(20, False, "点击"), (20, False, "等待"), (24, False, "等待"), (28, False, "变化")],
        ["not_reached", "reached"],
    )
    assert navigation.verify.await_count == 2
    assert [r["step"] for r in navigation.report()["target_verification_records"]] == [1, 4]


@pytest.mark.parametrize("finished", [False, True])
def test_login_stop_precedes_verification(navigation, finished):
    with pytest.raises(RuntimeError, match="检测到登录页"):
        navigation.run([(20, finished, "请登录后继续")], ["reached"])
    navigation.verify.assert_not_called()
    navigation.device.get_screenshot.assert_not_called()
    assert "登录页" in navigation.report()["failure_reason"]


def test_popup_must_close_before_target_can_stop(navigation):
    navigation.run(
        [(20, False, "入口"), (80, True, "弹层"), (180, False, "已关闭")],
        ["reached"], task="打开京东新奇集市，关闭弹窗后截图",
    )
    assert navigation.agent.step_count == 3
    assert navigation.verify.await_count == 1
    assert navigation.report()["target_verification_records"][0]["step"] == 3


def test_popup_finish_at_step_limit_cannot_bypass_verification(navigation):
    with pytest.raises(RuntimeError, match="目标页未到达"):
        navigation.run([(80, True, "弹层")], ["reached"], max_steps=1,
                       task="打开京东新奇集市，关闭弹窗后截图")
    navigation.verify.assert_not_called()
    assert navigation.report()["target_verification"] == "not_reached"


def test_goals_work_even_when_screenshot_persistence_disabled(navigation):
    navigation.run([(20, False, "已到达")], ["reached"], capture_screenshots=False)
    assert navigation.report()["target_verification"] == "reached"
    assert not list(navigation.output.glob("*.png"))


@pytest.mark.parametrize("goals", [None, []])
def test_no_goals_keeps_sdk_finish_and_capture_behavior(navigation, goals):
    navigation.run([(20, False, "进入"), (80, True, "完成")], [], goals=goals)
    navigation.verify.assert_not_called()
    navigation.device.get_screenshot.assert_not_called()
    assert navigation.agent.step_count == 2
    report = navigation.report()
    assert report["target_verification"] == "disabled"
    assert report["target_verification_records"] == []
    # Existing capture uses the SDK's pre-action screen when goals are absent.
    with Image.open(next(navigation.output.glob("*.png"))) as image:
        assert image.getpixel((0, 0)) == (20, 20, 20)


@pytest.mark.parametrize("goals,reason", [(GOALS, "目标页未到达"), ([], "AutoGLM did not reach")])
def test_step_limit_cannot_accept_rejected_finish(navigation, goals, reason):
    with pytest.raises(RuntimeError, match=reason):
        navigation.run([(20, bool(goals), "仍在首页")], ["not_reached"], goals=goals, max_steps=1)
    assert reason in navigation.report()["failure_reason"]


@pytest.fixture
def visual_model(monkeypatch):
    analyzer = LLMAnalyzer()
    provider = {"name": "test", "base_url": "https://vision.invalid/v1", "model": "requested-vlm", "api_key": "test-secret"}
    analyzer.providers = [provider, {**provider, "name": "fallback"}]
    monkeypatch.setattr(target_verifier, "LLMAnalyzer", lambda: analyzer)
    original = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr("app.services.llm_analyzer.httpx.AsyncClient", lambda: original(transport=httpx.MockTransport(handler)))
    return install


def test_model_errors_retry_once_then_accept_uncertain_with_trace(navigation, visual_model):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(503, json={"error": "unavailable"})

    visual_model(handler)
    navigation.run([(20, True, "完成")])
    assert len(requests) == 2  # No provider fallback multiplies the retry budget.
    assert navigation.report()["target_verification"] == "uncertain"
    from worker.model_trace import read_model_calls
    calls = read_model_calls(navigation.output)
    assert len(calls) == 2
    assert all(call["purpose"] == "target_verification" and call["status"] == "failed" for call in calls)
    assert "test-secret" not in json.dumps(calls)


@pytest.mark.parametrize("first", [None, "malformed"])
def test_verifier_retries_model_or_parse_error_and_preserves_prompt_context(visual_model, first):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            if first is None:
                return httpx.Response(500)
            content = "not JSON"
        else:
            content = json.dumps({"verdict": "reached", "reason": "标题为新奇集市"})
        return httpx.Response(200, json={"model": "actual-vlm", "choices": [{"message": {"content": content}}]})

    visual_model(handler)
    with capture_model_calls() as calls:
        result = asyncio.run(target_verifier.verify_target(frame(20).base64_data, GOALS, "京东", "逛新品"))
    assert result["verdict"] == "reached"
    assert len(calls) == len(requests) == 2
    assert calls[-1]["response_model"] == "actual-vlm"
    assert all(call["purpose"] == "target_verification" for call in calls)
    prompt = requests[-1]["messages"][0]["content"][0]["text"]
    assert all(text in prompt for text in ("京东", "逛新品", "新奇集市", "新品"))


def test_sdk_error_is_not_converted_to_goal_success(navigation, monkeypatch):
    def fail(self, task=None):
        self.step_count += 1
        return SimpleNamespace(success=False, finished=True, message="Model error: blocked", action={})
    monkeypatch.setattr(ScriptedAgent, "step", fail)
    with pytest.raises(RuntimeError, match="navigation failed"):
        navigation.run([], ["reached"])
    navigation.verify.assert_not_called()


def test_worker_passes_goals_and_reads_report_even_on_failure(tmp_path, monkeypatch):
    report = {"target_verification": "not_reached", "target_verification_records": [verdict("not_reached")],
              "failure_reason": "目标页未到达：连续三次假完成"}
    task = {"id": "task", "mode": "autoglm", "target_app": "京东", "target_scenario": "新奇集市", "target_goals_json": GOALS}
    claim = {"run": {"id": "run"}, "task": task, "device": {"serial": "fake-device"}}
    client = Mock()
    client.headers = {}
    client.base_url = "https://worker.invalid"

    def process(command, **kwargs):
        env = kwargs["env"]
        assert json.loads(env["WORKFLOW_TARGET_GOALS_JSON"]) == GOALS
        assert env["WORKFLOW_TARGET_SCENARIO"] == "新奇集市"
        (Path(env["TASK_OUTPUT_DIR"]) / "autoglm_result.json").write_text(json.dumps(report))
        return SimpleNamespace(returncode=1, poll=lambda: 1)

    monkeypatch.setattr(executor.subprocess, "Popen", process)
    monkeypatch.setattr(executor, "_force_stop_target_app", Mock())
    result = executor.execute_claim(tmp_path, client, "node", claim)
    assert result.exit_code == 1
    assert result.result_json == report
    client.upload_log.assert_called_once()
    # Absent goals override any inherited task's environment value.
    monkeypatch.setenv("WORKFLOW_TARGET_GOALS_JSON", json.dumps(GOALS))
    assert executor._build_env(tmp_path, "task", "run", "device", {})["WORKFLOW_TARGET_GOALS_JSON"] == "[]"


def test_worker_uploads_result_before_fail_and_preserves_failure_reason(tmp_path, monkeypatch):
    from worker import main
    report = {"target_verification": "not_reached", "failure_reason": "目标页未到达：三次假完成"}
    client = Mock()
    client.claim.side_effect = [{"claimed": True, "run": {"id": "run"}, "device": {"serial": "device"}}, {"claimed": False}]
    args = SimpleNamespace(repo_root=tmp_path, base_url="https://worker.invalid", token="test", capabilities="autoglm",
                           node_key="node", name="worker", once=True, poll_seconds=1)
    monkeypatch.setattr(main, "parse_args", lambda: args)
    monkeypatch.setattr(main, "WorkerClient", Mock(return_value=client))
    monkeypatch.setattr(main, "list_adb_devices", lambda: [])
    monkeypatch.setattr(main, "execute_claim", lambda *args: executor.ExecutionResult(1, 0, tmp_path / "log", report))
    monkeypatch.setattr(main.time, "sleep", Mock())
    assert main.main() == 0
    client.fail.assert_called_once_with("run", "node", 1, report["failure_reason"])
    assert [call[0] for call in client.method_calls if call[0] in ("upload_result", "finish", "fail")] == ["upload_result", "fail"]


def test_verification_is_readable_from_task_run_result_json(navigation):
    from app import models
    from app.database import SessionLocal, engine, init_db
    from app.services.worker_dispatch import store_worker_result

    if engine.url.database != "competitor_db_t80_test":
        pytest.skip("Requires the T8-0 disposable database")
    init_db()
    navigation.run([(80, False, "已到达")], ["reached"])
    with SessionLocal() as db:
        task = models.Task(name="T8-0 result trace", status="running", mode="autoglm")
        db.add(task)
        db.flush()
        run = models.TaskRun(task_id=task.id, attempt_no=1, status="running", worker_node_key="t80-node")
        db.add(run)
        db.commit()
        try:
            store_worker_result(db, run.id, "t80-node", navigation.report())
            db.expire_all()
            saved = db.get(models.TaskRun, run.id).result_json
            assert saved["target_verification"] == "reached"
            assert saved["target_verification_records"][0]["step"] == 1
        finally:
            db.delete(task)
            db.commit()
