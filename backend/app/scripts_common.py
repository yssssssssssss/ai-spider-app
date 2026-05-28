"""
脚本通用工具：截图上传 OSS 后自动写入数据库
供 step1-down_img.py、step2-cut_img.py、run_workflow*.py、run_hybrid.py 等调用
"""
import os
from datetime import datetime


def normalize_image_path(file_path: str) -> str:
    from app.config import settings

    abs_path = os.path.abspath(file_path)
    try:
        return os.path.relpath(abs_path, settings.PROJECT_ROOT)
    except ValueError:
        return file_path


def save_image_to_db(file_path: str, oss_url: str = None, oss_key: str = None,
                     source_app: str = None, scenario: str = None, task_id: str = None):
    """
    将图片信息保存到数据库。如果数据库不可用则打印警告但不报错。

    Returns:
        创建的 Image 对象，或 None
    """
    try:
        from app.database import SessionLocal
        from app import crud, schemas

        db = SessionLocal()
        try:
            image_data = schemas.ImageCreate(
                file_path=normalize_image_path(file_path),
                oss_url=oss_url,
                oss_key=oss_key,
                source_app=source_app,
                scenario=scenario,
                captured_at=datetime.utcnow(),
                task_id=task_id,
            )
            db_image = crud.create_image(db, image_data)
            print(f"  ✅ 已保存到数据库: {db_image.id}")
            return db_image
        finally:
            db.close()
    except Exception as e:
        print(f"  ⚠️ 数据库保存失败（可忽略）: {e}")
        return None
