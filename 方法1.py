import os
import time
import shutil
import subprocess


import config

x = config.KEYWORD
screenshot_base_dir_template = config.BASE_DIR


def get_next_file_number(base_dir, prefix):
    """获取下一个可用的文件编号"""
    print(f"检查目录: {base_dir}")
    
    # 测试目录是否存在和可写
    if not os.path.exists(base_dir):
        try:
            os.makedirs(base_dir)
            print(f"已创建目录: {base_dir}")
        except Exception as e:
            print(f"创建目录失败: {e}")
            # 创建备用目录在桌面上
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            base_dir = os.path.join(desktop, "pdd_screenshots")
            if not os.path.exists(base_dir):
                os.makedirs(base_dir)
            print(f"使用备用目录: {base_dir}")
    
    # 测试目录写入权限
    test_file = os.path.join(base_dir, "test_write.tmp")
    try:
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        print(f"目录 {base_dir} 可写入")
    except Exception as e:
        print(f"警告: 目录 {base_dir} 可能没有写入权限: {e}")
    
    existing_files = os.listdir(base_dir)
    matching_files = [f for f in existing_files if f.startswith(f"{prefix}_") and f.endswith('.png')]
    if not matching_files:
        return 0, base_dir
    
    numbers = []
    for file in matching_files:
        try:
            num_str = file.replace(f"{prefix}_", "").replace(".png", "")
            numbers.append(int(num_str))
        except (IndexError, ValueError):
            print(f"警告: 文件名 {file} 格式不符合预期，跳过。")
            continue
    
    return max(numbers) + 1 if numbers else 0, base_dir

def run_with_uiautomator2():
    import uiautomator2 as u2

    print("开始使用 Python uiautomator2 (OpenATX) 执行任务...")
    d = None
    try:
        print("正在连接设备...")
        d = u2.connect() 
        if not d:
            print("连接设备失败！")
            return
        print(f"设备已连接: {d.device_info}")

        # 获取目录和下一个文件编号
        current_file_idx, screenshot_dir = get_next_file_number(screenshot_base_dir_template, x)
        print(f"截图将保存在: {screenshot_dir}, 起始索引: {current_file_idx}")

        app_package = 'com.taobao.taobao'

        print(f"检查应用 {app_package} 状态...")
        current_app_info = d.app_current()
        
        if current_app_info['package'] == app_package:
            print(f"应用 {app_package} 已在前台，直接在当前页面操作。")
            time.sleep(2) 
        else:
            print(f"应用 {app_package} 不在前台 (当前: {current_app_info['package']})。正在启动/切换至 {app_package}...")
            d.session(app_package)
            print("等待应用启动/切换...")
            time.sleep(5)
            
            current_app_info_after_start = d.app_current()
            if current_app_info_after_start['package'] != app_package:
                print(f"启动/切换到 {app_package} 失败。当前应用是 {current_app_info_after_start['package']}")
                return
        
        print(f"taobao ({app_package}) 已准备就绪。")

        window_size = d.window_size()
        center_x = int(window_size[0] * 0.5)
        screen_height = window_size[1]
        
        start_y_offset = 100
        
        # 第一次滑动
        scroll_start_y1 = screen_height - start_y_offset
        scroll_distance1 = 375
        scroll_end_y1 = scroll_start_y1 - scroll_distance1
        scroll_duration1_ms = 300
        print(f"执行初始滑动: 从 ({center_x},{scroll_start_y1}) 到 ({center_x},{scroll_end_y1}), 时长 {scroll_duration1_ms/1000.0}s")
        d.swipe(center_x, scroll_start_y1, center_x, scroll_end_y1, duration=scroll_duration1_ms / 1000.0)
        time.sleep(3)

        # 第一次截图 - 改进版本
        screenshot_path1 = os.path.join(screenshot_dir, f"{x}_{current_file_idx}.png")
        print(f"准备截图到: {screenshot_path1}")
        
        try:
            # 使用临时文件路径
            temp_path = os.path.join(os.path.dirname(screenshot_path1), "temp_screenshot.png")
            
            # 尝试截图
            d.screenshot(temp_path)
            
            # 检查文件是否存在和有效
            if os.path.exists(temp_path) and os.path.getsize(temp_path) > 100:
                # 移动到最终位置
                shutil.move(temp_path, screenshot_path1)
                print(f"已保存截图: {screenshot_path1} ({os.path.getsize(screenshot_path1)} 字节)")
                current_file_idx += 1
            else:
                print(f"截图文件无效或过小: {os.path.getsize(temp_path) if os.path.exists(temp_path) else '文件不存在'}")
                raise Exception("截图失败")
        except Exception as e_scr:
            print(f"首次截图失败: {e_scr}")
            print("尝试备用截图方法...")
            
            try:
                # 备用方法：使用 uiautomator2 的 pull 功能
                device_path = "/sdcard/temp_screenshot.png"
                d.screenshot(device_path)  # 保存到设备
                d.pull(device_path, screenshot_path1)  # 从设备拉取
                d.shell(f"rm {device_path}")  # 清理设备文件
                
                if os.path.exists(screenshot_path1) and os.path.getsize(screenshot_path1) > 100:
                    print(f"备用方法成功保存截图: {screenshot_path1} ({os.path.getsize(screenshot_path1)} 字节)")
                    current_file_idx += 1
                else:
                    print(f"备用截图方法失败: {os.path.getsize(screenshot_path1) if os.path.exists(screenshot_path1) else '文件不存在'}")
                    raise Exception("备用截图方法失败")
            except Exception as e_backup:
                print(f"备用截图方法也失败: {e_backup}")
                print("无法保存截图，终止任务")
                return

        total_scrolls = 60
        scroll_distance2 = 1919
        scroll_duration2_ms = 800

        for i in range(total_scrolls):
            print(f"--- 第 {i+1}/{total_scrolls} 次滑动和截图 ---")
            try:
                scroll_start_y2 = screen_height - start_y_offset
                scroll_end_y2 = scroll_start_y2 - scroll_distance2
                if scroll_end_y2 < 50: scroll_end_y2 = 50 

                print(f"执行主要滑动: 从 ({center_x},{scroll_start_y2}) 到 ({center_x},{scroll_end_y2}), 时长 {scroll_duration2_ms/1000.0}s")
                d.swipe(center_x, scroll_start_y2, center_x, scroll_end_y2, duration=scroll_duration2_ms / 1000.0)
                time.sleep(3)

                screenshot_path2 = os.path.join(screenshot_dir, f"{x}_{current_file_idx}.png")
                print(f"准备截图到: {screenshot_path2}")
                
                try:
                    # 使用临时文件路径
                    temp_path = os.path.join(os.path.dirname(screenshot_path2), "temp_screenshot.png")
                    
                    # 尝试截图
                    d.screenshot(temp_path)
                    
                    # 检查文件是否存在和有效
                    if os.path.exists(temp_path) and os.path.getsize(temp_path) > 100:
                        # 移动到最终位置
                        shutil.move(temp_path, screenshot_path2)
                        print(f"已保存截图: {screenshot_path2} ({os.path.getsize(screenshot_path2)} 字节)")
                        current_file_idx += 1
                    else:
                        print(f"截图文件无效或过小: {os.path.getsize(temp_path) if os.path.exists(temp_path) else '文件不存在'}")
                        raise Exception("截图失败")
                except Exception as e_scr:
                    print(f"截图失败: {e_scr}")
                    print("尝试备用截图方法...")
                    
                    try:
                        # 备用方法：使用 uiautomator2 的 pull 功能
                        device_path = "/sdcard/temp_screenshot.png"
                        d.screenshot(device_path)  # 保存到设备
                        d.pull(device_path, screenshot_path2)  # 从设备拉取
                        d.shell(f"rm {device_path}")  # 清理设备文件
                        
                        if os.path.exists(screenshot_path2) and os.path.getsize(screenshot_path2) > 100:
                            print(f"备用方法成功保存截图: {screenshot_path2} ({os.path.getsize(screenshot_path2)} 字节)")
                            current_file_idx += 1
                        else:
                            print(f"备用截图方法失败: {os.path.getsize(screenshot_path2) if os.path.exists(screenshot_path2) else '文件不存在'}")
                            raise Exception("备用截图方法失败")
                    except Exception as e_backup:
                        print(f"备用截图方法也失败: {e_backup}")
                        print("无法保存截图，尝试重启应用...")
                        raise Exception("所有截图方法都失败")

                if (i + 1) % 3 == 0:
                    print(f"已完成{i+1}次截图，暂停10秒...")
                    time.sleep(10)
            
            except Exception as e_loop:
                print(f"第{i+1}次循环出错: {e_loop}")
                print("尝试重启应用并继续...")
                d.app_stop(app_package)
                time.sleep(2)
                d.session(app_package)
                time.sleep(5) 
                current_app_info_after_restart = d.app_current()
                if current_app_info_after_restart['package'] != app_package:
                    print("重启应用失败，终止任务。")
                    break
                else:
                    print(f"应用 {app_package} 重启成功，尝试从下一个迭代继续。")

        print("uiautomator2 任务执行完毕。")
        print(f"截图保存在: {screenshot_dir}")
        # 尝试打开截图目录
        try:
            os.startfile(screenshot_dir)  # Windows
        except:
            try:
                subprocess.run(['xdg-open', screenshot_dir])  # Linux
            except:
                try:
                    subprocess.run(['open', screenshot_dir])  # macOS
                except:
                    print(f"无法自动打开目录，请手动查看: {screenshot_dir}")

    except ImportError:
        print("错误：uiautomator2 库未安装。请运行 'pip install uiautomator2'")
    except Exception as e:
        print(f"使用 uiautomator2 执行时发生未捕获的错误: {e}")
    finally:
        if d:
            print("尝试关闭应用...")
            try:
                d.app_stop('com.taobao.taobao')
            except Exception as e_stop:
                print(f"关闭应用时出错: {e_stop}")

if __name__ == '__main__':
    run_with_uiautomator2()