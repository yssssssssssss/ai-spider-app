import cv2
import numpy as np
import os
from PIL import Image


import config

x = config.KEYWORD


def detect_and_crop_elements(image_path, output_dir=None):
    """
    从纯白色背景中检测非白色边缘，并截取近似正方形的图片
    
    参数:
    image_path: 输入图片路径
    output_dir: 输出目录
    """
    # 设置默认输出目录
    if output_dir is None:
        # 使用与输入图片相同的目录作为输出目录
        output_dir = os.path.join(os.path.dirname(image_path), "cropped")
    
    # 创建输出目录
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    
    # 检查文件是否存在
    if not os.path.exists(image_path):
        print(f"文件不存在: {image_path}")
        return
    
    # 使用numpy直接读取图片，避免OpenCV的imread中文路径问题
    try:
        # 先用PIL打开图片
        pil_img = Image.open(image_path)
        
        # 获取原图的DPI和位深信息
        original_dpi = pil_img.info.get('dpi', (300, 300))  # 默认300dpi如果没有指定
        original_mode = pil_img.mode  # 获取原图的模式（如RGB, RGBA等）
        original_bits = {"1": 1, "L": 8, "P": 8, "RGB": 24, "RGBA": 32, "CMYK": 32, "YCbCr": 24, "I": 32, "F": 32}
        original_bit_depth = original_bits.get(original_mode, 24)
        
        print(f"原图信息 - 模式: {original_mode}, DPI: {original_dpi}, 位深: {original_bit_depth}")
        
        # 转换为numpy数组
        img_array = np.array(pil_img)
        # 如果是RGB格式，转换为BGR (OpenCV使用BGR)
        if len(img_array.shape) == 3 and img_array.shape[2] == 3:
            img = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)
        else:
            img = img_array
    except Exception as e:
        print(f"读取图片时出错: {e}")
        return
    
    if img is None:
        print(f"无法读取图片: {image_path}")
        return
    
    # 获取图像尺寸
    height, width = img.shape[:2]
    
    # 创建一个掩码来存储非白色区域
    mask = np.zeros((height, width), dtype=np.uint8)
    
    # 根据图像通道数选择合适的处理方法
    if len(img.shape) == 3:
        # 检查通道数
        channels = img.shape[2]
        
        if channels == 3:  # BGR图像
            # 定义白色的BGR范围
            lower_white = np.array([250, 250, 250])
            upper_white = np.array([255, 255, 255])
            
            # 创建白色区域的掩码 (0表示白色区域，255表示非白色区域)
            white_mask = cv2.inRange(img, lower_white, upper_white)
            mask = cv2.bitwise_not(white_mask)
        elif channels == 4:  # RGBA图像
            # 提取BGR部分进行处理
            bgr_img = img[:, :, 0:3]
            
            # 定义白色的BGR范围
            lower_white = np.array([250, 250, 250])
            upper_white = np.array([255, 255, 255])
            
            # 创建白色区域的掩码
            white_mask = cv2.inRange(bgr_img, lower_white, upper_white)
            mask = cv2.bitwise_not(white_mask)
            
            # 也可以考虑使用Alpha通道作为额外信息
            # alpha_channel = img[:, :, 3]
            # 如果需要，可以结合alpha通道信息进一步改进掩码
    else:
        # 灰度图像，直接阈值处理
        _, mask = cv2.threshold(img, 250, 255, cv2.THRESH_BINARY_INV)
    
    # 对掩码进行形态学操作，去除噪点
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    
    # 查找轮廓
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # 过滤和处理轮廓
    min_area = 5000  # 最小面积阈值，可以根据需要调整
    min_height = 450  # 最小高度阈值
    
    # 近似正方形的比例容差 (允许的宽高比范围)
    square_ratio_min = 0.95  # 高/宽或宽/高不小于0.8
    square_ratio_max = 1.05  # 高/宽或宽/高不大于1.2
    
    count = 0
    skipped_count = 0
    
    # 如果没有找到轮廓或轮廓太少，尝试使用边缘检测方法
    if len(contours) < 1:
        print("使用颜色分割未找到足够的轮廓，尝试使用边缘检测方法...")
        
        # 转换为灰度图
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img
        
        # 使用自适应阈值处理
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, 20, 100)
        
        # 膨胀边缘，使轮廓更容易检测
        kernel = np.ones((3, 3), np.uint8)
        dilated = cv2.dilate(edges, kernel, iterations=2)
        
        # 查找轮廓
        contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    # 如果找到了多个轮廓，按面积排序，取最大的几个
    if len(contours) > 0:
        # 按轮廓面积排序（从大到小）
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        
        # 限制处理的轮廓数量，避免处理太多小轮廓
        max_contours = min(10, len(contours))
        
        for i in range(max_contours):
            contour = contours[i]
            
            # 计算轮廓的边界矩形
            x, y, w, h = cv2.boundingRect(contour)
            
            # 计算轮廓面积
            area = cv2.contourArea(contour)
            
            # 过滤掉太小的区域和高度不足的区域
            if area < min_area:
                print(f"跳过元素 {i+1}，面积({area})小于{min_area}像素")
                skipped_count += 1
                continue
                
            if h < min_height:
                print(f"跳过元素 {i+1}，高度({h})小于{min_height}像素")
                skipped_count += 1
                continue
            
            # 计算宽高比
            aspect_ratio = w / h if h > 0 else 0
            
            # 检查是否为近似正方形 (宽高比在指定范围内)
            if aspect_ratio < square_ratio_min or aspect_ratio > square_ratio_max:
                print(f"跳过元素 {i+1}，宽高比({aspect_ratio:.2f})不在近似正方形范围({square_ratio_min}-{square_ratio_max})内")
                skipped_count += 1
                continue
            
            # 扩大裁剪区域，确保完整包含商品
            padding = 0
            x_start = max(0, x - padding)
            y_start = max(0, y - padding)
            x_end = min(width, x + w + padding)
            y_end = min(height, y + h + padding)
            
            # 裁切图像
            cropped = pil_img.crop((x_start, y_start, x_end, y_end))
            
            # 保持原图的模式
            if cropped.mode != original_mode and original_mode == 'RGBA':
                # 如果原图是RGBA但裁切后不是，转换回RGBA
                cropped = cropped.convert('RGBA')
            elif cropped.mode == 'RGBA' and original_mode != 'RGBA':
                # 如果需要保存为不支持透明通道的格式，但又要保持位深
                if original_mode == 'RGB':
                    cropped = cropped.convert('RGB')
            
            # 获取原始文件名（不含扩展名）
            base_filename = os.path.splitext(os.path.basename(image_path))[0]
            
            # 保存裁切后的图像，保持原图的DPI和其他信息
            output_path = os.path.join(output_dir, f"{base_filename}_element_{count+1}.png")  # 使用PNG格式保持位深
            
            # 准备保存选项
            save_options = {}
            if original_dpi:
                save_options['dpi'] = original_dpi
            
            # 根据原图位深选择合适的保存格式
            if original_bit_depth == 32:
                # 对于32位图像，使用PNG格式并保持透明通道
                cropped.save(output_path, **save_options)
            else:
                # 对于其他位深，尝试保持原格式
                # 获取原图的文件扩展名
                original_ext = os.path.splitext(image_path)[1].lower()
                if original_ext in ['.jpg', '.jpeg'] and cropped.mode == 'RGB':
                    output_path = os.path.join(output_dir, f"{base_filename}_element_{count+1}.jpg")
                    cropped.save(output_path, quality=95, **save_options)
                else:
                    # 默认使用PNG以保持质量
                    cropped.save(output_path, **save_options)
            
            print(f"已保存元素 {count+1} 到 {output_path}，宽高比: {aspect_ratio:.2f}")
            count += 1
    else:
        print("未检测到任何有效轮廓")
    
    print(f"图片 {os.path.basename(image_path)} 共检测到 {len(contours)} 个轮廓，跳过 {skipped_count} 个不符合条件的元素，保存了 {count} 个符合条件的元素")
    return count

def process_image_folder(input_folder, output_folder=None):
    """
    处理文件夹中的所有图片
    
    参数:
    input_folder: 输入图片文件夹路径
    output_folder: 输出目录
    """
    # 设置默认输出目录
    if output_folder is None:
        output_folder = os.path.join(input_folder, "cropped")
    
    # 创建输出目录
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    
    # 检查输入文件夹是否存在
    if not os.path.exists(input_folder) or not os.path.isdir(input_folder):
        print(f"输入文件夹不存在或不是一个目录: {input_folder}")
        return
    
    # 支持的图片格式
    image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif']
    
    # 获取文件夹中所有图片
    image_files = []
    for file in os.listdir(input_folder):
        file_path = os.path.join(input_folder, file)
        if os.path.isfile(file_path) and os.path.splitext(file)[1].lower() in image_extensions:
            image_files.append(file_path)
    
    if not image_files:
        print(f"在文件夹 {input_folder} 中没有找到支持的图片文件")
        return
    
    print(f"在文件夹 {input_folder} 中找到 {len(image_files)} 个图片文件")
    
    # 处理每个图片
    total_elements = 0
    for i, image_path in enumerate(image_files):
        print(f"\n处理图片 {i+1}/{len(image_files)}: {os.path.basename(image_path)}")
        elements_count = detect_and_crop_elements(image_path, output_folder)
        if elements_count is not None:
            total_elements += elements_count
    
    print(f"\n处理完成! 共处理 {len(image_files)} 个图片，裁切出 {total_elements} 个符合条件的元素")

# 示例用法
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        # 如果提供了命令行参数，使用第一个参数作为输入路径
        input_path = sys.argv[1]
        
        # 如果提供了第二个参数，使用它作为输出目录
        output_dir = sys.argv[2] if len(sys.argv) > 2 else None
        
        # 检查输入路径是文件还是目录
        if os.path.isdir(input_path):
            # 如果是目录，处理目录中的所有图片
            process_image_folder(input_path, output_dir)
        else:
            # 如果是文件，处理单个图片
            detect_and_crop_elements(input_path, output_dir)
    else:
        # 默认图片路径，请修改为您的图片路径
        input_path = config.BASE_DIR
        output_dir = config.CROPPED_DIR
        
        # 检查输入路径是文件还是目录
        if os.path.isdir(input_path):
            # 如果是目录，处理目录中的所有图片
            process_image_folder(input_path, output_dir)
        else:
            # 如果是文件，处理单个图片
            detect_and_crop_elements(input_path, output_dir)