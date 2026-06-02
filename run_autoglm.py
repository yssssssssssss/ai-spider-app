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
from phone_agent.model import ModelConfig
from phone_agent.device_factory import DeviceType, set_device_type

import config as app_config

from app.services.oss_uploader import oss_uploader
from app.scripts_common import save_image_to_db


POPUP_CLOSE_MARKERS = ("弹窗", "浮层", "广告", "关闭", "关闭后", "跳过")
POPUP_CONTINUE_TASK = (
    "继续执行：你还没有完成弹窗关闭后的页面截图。"
    "如果当前仍有弹窗、广告或浮层，请先点击关闭、跳过、取消或返回关闭它；"
    "弹窗消失后停留在目标页面，等待截图保存，然后再结束任务。"
)
POPUP_BACK_TASK = (
    "继续执行：当前界面关闭弹窗后没有明显变化。"
    "请优先使用返回键关闭弹窗、广告或浮层；如果返回键无效，再点击可见的关闭、跳过或取消按钮。"
    "关闭后停留在目标页面等待截图保存，不要提前结束。"
)
AUTO_SCREENSHOT_STOP_RULE = (
    "执行约束：平台会在每一步自动截图并保存到本地和后台；"
    "你不需要、也禁止打开系统设置、相册、文件管理、截图工具或其他非目标应用来保存截图。"
    "到达用户要求的目标页面并停留完成自动截图后，必须立即结束任务；"
    "不要返回桌面，不要继续点击、长按、滑动或探索无关页面。"
)
MAX_AUTOGLM_STEPS = 10


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
    step_idx: int,
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

    task = _append_auto_screenshot_stop_rule(task)

    print(f"🚀 任务: {task}")
    print(f"📁 截图目录: {output_dir}")
    if agent_config.device_id:
        print(f"📱 设备: {agent_config.device_id}")
    print(f"🔢 最大步数: {max_steps}")
    print("-" * 50)

    # 使用 step() 逐步执行，每步截图
    popup_flow = PopupFlowStateMachine(task)
    step_result = agent.step(task=task)
    step_idx = 0

    if capture_screenshots and step_result.success:
        screenshot_path = _save_screenshot_from_agent(
            agent,
            step_idx,
            output_dir,
            task_id=task_id,
            task_run_id=task_run_id,
            db_device_id=db_device_id,
        )
        popup_flow.record_screenshot(screenshot_path)
    step_idx += 1

    # 继续执行直到完成
    while step_idx < max_steps:
        if step_result.finished and popup_flow.should_accept_finish():
            break

        instruction = popup_flow.next_instruction(finished=step_result.finished)
        if instruction:
            print("⚠️ AutoGLM 弹窗流程未闭环，按状态机继续执行")
            popup_flow.expect_close_result()
            step_result = agent.step(task=instruction)
        elif step_result.finished:
            break
        else:
            step_result = agent.step()

        if capture_screenshots and step_result.success:
            screenshot_path = _save_screenshot_from_agent(
                agent,
                step_idx,
                output_dir,
                task_id=task_id,
                task_run_id=task_run_id,
                db_device_id=db_device_id,
            )
            popup_flow.record_screenshot(screenshot_path)
        step_idx += 1

    print("-" * 50)
    print(f"✅ 任务完成: {step_result.message or 'done'}")
    print(f"📸 共截图 {step_idx} 张，保存在: {output_dir}")
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
    parser.add_argument("--no-capture", action="store_true", help="不自动截图（仅执行任务）")
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
    )


if __name__ == "__main__":
    main()
