"""
工作流任务编排与弹窗处理模块
"""
import os
import time
import sys
import shutil
from datetime import datetime
from typing import List, Dict, Callable, Optional
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Open-AutoGLM"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from app.scripts_common import is_local_file_sink


JD_APP_PACKAGE = "com.jingdong.app.mall"
DEFAULT_APP_LOAD_SECONDS = 6
DEFAULT_AFTER_CLICK_SECONDS = 4
DEFAULT_SCREENSHOT_SETTLE_SECONDS = 2


@dataclass
class WorkflowStep:
    """工作流步骤定义"""
    name: str                           # 步骤名称
    action: str                         # 动作类型: open_app, click, wait, screenshot, scroll, close_app
    app: str = ""                       # App名称
    package: str = ""                   # App包名
    activity: str = ""                  # App Activity
    target_text: str = ""               # 点击目标文本
    target_desc: str = ""               # 点击目标desc
    duration: int = 0                   # 等待时长(秒)
    interval: int = 0                   # 截图间隔(秒)
    scroll_count: int = 0               # 滑动次数
    scroll_direction: str = "up"        # 滑动方向: up/down
    output_dir: str = ""                # 输出目录(覆盖默认)
    required: bool = False              # 未完成该步骤是否失败


@dataclass
class WorkflowConfig:
    """工作流配置"""
    name: str                           # 工作流名称
    steps: List[WorkflowStep] = field(default_factory=list)
    popup_handler: bool = True          # 是否启用弹窗处理
    dedup: bool = True                  # 是否启用去重
    dedup_threshold: float = 0.9        # 去重相似度阈值


class PopupHandler:
    """弹窗自动检测与关闭处理器"""

    # 常见的关闭按钮文本和描述
    CLOSE_TEXTS = ["关闭", "取消", "我知道了", "不再提示", "跳过", "以后再说", "暂不", "拒绝", "不同意", "X", "×"]
    CLOSE_IDS = ["close", "cancel", "dismiss", "skip", "exit", "back", "btn_close", "iv_close", "img_close"]

    def __init__(self, d):
        self.d = d  # uiautomator2 device

    def detect_and_close(self, max_attempts: int = 3) -> bool:
        """
        检测并关闭弹窗
        返回: 是否检测到并关闭了弹窗
        """
        closed = False
        for attempt in range(max_attempts):
            popup_closed = self._try_close_popup()
            if popup_closed:
                closed = True
                time.sleep(0.5)
            else:
                break
        return closed

    def _try_close_popup(self) -> bool:
        """尝试通过UI树查找关闭按钮"""
        try:
            # 方法1: 通过文本查找
            for text in self.CLOSE_TEXTS:
                try:
                    elem = self.d(text=text)
                    if elem.exists:
                        print(f"  [弹窗] 检测到关闭按钮(文本): '{text}'")
                        elem.click()
                        return True
                except Exception:
                    continue

            # 方法2: 通过desc查找
            for desc in self.CLOSE_TEXTS:
                try:
                    elem = self.d(description=desc)
                    if elem.exists:
                        print(f"  [弹窗] 检测到关闭按钮(desc): '{desc}'")
                        elem.click()
                        return True
                except Exception:
                    continue

            # 方法3: 通过常见resourceId查找
            for rid in self.CLOSE_IDS:
                try:
                    elem = self.d(resourceIdMatches=f".*{rid}.*")
                    if elem.exists:
                        print(f"  [弹窗] 检测到关闭按钮(id): '{rid}'")
                        elem.click()
                        return True
                except Exception:
                    continue

            return False
        except Exception as e:
            print(f"  [弹窗] 检测异常: {e}")
            return False


class ScreenshotDeduplicator:
    """截图去重器 - 使用感知哈希"""

    def __init__(self, threshold: float = 0.9):
        self.threshold = threshold
        self.hashes = {}  # path -> hash

    def _phash(self, image_path: str) -> Optional[str]:
        """计算图片的感知哈希"""
        try:
            from PIL import Image
            import numpy as np

            img = Image.open(image_path)
            img = img.convert("L")  # 转为灰度
            img = img.resize((32, 32), Image.LANCZOS)
            arr = np.array(img, dtype=np.float32)

            # DCT变换
            import cv2
            dct = cv2.dct(arr)
            dct_low = dct[:8, :8]

            # 计算平均值并生成hash
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
        """计算汉明距离"""
        return sum(c1 != c2 for c1, c2 in zip(hash1, hash2))

    def is_duplicate(self, image_path: str) -> bool:
        """检查图片是否与已有图片重复"""
        h = self._phash(image_path)
        if h is None:
            return False

        for existing_path, existing_hash in self.hashes.items():
            dist = self._hamming_distance(h, existing_hash)
            similarity = 1 - dist / len(h)
            if similarity >= self.threshold:
                print(f"  [去重] 检测到重复图片: {os.path.basename(image_path)} ~ {os.path.basename(existing_path)} (相似度: {similarity:.2%})")
                return True

        self.hashes[image_path] = h
        return False


class WorkflowEngine:
    """工作流执行引擎"""

    def __init__(self, config: WorkflowConfig):
        self.config = config
        self.d = None
        self.popup_handler = None
        self.dedup = ScreenshotDeduplicator(threshold=config.dedup_threshold) if config.dedup else None
        self.screenshot_count = 0
        self.device_id = os.getenv("PHONE_AGENT_DEVICE_ID") or None
        self.task_output_dir = os.getenv("TASK_OUTPUT_DIR") or None

    def _get_device(self):
        """获取或创建设备连接"""
        if self.d is None:
            import uiautomator2 as u2
            self.d = u2.connect(self.device_id) if self.device_id else u2.connect()
            self.popup_handler = PopupHandler(self.d)
            print(f"✅ 设备已连接: {self.d.device_info['serial']}")
        return self.d

    def _sleep(self, seconds: int, reason: str):
        if seconds <= 0:
            return
        print(f"⏳ {reason}: {seconds} 秒")
        time.sleep(seconds)

    def _screenshot(self, output_dir: str, prefix: str = "screenshot") -> dict:
        """截图并保存，支持去重和OSS上传
        返回: {"local_path": str, "oss_url": str, "oss_key": str}
        """
        timestamp = datetime.now().strftime("%H%M%S_%f")[:-3]
        filename = f"{prefix}_{timestamp}.png"
        filepath = os.path.join(output_dir, filename)

        self.d.screenshot(filepath)

        # 去重检查
        if self.dedup and self.dedup.is_duplicate(filepath):
            os.remove(filepath)
            print(f"  📸 [去重] 删除重复截图: {filename}")
            return {"local_path": "", "oss_url": "", "oss_key": ""}

        print(f"  📸 已保存: {filename}")
        self.screenshot_count += 1

        if is_local_file_sink():
            return {
                "local_path": filepath,
                "oss_url": "",
                "oss_key": "",
            }

        # 上传到京东云 OSS
        from app.services.oss_uploader import oss_uploader

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
        """处理弹窗"""
        if self.config.popup_handler and self.popup_handler:
            closed = self.popup_handler.detect_and_close()
            if closed:
                print("  ✅ 弹窗已处理")

    def _open_app(self, step: WorkflowStep) -> str:
        """打开App并返回输出目录"""
        d = self._get_device()

        # 构建输出目录: app名+时间
        now = datetime.now().strftime("%Y%m%d_%H%M%S")
        app_folder = f"{step.app}_{now}"
        output_dir = step.output_dir or self.task_output_dir or os.path.join(os.path.dirname(__file__), "data", "workflow", app_folder)
        os.makedirs(output_dir, exist_ok=True)
        print(f"📁 输出目录: {output_dir}")

        # 打开App
        print(f"🚀 打开应用: {step.app} ({step.package})")
        if step.activity:
            d.app_start(step.package, step.activity)
        else:
            d.app_start(step.package)
        self._sleep(step.duration or 3, "等待应用加载")

        # 处理启动弹窗
        self._handle_popups()
        self._sleep(2, "等待页面稳定")

        return output_dir

    def _click(self, step: WorkflowStep):
        """点击元素"""
        d = self._get_device()
        print(f"👉 点击: text='{step.target_text}', desc='{step.target_desc}'")

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

        if not clicked and step.target_text:
            try:
                elem = d(textContains=step.target_text)
                if elem.exists:
                    elem.click()
                    clicked = True
            except Exception:
                pass

        if not clicked and step.target_desc:
            try:
                elem = d(descriptionContains=step.target_desc)
                if elem.exists:
                    elem.click()
                    clicked = True
            except Exception:
                pass

        if not clicked:
            message = f"未找到点击目标: text='{step.target_text}', desc='{step.target_desc}'"
            print(f"  ⚠️ {message}")
            if step.required:
                raise RuntimeError(message)

        self._sleep(step.duration or DEFAULT_AFTER_CLICK_SECONDS, "等待点击后页面加载")
        self._handle_popups()

    def _single_screenshot(self, step: WorkflowStep, output_dir: str):
        """等待页面稳定后截一张图"""
        if not output_dir:
            raise RuntimeError("截图步骤缺少输出目录，请先打开应用")
        self._sleep(step.duration or DEFAULT_SCREENSHOT_SETTLE_SECONDS, "等待截图前页面稳定")
        self._handle_popups()
        self._screenshot(output_dir, prefix=step.app or "screenshot")

    def _wait_and_screenshot(self, step: WorkflowStep, output_dir: str):
        """等待并间隔截图"""
        print(f"⏳ 等待 {step.duration} 秒，每 {step.interval} 秒截图一次")
        elapsed = 0
        while elapsed < step.duration:
            self._screenshot(output_dir, prefix=step.app)
            time.sleep(step.interval)
            elapsed += step.interval
            self._handle_popups()

    def _scroll_and_screenshot(self, step: WorkflowStep, output_dir: str):
        """滑动并截图"""
        d = self._get_device()
        w, h = d.window_size()
        center_x = int(w * 0.5)
        start_y = h - 100
        end_y = start_y - int(h * 0.8)  # 滑动约一屏

        print(f"📜 滑动 {step.scroll_count} 次并截图")
        for i in range(step.scroll_count):
            print(f"  滑动 {i+1}/{step.scroll_count}")
            d.swipe(center_x, start_y, center_x, end_y, duration=0.5)
            time.sleep(2)
            self._screenshot(output_dir, prefix=step.app)
            self._handle_popups()

    def _close_app(self, step: WorkflowStep):
        """关闭App"""
        d = self._get_device()
        print(f"🛑 关闭应用: {step.app} ({step.package})")
        d.app_stop(step.package)
        time.sleep(1)

    def run(self):
        """执行工作流"""
        print("=" * 60)
        print(f"🎬 工作流: {self.config.name}")
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
            elif step.action == "screenshot":
                self._single_screenshot(step, current_output_dir)
            elif step.action == "scroll":
                self._scroll_and_screenshot(step, current_output_dir)
            elif step.action == "close_app":
                self._close_app(step)
            else:
                print(f"⚠️ 未知动作: {step.action}")

        print("\n" + "=" * 60)
        print(f"🎉 工作流完成! 共截图 {self.screenshot_count} 张")
        print("=" * 60)


def _task_context_from_env() -> Dict[str, str]:
    return {
        "name": os.getenv("WORKFLOW_TASK_NAME", ""),
        "keyword": os.getenv("WORKFLOW_TASK_KEYWORD", ""),
        "target_app": os.getenv("WORKFLOW_TARGET_APP", ""),
        "target_scenario": os.getenv("WORKFLOW_TARGET_SCENARIO", ""),
        "generated_instruction": os.getenv("WORKFLOW_GENERATED_INSTRUCTION", ""),
    }


def _has_task_context(context: Dict[str, str]) -> bool:
    return any(value.strip() for value in context.values())


def _is_jd_new_tab_task(context: Dict[str, str]) -> bool:
    text = " ".join(value for value in context.values() if value)
    target_app = context.get("target_app", "")
    return (
        ("京东" in target_app or "京东" in text or "jd" in text.lower() or "jingdong" in text.lower())
        and "新品" in text
        and ("截图" in text or "截屏" in text or "capture" in text.lower())
    )


def build_jd_new_tab_workflow() -> WorkflowConfig:
    """京东 App 新品 tab 单截图任务。"""
    return WorkflowConfig(
        name="京东新品tab截图",
        steps=[
            WorkflowStep(
                name="打开京东",
                action="open_app",
                app="京东",
                package=JD_APP_PACKAGE,
                duration=DEFAULT_APP_LOAD_SECONDS,
            ),
            WorkflowStep(
                name="点击新品tab",
                action="click",
                app="京东",
                target_text="新品",
                target_desc="新品",
                duration=DEFAULT_AFTER_CLICK_SECONDS,
                required=True,
            ),
            WorkflowStep(
                name="完成截屏",
                action="screenshot",
                app="京东",
                duration=DEFAULT_SCREENSHOT_SETTLE_SECONDS,
            ),
        ],
        popup_handler=True,
        dedup=False,
    )


def build_workflow_from_task_context(context: Dict[str, str]) -> WorkflowConfig:
    if _is_jd_new_tab_task(context):
        return build_jd_new_tab_workflow()
    raise ValueError("unsupported uiautomator2 workflow task")


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
        name="淘宝+拼多多截图工作流",
        steps=[
            # 第一阶段: 淘宝
            WorkflowStep(name="打开淘宝", action="open_app", app="taobao", package="com.taobao.taobao"),
            WorkflowStep(name="点击百亿补贴", action="click", app="taobao", target_text="百亿补贴"),
            WorkflowStep(name="等待截图(淘宝)", action="wait", app="taobao", duration=20, interval=2),
            WorkflowStep(name="滑动截图(淘宝)", action="scroll", app="taobao", scroll_count=2),

            # 第二阶段: 拼多多
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
    context = _task_context_from_env()
    workflow = build_workflow_from_task_context(context) if _has_task_context(context) else build_example_workflow()
    engine = WorkflowEngine(workflow)
    engine.run()


if __name__ == "__main__":
    main()
