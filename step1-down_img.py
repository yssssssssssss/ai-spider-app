import unittest
import time
import os
import sys
from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
from app.services.oss_uploader import oss_uploader
from app.scripts_common import save_image_to_db

import config

x = config.KEYWORD


capabilities = dict(
    platformName='Android',
    automationName='uiautomator2',
    deviceName='Android',
    appPackage='com.taobao.taobao',  # 淘宝的包名
    appActivity='.home.MainActivity',  # 淘宝主页Activity
    # 移除language和locale设置
    # language='en',
    # locale='US',
    # 保留以下选项跳过设备初始化和设置修改
    noReset=True,
    skipDeviceInitialization=True,
    skipServerInstallation=False,
    ignoreHiddenApiPolicyError=True,
    disableWindowAnimation=False
)

appium_server_url = config.APPIUM_SERVER_URL

class TestAppium(unittest.TestCase):
    def setUp(self) -> None:
        self.driver = webdriver.Remote(appium_server_url, options=UiAutomator2Options().load_capabilities(config.APPIUM_CAPABILITIES))
        # 创建截图保存目录
        self.screenshot_dir = config.ensure_dir(config.BASE_DIR)

    def tearDown(self) -> None:
        if self.driver:
            self.driver.quit()
            
    def get_next_file_number(self, base_dir, prefix):
        """获取下一个可用的文件编号"""
        # 获取目录中所有文件
        existing_files = os.listdir(base_dir)
        
        # 过滤出以prefix开头的文件
        matching_files = [f for f in existing_files if f.startswith(f"{prefix}_") and f.endswith('.png')]
        
        if not matching_files:
            return 0
        
        # 提取所有文件编号
        numbers = []
        for file in matching_files:
            try:
                # 从文件名中提取数字部分
                num = int(file.split('_')[1].split('.')[0])
                numbers.append(num)
            except (IndexError, ValueError):
                continue
        
        # 返回最大编号+1，如果没有有效编号则返回0
        return max(numbers) + 1 if numbers else 0

    def test_open_and_scroll_screenshot(self) -> None:
        """打开淘宝，先进行一次小滑动截图，然后循环执行大滑动截图"""
        try:
            # 打开淘宝
            self.driver.activate_app('com.taobao.taobao')
            print("已通过包名直接打开淘宝")
            
            # 等待应用启动
            time.sleep(3)
            print("淘宝已成功打开")
            
            # 获取屏幕尺寸
            window_size = self.driver.get_window_size()
            center_x = int(window_size['width'] * 0.5)
            screen_height = window_size['height']
            
            # 设置起始y坐标（距离底边100px）
            start_y = screen_height - 100
            
            # 第一次滑动113像素并截图（只执行一次）
            end_y1 = start_y - 100  # 向上滑动113像素
            self.driver.swipe(center_x, start_y, center_x, end_y1, 300)
            time.sleep(1)  # 等待滑动完成
            
            # 获取下一个可用的文件编号
            next_file_num = self.get_next_file_number(self.screenshot_dir, x)
            
            # 第一次截图
            screenshot_path1 = os.path.join(self.screenshot_dir, f"{x}_{next_file_num}.png")
            self.driver.get_screenshot_as_file(screenshot_path1)
            print(f"已保存首次小滑动截图: {screenshot_path1}")
            
            # 上传到京东云 OSS
            result1 = oss_uploader.upload(screenshot_path1, scenario_name="screenshot")
            if result1.get("success"):
                print(f"  ☁️  OSS URL: {result1['url']}")
                save_image_to_db(screenshot_path1, oss_url=result1.get("url"), oss_key=result1.get("key"), source_app="taobao")
            else:
                print(f"  ⚠️ OSS 上传失败: {result1.get('error')}")
            
            # 设置滑动次数
            total_scrolls = 65  # 可以根据需要修改这个值
            
            # 循环执行大滑动并截图
            for i in range(total_scrolls):
                # 每次滑动前都重置起始坐标到距离底边100px
                start_y = screen_height - 100
                
                # 滑动1919像素并截图
                end_y2 = start_y - 1700  # 向上滑动1919像素
                self.driver.swipe(center_x, start_y, center_x, end_y2, 800)
                time.sleep(1.5)  # 等待滑动完成和内容加载
                
                # 获取下一个可用的文件编号
                next_file_num = self.get_next_file_number(self.screenshot_dir, x)
                
                # 截图
                screenshot_path2 = os.path.join(self.screenshot_dir, f"{x}_{next_file_num}.png")
                self.driver.get_screenshot_as_file(screenshot_path2)
                print(f"已保存第{next_file_num}次大滑动截图: {screenshot_path2}")
                
                # 上传到京东云 OSS
                result2 = oss_uploader.upload(screenshot_path2, scenario_name="screenshot")
                if result2.get("success"):
                    print(f"  ☁️  OSS URL: {result2['url']}")
                    save_image_to_db(screenshot_path2, oss_url=result2.get("url"), oss_key=result2.get("key"), source_app="taobao")
                else:
                    print(f"  ⚠️ OSS 上传失败: {result2.get('error')}")
                
        except Exception as e:
            print(f"滑动截图过程中发生错误: {e}")

if __name__ == '__main__':
    # 只运行指定的测试
    suite = unittest.TestSuite()
    suite.addTest(TestAppium('test_open_and_scroll_screenshot'))
    unittest.TextTestRunner().run(suite)