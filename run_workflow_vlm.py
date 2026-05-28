"""
VLM 视觉驱动工作流任务编排
- 使用 VLM (AutoGLM 模型) 进行视觉识别和点击控制
- 使用 uiautomator2 执行稳定的滑动/截图/等待
"""
import os
import time
import sys
import shutil
from datetime import datetime
from typing import List, Dict, Callable, Optional
from dataclasses import dataclass, field

# 将 Open-AutoGLM 加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Open-AutoGLM"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from app.services.oss_uploader import oss_uploader

from phone_agent.model import ModelConfig, ModelClient
from phone_agent.model.client import MessageBuilder
from phone_agent.actions.handler import ActionHandler, parse_action
from phone_agent.config import get_system_prompt
from phone_agent.adb.screenshot import get_screenshot

import config as app_config


@dataclass
class WorkflowStep:
    """工作流步骤定义"""
    name: str
    action: str  # open_app, click, wait, screenshot, scroll, close_app
    app: str = ""
    package: str = ""
    activity: str = ""
    target_text: str = ""
    target_desc: str = ""
    duration: int = 0
    interval: int = 0
    scroll_count: int = 0
    scroll_direction: str = "up"
    output_dir: str = ""


@dataclass
class WorkflowConfig:
    """工作流配置"""
    name: str
    steps: List[WorkflowStep] = field(default_factory=list)
    popup_handler: bool = True
    popup_cooldown: int = 3  # 弹窗处理冷却时间（秒）
    dedup: bool = True
    dedup_threshold: float = 0.9
    scroll_wait: float = 2.0  # 滑动后等待时间（秒）
    click_wait: float = 2.0   # 点击后等待时间（秒）
    app_start_wait: float = 3.0  # App 启动后等待时间（秒）


class VLMController:
    """
    VLM 视觉控制器
    复用 AutoGLM 的 ModelClient + ActionHandler 实现视觉识别点击
    """

    def __init__(self, model_config: ModelConfig, device_id: str = None, popup_cooldown: int = 3):
        self.model_config = model_config
        self.client = ModelClient(model_config)
        self.action_handler = ActionHandler(device_id=device_id)
        self.device_id = device_id
        self.system_prompt = get_system_prompt("cn")
        # 弹窗防重复处理机制
        self.popup_cooldown = popup_cooldown  # 弹窗处理冷却时间（秒）
        self._last_popup_time = 0            # 上次处理弹窗的时间戳
        self._popup_hashes = set()           # 已处理弹窗的截图哈希集合
        self._popup_hash_threshold = 0.85    # 弹窗重复判定阈值（略低于截图去重阈值，确保准确匹配）

    def _get_image_hash(self, image_path: str) -> Optional[str]:
        """计算图片的简化哈希，用于弹窗重复检测"""
        try:
            from PIL import Image
            import numpy as np
            import cv2

            img = Image.open(image_path)
            img = img.convert("L")
            img = img.resize((32, 32), Image.LANCZOS)
            arr = np.array(img, dtype=np.float32)
            dct = cv2.dct(arr)
            dct_low = dct[:8, :8]
            avg = (dct_low.sum() - dct_low[0, 0]) / 63.0
            hash_bits = ""
            for i in range(8):
                for j in range(8):
                    if i == 0 and j == 0:
                        continue
                    hash_bits += "1" if dct_low[i, j] > avg else "0"
            return hash_bits
        except Exception:
            return None

    def _hamming_distance(self, hash1: str, hash2: str) -> int:
        """计算汉明距离"""
        return sum(c1 != c2 for c1, c2 in zip(hash1, hash2))

    def _is_duplicate_popup(self, screenshot_path: str) -> bool:
        """检查当前截图是否与最近处理过的弹窗重复"""
        h = self._get_image_hash(screenshot_path)
        if h is None:
            return False
        for existing_hash in self._popup_hashes:
            dist = self._hamming_distance(h, existing_hash)
            similarity = 1 - dist / len(h)
            if similarity >= self._popup_hash_threshold:
                return True
        self._popup_hashes.add(h)
        return False

    def _capture_and_act(self, prompt: str, max_steps: int = 1) -> bool:
        """
        通用方法：截图 → 发送给 VLM → 执行返回的动作
        """
        screenshot = get_screenshot(self.device_id)

        messages = [
            MessageBuilder.create_system_message(self.system_prompt),
            MessageBuilder.create_user_message(
                text=prompt,
                image_base64=screenshot.base64_data,
            ),
        ]

        try:
            print(f"  🤖 [VLM] 推理中...")
            response = self.client.request(messages)
            action = parse_action(response.action)
            result = self.action_handler.execute(
                action, screenshot.width, screenshot.height
            )
            if result.success:
                print(f"  ✅ [VLM] 动作执行成功")
            else:
                print(f"  ❌ [VLM] 动作执行失败: {result.message}")
            return result.success
        except Exception as e:
            print(f"  ❌ [VLM] 错误: {e}")
            return False

    def click_element(self, target_text: str) -> bool:
        """VLM 视觉识别并点击元素"""
        print(f"  🤖 [VLM] 识别并点击: 「{target_text}」")
        prompt = f"当前任务：请点击截图中的「{target_text}」按钮或入口。"
        return self._capture_and_act(prompt)

    def detect_and_close_popup(self) -> bool:
        """VLM 视觉识别并关闭弹窗，带冷却和去重机制"""
        # 冷却期检查：如果距离上次处理弹窗时间太短，跳过检测
        now = time.time()
        if now - self._last_popup_time < self.popup_cooldown:
            return False

        print(f"  🤖 [VLM] 检测弹窗...")

        # 先保存临时截图用于弹窗去重判断
        screenshot = get_screenshot(self.device_id)
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        # 将 base64 数据写入临时文件
        import base64
        with open(tmp_path, "wb") as f:
            f.write(base64.b64decode(screenshot.base64_data))

        # 检查是否是与之前处理过的相同弹窗
        if self._is_duplicate_popup(tmp_path):
            print(f"  ⏭️ [VLM] 该弹窗已处理过，跳过")
            os.remove(tmp_path)
            self._last_popup_time = now
            return False

        os.remove(tmp_path)

        prompt = (
            "当前任务：检查截图中是否有弹窗、广告、权限请求等干扰界面。"
            "如果有，请点击关闭按钮、跳过按钮或取消按钮。"
            "如果没有弹窗，请直接返回 finish(message='无弹窗')。"
        )
        messages = [
            MessageBuilder.create_system_message(self.system_prompt),
            MessageBuilder.create_user_message(
                text=prompt,
                image_base64=screenshot.base64_data,
            ),
        ]
        try:
            response = self.client.request(messages)
            action = parse_action(response.action)
            if action.get("_metadata") == "finish":
                print(f"  ✅ [VLM] 无弹窗")
                return False
            result = self.action_handler.execute(
                action, screenshot.width, screenshot.height
            )
            if result.success:
                print(f"  ✅ [VLM] 弹窗已关闭，等待 {self.popup_cooldown}s 冷却...")
                self._last_popup_time = time.time()
                time.sleep(self.popup_cooldown)
                return True
            else:
                print(f"  ❌ [VLM] 关闭弹窗失败: {result.message}")
                return False
        except Exception as e:
            print(f"  ❌ [VLM] 弹窗检测错误: {e}")
            return False


class ScreenshotDeduplicator:
    """截图去重器 - 使用感知哈希"""

    def __init__(self, threshold: float = 0.9):
        self.threshold = threshold
        self.hashes = {}

    def _phash(self, image_path: str) -> Optional[str]:
        try:
            from PIL import Image
            import numpy as np
            import cv2

            img = Image.open(image_path)
            img = img.convert("L")
            img = img.resize((32, 32), Image.LANCZOS)
            arr = np.array(img, dtype=np.float32)
            dct = cv2.dct(arr)
            dct_low = dct[:8, :8]
            avg = (dct_low.sum() - dct_low[0, 0]) / 63.0
            hash_bits = ""
            for i in range(8):
                for j in range(8):
                    if i == 0 and j == 0:
                        continue
                    hash_bits += "1" if dct_low[i, j] > avg else "0"
            return hash_bits
        except Exception as e:
            print(f"  [去重] 计算hash失败: {e}")
            return None

    def _hamming_distance(self, hash1: str, hash2: str) -> int:
        return sum(c1 != c2 for c1, c2 in zip(hash1, hash2))

    def is_duplicate(self, image_path: str) -> bool:
        h = self._phash(image_path)
        if h is None:
            return False
        for existing_path, existing_hash in self.hashes.items():
            dist = self._hamming_distance(h, existing_hash)
            similarity = 1 - dist / len(h)
            if similarity >= self.threshold:
                print(f"  [去重] 重复: {os.path.basename(image_path)} ~ {os.path.basename(existing_path)} ({similarity:.2%})")
                return True
        self.hashes[image_path] = h
        return False


class WorkflowEngine:
    """VLM + uiautomator2 混合工作流执行引擎"""

    def __init__(self, config: WorkflowConfig, model_config: ModelConfig = None):
        self.config = config
        self.model_config = model_config
        self.d = None
        self.vlm = None
        self.dedup = ScreenshotDeduplicator(threshold=config.dedup_threshold) if config.dedup else None
        self.screenshot_count = 0

    def _get_device(self):
        if self.d is None:
            import uiautomator2 as u2
            self.d = u2.connect()
            print(f"✅ 设备已连接: {self.d.device_info['serial']}")
            # 初始化 VLM 控制器，传入弹窗冷却时间
            if self.model_config:
                self.vlm = VLMController(
                    self.model_config,
                    device_id=None,
                    popup_cooldown=getattr(self.config, 'popup_cooldown', 3)
                )
                print(f"🧠 VLM 已初始化: {self.model_config.model_name}")
        return self.d

    def _screenshot(self, output_dir: str, prefix: str = "screenshot") -> dict:
        timestamp = datetime.now().strftime("%H%M%S_%f")[:-3]
        filename = f"{prefix}_{timestamp}.png"
        filepath = os.path.join(output_dir, filename)
        self.d.screenshot(filepath)
        if self.dedup and self.dedup.is_duplicate(filepath):
            os.remove(filepath)
            print(f"  📸 [去重] 删除重复: {filename}")
            return {"local_path": "", "oss_url": "", "oss_key": ""}
        print(f"  📸 已保存: {filename}")
        self.screenshot_count += 1

        # 上传到京东云 OSS
        result = oss_uploader.upload(filepath, scenario_name="screenshot")
        if result.get("success"):
            print(f"  ☁️  OSS URL: {result['url']}")
        else:
            print(f"  ⚠️ OSS 上传失败: {result.get('error')}")

        return {
            "local_path": filepath,
            "oss_url": result.get("url", ""),
            "oss_key": result.get("key", ""),
        }

    def _handle_popups(self):
        if self.config.popup_handler and self.vlm:
            return self.vlm.detect_and_close_popup()
        return False

    def _open_app(self, step: WorkflowStep) -> str:
        d = self._get_device()
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        app_folder = f"{step.app}_{now}"
        output_dir = os.path.join(os.path.dirname(__file__), "data", "workflow_vlm", app_folder)
        os.makedirs(output_dir, exist_ok=True)
        print(f"📁 输出目录: {output_dir}")

        print(f"🚀 打开应用: {step.app} ({step.package})")
        if step.activity:
            d.app_start(step.package, step.activity)
        else:
            d.app_start(step.package)
        time.sleep(self.config.app_start_wait)
        self._handle_popups()
        time.sleep(2)
        return output_dir

    def _click(self, step: WorkflowStep):
        d = self._get_device()
        if self.vlm and step.target_text:
            success = self.vlm.click_element(step.target_text)
            if success:
                time.sleep(self.config.click_wait)
                self._handle_popups()
                return
        # VLM 失败或没有 target_text，回退到规则
        print(f"👉 回退到规则点击: text='{step.target_text}'")
        clicked = False
        if step.target_text:
            try:
                elem = d(text=step.target_text)
                if elem.exists:
                    elem.click()
                    clicked = True
            except Exception:
                pass
        if not clicked and step.target_desc:
            try:
                elem = d(description=step.target_desc)
                if elem.exists:
                    elem.click()
                    clicked = True
            except Exception:
                pass
        if not clicked:
            print(f"  ⚠️ 未找到点击目标")
        time.sleep(self.config.click_wait)
        self._handle_popups()

    def _wait_and_screenshot(self, step: WorkflowStep, output_dir: str):
        print(f"⏳ 等待 {step.duration} 秒，每 {step.interval} 秒截图一次")
        elapsed = 0
        while elapsed < step.duration:
            self._screenshot(output_dir, prefix=step.app)
            time.sleep(step.interval)
            elapsed += step.interval
            self._handle_popups()

    def _scroll_and_screenshot(self, step: WorkflowStep, output_dir: str):
        d = self._get_device()
        w, h = d.window_size()
        center_x = int(w * 0.5)
        start_y = h - 100
        end_y = start_y - int(h * 0.8)

        print(f"📜 滑动 {step.scroll_count} 次并截图")
        for i in range(step.scroll_count):
            print(f"  滑动 {i+1}/{step.scroll_count}")
            d.swipe(center_x, start_y, center_x, end_y, duration=0.5)
            time.sleep(self.config.scroll_wait)
            self._screenshot(output_dir, prefix=step.app)
            self._handle_popups()

    def _close_app(self, step: WorkflowStep):
        d = self._get_device()
        print(f"🛑 关闭应用: {step.app} ({step.package})")
        d.app_stop(step.package)
        time.sleep(1)

    def run(self):
        print("=" * 60)
        print(f"🎬 VLM 工作流: {self.config.name}")
        print("=" * 60)

        current_output_dir = ""
        for i, step in enumerate(self.config.steps):
            print(f"\n--- 步骤 {i+1}/{len(self.config.steps)}: {step.name} ---")
            self._handle_popups()

            if step.action == "open_app":
                current_output_dir = self._open_app(step)
            elif step.action == "click":
                self._click(step)
            elif step.action == "wait":
                self._wait_and_screenshot(step, current_output_dir)
            elif step.action == "scroll":
                self._scroll_and_screenshot(step, current_output_dir)
            elif step.action == "close_app":
                self._close_app(step)
            else:
                print(f"⚠️ 未知动作: {step.action}")

        print("\n" + "=" * 60)
        print(f"🎉 工作流完成! 共截图 {self.screenshot_count} 张")
        print("=" * 60)


def build_example_workflow() -> WorkflowConfig:
    """
    构建示例工作流：
    - 第一步打开taobao，点击"百亿补贴"按钮
    - 第二步在首页等候20秒，并间隔2秒截一次图
    - 第三步向下滑动一屏页面，截图一次，再滑动一屏页面，再截图一次
    - 第四步关闭taobao，打开拼多多，点击"限时秒杀"按钮
    - 第五步在首页等候12秒，并间隔2秒截一次图
    - 第六步向下滑动一屏页面，截图一次，再滑动一屏页面，再截图一次
    - 退出拼多多
    """
    return WorkflowConfig(
        name="淘宝+拼多多 VLM 视觉驱动截图工作流",
        steps=[
            WorkflowStep(name="打开淘宝", action="open_app", app="taobao", package="com.taobao.taobao"),
            WorkflowStep(name="点击百亿补贴", action="click", app="taobao", target_text="百亿补贴"),
            WorkflowStep(name="等待截图(淘宝)", action="wait", app="taobao", duration=20, interval=2),
            WorkflowStep(name="滑动截图(淘宝)", action="scroll", app="taobao", scroll_count=2),

            WorkflowStep(name="关闭淘宝", action="close_app", app="taobao", package="com.taobao.taobao"),
            WorkflowStep(name="打开拼多多", action="open_app", app="pdd", package="com.xunmeng.pinduoduo"),
            WorkflowStep(name="点击限时秒杀", action="click", app="pdd", target_text="限时秒杀"),
            WorkflowStep(name="等待截图(拼多多)", action="wait", app="pdd", duration=12, interval=2),
            WorkflowStep(name="滑动截图(拼多多)", action="scroll", app="pdd", scroll_count=2),
            WorkflowStep(name="退出拼多多", action="close_app", app="pdd", package="com.xunmeng.pinduoduo"),
        ],
        popup_handler=True,
        dedup=True,
    )


def main():
    import argparse
    parser = argparse.ArgumentParser(description="VLM 视觉驱动工作流")
    parser.add_argument("--base-url", default=None, help="模型服务地址")
    parser.add_argument("--model", default=None, help="模型名称")
    parser.add_argument("--apikey", default=None, help="API Key")
    parser.add_argument("--dedup-threshold", type=float, default=0.9, help="去重阈值(0-1)")
    parser.add_argument("--popup-cooldown", type=int, default=3, help="弹窗处理冷却时间(秒)")
    parser.add_argument("--app-start-wait", type=float, default=3.0, help="App启动后等待时间(秒)")
    parser.add_argument("--click-wait", type=float, default=2.0, help="点击后等待时间(秒)")
    parser.add_argument("--scroll-wait", type=float, default=2.0, help="滑动后等待时间(秒)")
    parser.add_argument("--no-dedup", action="store_true", help="禁用去重")
    parser.add_argument("--no-popup", action="store_true", help="禁用弹窗处理")
    args = parser.parse_args()

    base_url = args.base_url or os.getenv("PHONE_AGENT_BASE_URL")
    model = args.model or os.getenv("PHONE_AGENT_MODEL", "autoglm-phone-9b")
    apikey = args.apikey or os.getenv("PHONE_AGENT_API_KEY", "EMPTY")

    if not base_url:
        print("❌ 错误: 未设置模型服务地址")
        print("请设置环境变量 PHONE_AGENT_BASE_URL 或使用 --base-url")
        sys.exit(1)

    model_config = ModelConfig(
        base_url=base_url,
        model_name=model,
        api_key=apikey,
    )

    workflow = build_example_workflow()
    if args.no_dedup:
        workflow.dedup = False
    if args.no_popup:
        workflow.popup_handler = False
    workflow.dedup_threshold = args.dedup_threshold
    workflow.popup_cooldown = args.popup_cooldown
    workflow.app_start_wait = args.app_start_wait
    workflow.click_wait = args.click_wait
    workflow.scroll_wait = args.scroll_wait

    engine = WorkflowEngine(workflow, model_config=model_config)
    engine.run()


if __name__ == "__main__":
    main()
