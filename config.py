"""
项目统一配置文件
将硬编码的 Windows 绝对路径改为跨平台的相对路径
"""
import os

# 项目根目录（当前文件所在目录）
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# 搜索关键词（默认：智能手表）
KEYWORD = os.getenv("TB_KEYWORD", "智能手表")

# 截图基础目录
BASE_DIR = os.path.join(PROJECT_ROOT, "data", KEYWORD, "base")

# 裁剪输出目录
CROPPED_DIR = os.path.join(PROJECT_ROOT, "data", KEYWORD, "cropped")

# Appium 服务器地址
APPIUM_SERVER_URL = os.getenv("APPIUM_SERVER_URL", "http://localhost:4723")

# 设备能力配置（Appium）
APPIUM_CAPABILITIES = dict(
    platformName="Android",
    automationName="uiautomator2",
    deviceName="Android",
    appPackage="com.taobao.taobao",
    appActivity=".home.MainActivity",
    noReset=True,
    skipDeviceInitialization=True,
    skipServerInstallation=False,
    ignoreHiddenApiPolicyError=True,
    disableWindowAnimation=False,
)


def ensure_dir(path: str) -> str:
    """确保目录存在，如果不存在则创建"""
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)
    return path
