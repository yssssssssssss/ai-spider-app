import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.database import SessionLocal
from app import crud, schemas

def extract_app_and_scenario(path: str) -> tuple:
    parts = Path(path).parts
    app = "unknown"
    scenario = "unknown"
    for p in parts:
        p_lower = p.lower()
        if "taobao" in p_lower:
            app = "taobao"
        elif "pdd" in p_lower or "pinduoduo" in p_lower:
            app = "pdd"
        if "base" in p_lower:
            scenario = "base"
        elif "cropped" in p_lower or "crop" in p_lower:
            scenario = "cropped"
    return app, scenario

def migrate_folder(folder_path: str, task_id=None):
    db = SessionLocal()
    count = 0
    try:
        for root, _, files in os.walk(folder_path):
            for f in files:
                if not f.lower().endswith((".png", ".jpg", ".jpeg")):
                    continue
                full_path = os.path.join(root, f)
                app, scenario = extract_app_and_scenario(full_path)
                image_in = schemas.ImageCreate(
                    file_path=full_path,
                    source_app=app,
                    scenario=scenario,
                    captured_at=datetime.fromtimestamp(os.path.getmtime(full_path)),
                    task_id=task_id
                )
                crud.create_image(db, image_in)
                count += 1
                print(f"  已入库 [{count}]: {full_path}")
    finally:
        db.close()
    print(f"\n✅ 共入库 {count} 张图片")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        target = os.path.join(os.path.dirname(__file__), "..", "data")
    print(f"📁 开始扫描目录: {target}")
    migrate_folder(target)
