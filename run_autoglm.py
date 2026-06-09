"""
AutoGLM 驱动脚本
使用 Open-AutoGLM 的 AI 能力驱动手机完成淘宝截图任务
- 每一步自动截图保存到本地
- 上传到京东云 OSS
- 将 OSS URL 写入数据库
"""
import os
import sys
import argparse
import base64
import re
import subprocess
from datetime import datetime
from PIL import Image, ImageOps, UnidentifiedImageError

# 加载项目根目录 .env 文件（如果存在）
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

# 将 Open-AutoGLM 和 backend 加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Open-AutoGLM"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from phone_agent import PhoneAgent
from phone_agent.agent import AgentConfig
from phone_agent.config.apps import get_package_name
from phone_agent.model import ModelConfig
from phone_agent.device_factory import DeviceType, set_device_type

import config as app_config

from app.services.oss_uploader import oss_uploader
from app.scripts_common import save_image_to_db


POPUP_CLOSE_MARKERS = ("弹窗", "浮层", "广告", "关闭", "关闭后", "跳过")
POPUP_CONTINUE_TASK = (
    "继续执行：你还没有完成弹窗关闭后的页面截图。"
    "如果当前仍有弹窗、广告或浮层，只允许点击明确的X、×或“关闭”按钮关闭它；"
    "禁止点击开心收下、立即领取、去使用、立即购买、抢、领券、跳过、取消、返回或任何业务内容。"
    "找不到明确关闭按钮时，不要点击其他内容，直接结束并说明未找到关闭按钮；"
    "弹窗消失后停留在目标页面，等待截图保存，然后再结束任务。"
)
POPUP_BACK_TASK = (
    "继续执行：当前界面关闭弹窗后没有明显变化。"
    "请只点击明确的X、×或“关闭”按钮关闭弹窗、广告或浮层。"
    "禁止点击开心收下、立即领取、去使用、立即购买、抢、领券、跳过、取消、返回或任何业务内容。"
    "如果没有明确关闭按钮，不要点击其他内容，直接结束并说明未找到关闭按钮；"
    "关闭后停留在目标页面等待截图保存，不要提前结束。"
)
AUTO_SCREENSHOT_STOP_RULE = (
    "执行约束：到达目标页面后停留并结束任务。"
    "不要打开与目标无关的应用，不要继续探索无关页面。"
)
MAX_AUTOGLM_STEPS = 10
PAGE_TRANSITION_ACTIONS = {"Tap", "Back", "Home", "Launch", "Swipe"}


def _append_auto_screenshot_stop_rule(task: str) -> str:
    if AUTO_SCREENSHOT_STOP_RULE in task:
        return task
    return f"{task}。{AUTO_SCREENSHOT_STOP_RULE}"


def _requires_popup_close_flow(task: str) -> bool:
    return bool(task) and "截图" in task and any(marker in task for marker in POPUP_CLOSE_MARKERS)


def _screenshots_are_near_duplicate(left_path: str, right_path: str) -> bool:
    try:
        with Image.open(left_path) as left, Image.open(right_path) as right:
            left_small = ImageOps.grayscale(left).resize((16, 16), Image.Resampling.LANCZOS)
            right_small = ImageOps.grayscale(right).resize((16, 16), Image.Resampling.LANCZOS)
            left_pixels = tuple(int(p) for p in left_small.getdata())
            right_pixels = tuple(int(p) for p in right_small.getdata())
    except (FileNotFoundError, UnidentifiedImageError, OSError):
        return False

    avg_delta = sum(abs(a - b) for a, b in zip(left_pixels, right_pixels)) / len(left_pixels)
    return avg_delta <= 6.0


class PopupFlowStateMachine:
    """Track popup-close tasks without trusting AutoGLM's early finish blindly."""

    def __init__(self, task: str):
        self.enabled = _requires_popup_close_flow(task)
        self.close_failures = 0
        self.closed_after_prompt = False
        self._last_screenshot_path = None
        self._pending_close_check = False

    def should_accept_finish(self) -> bool:
        if not self.enabled:
            return True
        return self.closed_after_prompt

    def expect_close_result(self) -> None:
        if self.enabled:
            self._pending_close_check = True

    def record_close_attempt(self, changed: bool) -> None:
        if not self.enabled:
            return
        if changed:
            self.close_failures = 0
            self.closed_after_prompt = True
        else:
            self.close_failures += 1

    def record_screenshot(self, screenshot_path: str | None) -> None:
        if not self.enabled or not screenshot_path:
            return
        previous_path = self._last_screenshot_path
        self._last_screenshot_path = screenshot_path
        if not previous_path or not self._pending_close_check:
            return

        changed = not _screenshots_are_near_duplicate(previous_path, screenshot_path)
        self._pending_close_check = False
        self.record_close_attempt(changed=changed)

    def next_instruction(self, finished: bool = False) -> str | None:
        if not self.enabled or self.closed_after_prompt:
            return None
        if self.close_failures > 0:
            return POPUP_BACK_TASK
        if finished:
            return POPUP_CONTINUE_TASK
        return None


class SequentialGoalFinishGuard:
    def __init__(self, task: str):
        self.goals = self._parse_goal_labels(task)
        self.enabled = len(self.goals) >= 2
        self.has_page_transition = False

    @staticmethod
    def _parse_goal_labels(task: str) -> list[str]:
        labels = []
        for match in re.finditer(r"(?:^|[：:；;。])\s*\d+[.．、]\s*([^；;。（(]+)", task or ""):
            label = match.group(1).strip()
            if label:
                labels.append(label)
        return labels

    def record_action(self, action: dict | None) -> None:
        if not isinstance(action, dict) or action.get("_metadata") != "do":
            return
        if action.get("action") in PAGE_TRANSITION_ACTIONS:
            self.has_page_transition = True

    def should_accept_finish(self) -> bool:
        return not self.enabled or self.has_page_transition

    def next_instruction(self, finished: bool = False) -> str | None:
        if not self.enabled or not finished or self.should_accept_finish():
            return None
        first_goal = self.goals[0]
        second_goal = self.goals[1]
        return (
            "继续执行：多目标截图任务尚未按顺序完成。"
            f"第1个目标页面：{first_goal}；第2个目标页面：{second_goal}。"
            "当前页面只满足后续目标时，不算完成前序目标。"
            "请先回到或打开第1个目标页面并停留确认，然后再进入第2个目标页面；"
            "到达最后一个目标页面后再结束任务。"
        )


def _save_screenshot_from_agent(
    agent,
    step_idx: int,
    output_dir: str,
    source_app: str = "taobao",
    task_id: str = None,
    task_run_id: str = None,
    db_device_id: str = None,
):
    """
    从 agent 上下文中提取最近一步的截图，保存到本地并上传 OSS 入库。

    AutoGLM agent 的上下文中保存了每一步的截图（base64），
    我们从最后一条 user message 中提取图片数据。
    """
    try:
        # 遍历上下文找到最近的 user message 中的图片
        for msg in reversed(agent.context):
            if msg.get("role") == "user":
                content = msg.get("content", [])
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict) and part.get("type") == "image_url":
                            image_url = part.get("image_url", {}).get("url", "")
                            if image_url.startswith("data:image"):
                                # 提取 base64 数据
                                b64_data = image_url.split(",", 1)[1]
                                return _process_screenshot_bytes(
                                    b64_data, step_idx, output_dir, source_app, task_id, task_run_id, db_device_id
                                )
                break

        # 如果上下文中没有图片（被 remove_images_from_message 移除了），
        # 则直接从设备截图
        return _capture_and_save(step_idx, output_dir, source_app, agent.agent_config.device_id, task_id, task_run_id, db_device_id)

    except Exception as e:
        print(f"  ⚠️ 截图保存失败: {e}")
        return None


def _capture_and_save(
    step_idx: int | str,
    output_dir: str,
    source_app: str,
    device_id: str = None,
    task_id: str = None,
    task_run_id: str = None,
    db_device_id: str = None,
):
    """通过 ADB 直接从设备截图并保存"""
    try:
        import subprocess
        temp_path = os.path.join(output_dir, f"_temp_step_{step_idx}.png")
        adb_prefix = ["adb"]
        if device_id:
            adb_prefix = ["adb", "-s", device_id]

        # 截图到设备
        subprocess.run(adb_prefix + ["shell", "screencap", "-p", "/sdcard/autoglm_step.png"],
                       capture_output=True, timeout=10)
        # 拉取到本地
        subprocess.run(adb_prefix + ["pull", "/sdcard/autoglm_step.png", temp_path],
                       capture_output=True, timeout=10)
        # 清理设备上的临时文件
        subprocess.run(adb_prefix + ["shell", "rm", "/sdcard/autoglm_step.png"],
                       capture_output=True, timeout=5)

        if not os.path.exists(temp_path):
            print(f"  ⚠️ 截图文件不存在: {temp_path}")
            return None

        # 重命名为正式文件名
        timestamp = int(datetime.now().timestamp() * 1000)
        final_path = os.path.join(output_dir, f"autoglm_step_{step_idx}_{timestamp}.png")
        os.rename(temp_path, final_path)
        print(f"  📸 已保存截图: {final_path}")

        # 上传 OSS 并入库
        result = oss_uploader.upload(final_path, scenario_name="screenshot")
        if result.get("success"):
            print(f"  ☁️  OSS URL: {result['url']}")
            save_image_to_db(
                final_path,
                oss_url=result.get("url"),
                oss_key=result.get("key"),
                source_app=source_app,
                scenario="autoglm",
                task_id=task_id,
                task_run_id=task_run_id,
                device_id=db_device_id,
            )
        return final_path

    except Exception as e:
        print(f"  ⚠️ ADB 截图失败: {e}")
        return None


def _process_screenshot_bytes(
    b64_data: str,
    step_idx: int,
    output_dir: str,
    source_app: str,
    task_id: str = None,
    task_run_id: str = None,
    db_device_id: str = None,
):
    """将 base64 截图数据保存到本地文件并上传 OSS"""
    try:
        img_bytes = base64.b64decode(b64_data)

        timestamp = int(datetime.now().timestamp() * 1000)
        file_path = os.path.join(output_dir, f"autoglm_step_{step_idx}_{timestamp}.png")

        with open(file_path, "wb") as f:
            f.write(img_bytes)
        print(f"  📸 已保存截图: {file_path}")

        # 上传 OSS
        result = oss_uploader.upload(file_path, scenario_name="screenshot")
        if result.get("success"):
            print(f"  ☁️  OSS URL: {result['url']}")
            save_image_to_db(
                file_path,
                oss_url=result.get("url"),
                oss_key=result.get("key"),
                source_app=source_app,
                scenario="autoglm",
                task_id=task_id,
                task_run_id=task_run_id,
                device_id=db_device_id,
            )
        return file_path

    except Exception as e:
        print(f"  ⚠️ 截图处理失败: {e}")
        return None


def _should_capture_before_action(action: dict | None) -> bool:
    if not isinstance(action, dict):
        return False
    if action.get("_metadata") != "do":
        return False
    return action.get("action") == "Tap"


def _should_install_pre_action_capture(task: str) -> bool:
    return _requires_popup_close_flow(task)


def _should_save_step_screenshot(step_result) -> bool:
    return bool(getattr(step_result, "success", False)) and not bool(getattr(step_result, "finished", False))


def _resolve_app_package(app_name: str | None) -> str | None:
    app_name = (app_name or "").strip()
    if not app_name:
        return None
    return get_package_name(app_name)


def _adb_command(device_id: str | None, *args: str) -> list[str]:
    command = ["adb"]
    if device_id:
        command.extend(["-s", device_id])
    command.extend(args)
    return command


def _force_stop_app(app_name: str | None, device_id: str | None = None) -> bool:
    package_name = _resolve_app_package(app_name)
    if not package_name:
        print(f"  ⚠️ 未找到 App 包名，跳过退出: {app_name or 'unknown'}")
        return False
    try:
        result = subprocess.run(
            _adb_command(device_id, "shell", "am", "force-stop", package_name),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"  ⚠️ 退出应用失败: {app_name} ({package_name}): {exc}")
        return False
    if result.returncode != 0:
        error = (result.stderr or "").strip()
        print(f"  ⚠️ 退出应用失败: {app_name} ({package_name}): {error or result.returncode}")
        return False
    print(f"  🛑 已退出应用: {app_name} ({package_name})")
    return True


def _install_pre_action_screenshot_capture(
    agent,
    output_dir: str,
    source_app: str,
    task_id: str = None,
    task_run_id: str = None,
    db_device_id: str = None,
):
    original_execute = agent.action_handler.execute
    counter = {"value": 0}

    def execute_with_pre_action_capture(action, screen_width, screen_height):
        if _should_capture_before_action(action):
            step_idx = f"pre_action_{counter['value']}"
            counter["value"] += 1
            try:
                _capture_and_save(
                    step_idx,
                    output_dir,
                    source_app,
                    agent.agent_config.device_id,
                    task_id,
                    task_run_id,
                    db_device_id,
                )
            except Exception as e:
                print(f"  ⚠️ 预动作截图失败: {e}")
        return original_execute(action, screen_width, screen_height)

    agent.action_handler.execute = execute_with_pre_action_capture
    return execute_with_pre_action_capture


def run_with_autoglm(
    task: str,
    base_url: str = None,
    model: str = None,
    apikey: str = None,
    max_steps: int = 100,
    output_dir: str = None,
    capture_screenshots: bool = True,
    task_id: str = None,
    task_run_id: str = None,
    device_id: str = None,
    db_device_id: str = None,
    source_app: str = "taobao",
    exit_app_on_finish: bool = True,
):
    """
    使用 AutoGLM 执行自然语言任务，每一步自动截图并上传 OSS 入库

    Args:
        task: 自然语言任务描述，如"打开淘宝搜索智能手表并截图"
        base_url: 模型服务地址
        model: 模型名称
        apikey: API Key
        max_steps: 最大执行步数
        output_dir: 截图保存目录
        capture_screenshots: 是否每一步都截图保存
    """
    max_steps = max(1, min(max_steps, MAX_AUTOGLM_STEPS))

    # 设置设备类型为 ADB (Android)
    set_device_type(DeviceType.ADB)

    # 截图输出目录
    keyword = app_config.KEYWORD
    folder = task_id or keyword
    output_dir = output_dir or os.path.join(app_config.PROJECT_ROOT, "data", folder, "autoglm")
    os.makedirs(output_dir, exist_ok=True)

    # 模型配置
    model_config = ModelConfig(
        base_url=base_url or os.getenv("PHONE_AGENT_BASE_URL", "http://localhost:8000/v1"),
        model_name=model or os.getenv("PHONE_AGENT_MODEL", "autoglm-phone-9b"),
        api_key=apikey or os.getenv("PHONE_AGENT_API_KEY", "EMPTY"),
    )

    # Agent 配置
    agent_config = AgentConfig(
        max_steps=max_steps,
        device_id=device_id or os.getenv("PHONE_AGENT_DEVICE_ID", None),
        lang="cn",
        verbose=True,
    )

    # 创建 Agent
    agent = PhoneAgent(
        model_config=model_config,
        agent_config=agent_config,
    )
    if capture_screenshots and _should_install_pre_action_capture(task):
        _install_pre_action_screenshot_capture(
            agent,
            output_dir,
            source_app,
            task_id,
            task_run_id,
            db_device_id,
        )

    task = _append_auto_screenshot_stop_rule(task)

    print(f"🚀 任务: {task}")
    print(f"📁 截图目录: {output_dir}")
    if agent_config.device_id:
        print(f"📱 设备: {agent_config.device_id}")
    print(f"🔢 最大步数: {max_steps}")
    print("-" * 50)

    # 使用 step() 逐步执行，每步截图
    popup_flow = PopupFlowStateMachine(task)
    goal_finish_guard = SequentialGoalFinishGuard(task)
    step_result = agent.step(task=task)
    step_idx = 0

    if capture_screenshots and _should_save_step_screenshot(step_result):
        screenshot_path = _save_screenshot_from_agent(
            agent,
            step_idx,
            output_dir,
            source_app=source_app,
            task_id=task_id,
            task_run_id=task_run_id,
            db_device_id=db_device_id,
        )
        popup_flow.record_screenshot(screenshot_path)
    step_idx += 1
    goal_finish_guard.record_action(step_result.action)

    # 继续执行直到完成
    while step_idx < max_steps:
        if step_result.finished and popup_flow.should_accept_finish() and goal_finish_guard.should_accept_finish():
            break

        instruction = popup_flow.next_instruction(finished=step_result.finished)
        if not instruction:
            instruction = goal_finish_guard.next_instruction(finished=step_result.finished)
        if instruction:
            print("⚠️ AutoGLM 流程未闭环，按状态机继续执行")
            if instruction in (POPUP_CONTINUE_TASK, POPUP_BACK_TASK):
                popup_flow.expect_close_result()
            step_result = agent.step(task=instruction)
        elif step_result.finished:
            break
        else:
            step_result = agent.step()

        if capture_screenshots and _should_save_step_screenshot(step_result):
            screenshot_path = _save_screenshot_from_agent(
                agent,
                step_idx,
                output_dir,
                source_app=source_app,
                task_id=task_id,
                task_run_id=task_run_id,
                db_device_id=db_device_id,
            )
            popup_flow.record_screenshot(screenshot_path)
        step_idx += 1
        goal_finish_guard.record_action(step_result.action)

    print("-" * 50)
    print(f"✅ 任务完成: {step_result.message or 'done'}")
    print(f"📸 共截图 {step_idx} 张，保存在: {output_dir}")
    if exit_app_on_finish:
        _force_stop_app(source_app, agent_config.device_id)
    return step_result.message or "done"


def main():
    parser = argparse.ArgumentParser(description="使用 AutoGLM 驱动手机完成淘宝截图任务")
    parser.add_argument("task", nargs="?", default="打开淘宝搜索智能手表并截图",
                        help="自然语言任务描述 (默认: 打开淘宝搜索智能手表并截图)")
    parser.add_argument("--base-url", default=None, help="模型服务地址")
    parser.add_argument("--model", default=None, help="模型名称")
    parser.add_argument("--apikey", default=None, help="API Key")
    parser.add_argument("--max-steps", type=int, default=MAX_AUTOGLM_STEPS, help="最大执行步数，上限10")
    parser.add_argument("--output-dir", default=None, help="截图保存目录")
    parser.add_argument("--task-id", default=None, help="关联后台任务 ID")
    parser.add_argument("--task-run-id", default=None, help="关联后台任务运行 ID")
    parser.add_argument("--device-id", default=None, help="ADB 设备序列号")
    parser.add_argument("--db-device-id", default=None, help="后台设备记录 ID")
    parser.add_argument("--source-app", default="taobao", help="截图入库时记录的来源 App")
    parser.add_argument("--no-capture", action="store_true", help="不自动截图（仅执行任务）")
    parser.add_argument("--no-exit-app", action="store_true", help="任务完成后不退出当前执行 App")
    parser.add_argument("--check", action="store_true", help="检查系统要求")

    args = parser.parse_args()

    if args.check:
        from main import check_system_requirements

        ok = check_system_requirements(DeviceType.ADB)
        sys.exit(0 if ok else 1)
        return

    # 检查必要的环境变量
    base_url = args.base_url or os.getenv("PHONE_AGENT_BASE_URL")
    if not base_url:
        print("❌ 错误: 未设置模型服务地址")
        print("请通过以下方式之一设置:")
        print("  1. 环境变量: export PHONE_AGENT_BASE_URL=你的模型服务地址")
        print("  2. 命令行参数: --base-url 你的模型服务地址")
        print()
        print("可用的第三方模型服务:")
        print("  - 智谱 BigModel: https://open.bigmodel.cn/api/paas/v4 (模型: autoglm-phone)")
        print("  - ModelScope: https://api-inference.modelscope.cn/v1 (模型: ZhipuAI/AutoGLM-Phone-9B)")
        print("  - 本地部署: http://localhost:8000/v1 (模型: autoglm-phone-9b)")
        sys.exit(1)

    run_with_autoglm(
        task=args.task,
        base_url=args.base_url,
        model=args.model,
        apikey=args.apikey,
        max_steps=args.max_steps,
        output_dir=args.output_dir,
        capture_screenshots=not args.no_capture,
        task_id=args.task_id,
        task_run_id=args.task_run_id,
        device_id=args.device_id,
        db_device_id=args.db_device_id,
        source_app=args.source_app,
        exit_app_on_finish=not args.no_exit_app,
    )


if __name__ == "__main__":
    main()
