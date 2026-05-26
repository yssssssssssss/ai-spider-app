"""
AutoGLM 驱动脚本
使用 Open-AutoGLM 的 AI 能力驱动手机完成淘宝截图任务
"""
import os
import sys
import argparse

# 将 Open-AutoGLM 加入路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "Open-AutoGLM"))

from phone_agent import PhoneAgent
from phone_agent.agent import AgentConfig
from phone_agent.model import ModelConfig
from phone_agent.device_factory import DeviceType, set_device_type

import config as app_config


def run_with_autoglm(task: str, base_url: str = None, model: str = None, apikey: str = None, max_steps: int = 100):
    """
    使用 AutoGLM 执行自然语言任务

    Args:
        task: 自然语言任务描述，如"打开淘宝搜索智能手表并截图"
        base_url: 模型服务地址，默认从环境变量 PHONE_AGENT_BASE_URL 读取
        model: 模型名称，默认从环境变量 PHONE_AGENT_MODEL 读取
        apikey: API Key，默认从环境变量 PHONE_AGENT_API_KEY 读取
        max_steps: 最大执行步数
    """
    # 设置设备类型为 ADB (Android)
    set_device_type(DeviceType.ADB)

    # 模型配置
    model_config = ModelConfig(
        base_url=base_url or os.getenv("PHONE_AGENT_BASE_URL", "http://localhost:8000/v1"),
        model_name=model or os.getenv("PHONE_AGENT_MODEL", "autoglm-phone-9b"),
        api_key=apikey or os.getenv("PHONE_AGENT_API_KEY", "EMPTY"),
    )

    # Agent 配置
    agent_config = AgentConfig(
        max_steps=max_steps,
        device_id=os.getenv("PHONE_AGENT_DEVICE_ID", None),
        lang="cn",
        verbose=True,
    )

    # 创建 Agent
    agent = PhoneAgent(
        model_config=model_config,
        agent_config=agent_config,
    )

    # 执行任务
    print(f"🚀 任务: {task}")
    print("-" * 50)
    result = agent.run(task)
    print("-" * 50)
    print(f"✅ 任务完成: {result}")
    return result


def main():
    parser = argparse.ArgumentParser(description="使用 AutoGLM 驱动手机完成淘宝截图任务")
    parser.add_argument("task", nargs="?", default="打开淘宝搜索智能手表并截图",
                        help="自然语言任务描述 (默认: 打开淘宝搜索智能手表并截图)")
    parser.add_argument("--base-url", default=None, help="模型服务地址")
    parser.add_argument("--model", default=None, help="模型名称")
    parser.add_argument("--apikey", default=None, help="API Key")
    parser.add_argument("--max-steps", type=int, default=100, help="最大执行步数")
    parser.add_argument("--check", action="store_true", help="检查系统要求")

    args = parser.parse_args()

    if args.check:
        # 运行系统检查
        os.system(f"cd {os.path.join(os.path.dirname(__file__), 'Open-AutoGLM')} && python main.py --check")
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
    )


if __name__ == "__main__":
    main()
