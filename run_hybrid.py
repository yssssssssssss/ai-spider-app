"""
AutoGLM + uiautomator2 混合驱动脚本
- 使用 AutoGLM 理解任务、导航到目标页面
- 使用 uiautomator2 执行稳定的滑动截图循环
"""
import os
import sys
import time
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Open-AutoGLM"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from app.services.oss_uploader import oss_uploader
from app.scripts_common import save_image_to_db

from phone_agent import PhoneAgent
from phone_agent.agent import AgentConfig
from phone_agent.model import ModelConfig
from phone_agent.device_factory import DeviceType, set_device_type

import config as app_config


def autoglm_navigate(task: str, base_url: str, model: str, apikey: str, max_steps: int = 20):
    """
    使用 AutoGLM 执行导航任务（打开App、搜索、进入结果页）
    """
    set_device_type(DeviceType.ADB)

    model_config = ModelConfig(
        base_url=base_url,
        model_name=model,
        api_key=apikey,
    )

    agent_config = AgentConfig(
        max_steps=max_steps,
        device_id=os.getenv("PHONE_AGENT_DEVICE_ID", None),
        lang="cn",
        verbose=True,
    )

    agent = PhoneAgent(
        model_config=model_config,
        agent_config=agent_config,
    )

    print(f"🚀 [AutoGLM] 导航任务: {task}")
    print("-" * 50)
    result = agent.run(task)
    print("-" * 50)
    print(f"✅ [AutoGLM] 导航完成: {result}")
    return result


def uiautomator2_scroll_screenshots(
    keyword: str = None,
    total_scrolls: int = 60,
    output_dir: str = None,
):
    """
    使用 uiautomator2 执行滑动截图循环
    复用 方法1.py 的核心逻辑
    """
    import uiautomator2 as u2

    keyword = keyword or app_config.KEYWORD
    output_dir = output_dir or app_config.BASE_DIR
    os.makedirs(output_dir, exist_ok=True)

    print(f"🚀 [uiautomator2] 开始滑动截图: keyword={keyword}, output={output_dir}")

    d = u2.connect()
    print(f"✅ 设备已连接: {d.device_info}")

    window_size = d.window_size()
    center_x = int(window_size[0] * 0.5)
    screen_height = window_size[1]
    start_y_offset = 100

    # 获取下一个文件编号
    existing = [f for f in os.listdir(output_dir) if f.startswith(f"{keyword}_") and f.endswith('.png')]
    numbers = []
    for f in existing:
        try:
            num = int(f.replace(f"{keyword}_", "").replace(".png", ""))
            numbers.append(num)
        except:
            pass
    current_idx = max(numbers) + 1 if numbers else 0
    print(f"📸 起始索引: {current_idx}, 已有截图: {len(numbers)} 张")

    # 初始小滑动
    scroll_start_y1 = screen_height - start_y_offset
    scroll_end_y1 = scroll_start_y1 - 375
    print(f"👉 初始滑动: ({center_x},{scroll_start_y1}) -> ({center_x},{scroll_end_y1})")
    d.swipe(center_x, scroll_start_y1, center_x, scroll_end_y1, duration=0.3)
    time.sleep(3)

    # 截图
    screenshot_path = os.path.join(output_dir, f"{keyword}_{current_idx}.png")
    d.screenshot(screenshot_path)
    print(f"📸 已保存: {screenshot_path}")
    result = oss_uploader.upload(screenshot_path, scenario_name="screenshot")
    if result.get("success"):
        print(f"  ☁️  OSS URL: {result['url']}")
        save_image_to_db(screenshot_path, oss_url=result.get("url"), oss_key=result.get("key"), source_app="taobao", scenario="screenshot")
    current_idx += 1

    # 大滑动循环
    scroll_distance2 = 1919
    scroll_duration2_ms = 800

    for i in range(total_scrolls):
        print(f"--- 第 {i+1}/{total_scrolls} 次滑动 ---")
        scroll_start_y2 = screen_height - start_y_offset
        scroll_end_y2 = scroll_start_y2 - scroll_distance2
        if scroll_end_y2 < 50:
            scroll_end_y2 = 50

        d.swipe(center_x, scroll_start_y2, center_x, scroll_end_y2, duration=scroll_duration2_ms / 1000.0)
        time.sleep(3)

        screenshot_path = os.path.join(output_dir, f"{keyword}_{current_idx}.png")
        d.screenshot(screenshot_path)
        print(f"📸 已保存: {screenshot_path}")
        result = oss_uploader.upload(screenshot_path, scenario_name="screenshot")
        if result.get("success"):
            print(f"  ☁️  OSS URL: {result['url']}")
            save_image_to_db(screenshot_path, oss_url=result.get("url"), oss_key=result.get("key"), source_app="taobao", scenario="screenshot")
        current_idx += 1

        if (i + 1) % 3 == 0:
            print(f"⏸️ 已完成 {i+1} 次截图，暂停 10 秒...")
            time.sleep(10)

    print(f"✅ [uiautomator2] 完成! 共截图 {current_idx} 张，保存在: {output_dir}")
    return output_dir


def run_full_task(
    keyword: str = None,
    total_scrolls: int = 60,
    base_url: str = None,
    model: str = None,
    apikey: str = None,
    skip_nav: bool = False,
):
    """
    完整任务流程：
    1. AutoGLM 导航到搜索结果页
    2. uiautomator2 滑动截图
    """
    keyword = keyword or app_config.KEYWORD
    base_url = base_url or os.getenv("PHONE_AGENT_BASE_URL")
    model = model or os.getenv("PHONE_AGENT_MODEL", "autoglm-phone-9b")
    apikey = apikey or os.getenv("PHONE_AGENT_API_KEY")

    # 阶段 1: AutoGLM 导航
    if not skip_nav:
        if not base_url:
            print("❌ 错误: 未设置模型服务地址。请设置环境变量 PHONE_AGENT_BASE_URL 或使用 --base-url")
            sys.exit(1)

        nav_task = f"打开淘宝，搜索{keyword}，进入搜索结果页面"
        autoglm_navigate(nav_task, base_url, model, apikey)
        print("⏳ 等待页面稳定...")
        time.sleep(5)

    # 阶段 2: uiautomator2 滑动截图
    output_dir = uiautomator2_scroll_screenshots(keyword=keyword, total_scrolls=total_scrolls)

    print("\n" + "=" * 50)
    print("🎉 任务全部完成!")
    print(f"📁 截图保存位置: {output_dir}")
    print("=" * 50)
    return output_dir


def main():
    import argparse
    parser = argparse.ArgumentParser(description="AutoGLM + uiautomator2 混合驱动淘宝截图")
    parser.add_argument("--keyword", default=None, help="搜索关键词 (默认: 智能手表)")
    parser.add_argument("--scrolls", type=int, default=60, help="滑动次数 (默认: 60)")
    parser.add_argument("--base-url", default=None, help="模型服务地址")
    parser.add_argument("--model", default=None, help="模型名称")
    parser.add_argument("--apikey", default=None, help="API Key")
    parser.add_argument("--skip-nav", action="store_true", help="跳过 AutoGLM 导航，直接开始滑动截图")
    parser.add_argument("--check", action="store_true", help="检查系统要求")

    args = parser.parse_args()

    if args.check:
        os.system(f"cd {os.path.join(os.path.dirname(__file__), 'Open-AutoGLM')} && python main.py --check")
        return

    run_full_task(
        keyword=args.keyword,
        total_scrolls=args.scrolls,
        base_url=args.base_url,
        model=args.model,
        apikey=args.apikey,
        skip_nav=args.skip_nav,
    )


if __name__ == "__main__":
    main()
