from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from uuid import UUID
import os
from typing import List
from PIL import Image, ImageOps, UnidentifiedImageError
from app.database import get_db
from app import crud, schemas, models
from app.config import settings
from app.services.llm_analyzer import analyzer
from app.services.embedder import embedder

router = APIRouter(prefix="/images", tags=["images"])

NEAR_DUPLICATE_SIZE = (16, 16)
NEAR_DUPLICATE_MAX_PIXEL_DELTA = 6.0
NEAR_DUPLICATE_MAX_HASH_DISTANCE = 24
ANALYZED_STATUSES = ("success", "partial")


def _resolve_image_path(image_path: str) -> str:
    if os.path.isabs(image_path):
        return image_path
    return os.path.join(settings.PROJECT_ROOT, image_path)


def _page_signature(image_path: str) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
    try:
        with Image.open(_resolve_image_path(image_path)) as img:
            gray = ImageOps.grayscale(img)
            small = gray.resize(NEAR_DUPLICATE_SIZE, Image.Resampling.LANCZOS)
            pixels = tuple(int(p) for p in small.getdata())
    except (FileNotFoundError, UnidentifiedImageError, OSError):
        return None

    avg = sum(pixels) / len(pixels)
    bits = tuple(1 if p >= avg else 0 for p in pixels)
    return pixels, bits


def _is_near_duplicate_signature(
    left: tuple[tuple[int, ...], tuple[int, ...]],
    right: tuple[tuple[int, ...], tuple[int, ...]],
) -> bool:
    left_pixels, left_bits = left
    right_pixels, right_bits = right
    pixel_delta = sum(abs(a - b) for a, b in zip(left_pixels, right_pixels)) / len(left_pixels)
    hash_distance = sum(a != b for a, b in zip(left_bits, right_bits))
    return (
        pixel_delta <= NEAR_DUPLICATE_MAX_PIXEL_DELTA
        and hash_distance <= NEAR_DUPLICATE_MAX_HASH_DISTANCE
    )


def _find_near_duplicate_image(db: Session, image: models.Image) -> models.Image | None:
    if not image.task_id:
        return None

    current_signature = _page_signature(image.file_path)
    if not current_signature:
        return None

    candidates = (
        db.query(models.Image)
        .join(models.Analysis, models.Analysis.image_id == models.Image.id)
        .filter(models.Image.task_id == image.task_id)
        .filter(models.Image.id != image.id)
        .filter(models.Analysis.status.in_(ANALYZED_STATUSES))
        .order_by(models.Image.created_at.asc())
        .limit(100)
        .all()
    )
    for candidate in candidates:
        candidate_signature = _page_signature(candidate.file_path)
        if candidate_signature and _is_near_duplicate_signature(current_signature, candidate_signature):
            return candidate
    return None

def _analysis_context(image) -> dict:
    task = image.task
    request = task.request if task else None
    keywords = []
    if request and request.keywords:
        keywords = request.keywords
    elif task and task.keyword:
        keywords = [task.keyword]
    return {
        "target_app": image.source_app or (task.target_app if task else None) or (request.target_app if request else None),
        "target_scenario": image.scenario or (task.target_scenario if task else None) or (request.target_scenario if request else None),
        "keywords": keywords,
        "focus_question": request.description if request else None,
    }

async def _analyze_and_embed(image_id: UUID):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        image = crud.get_image(db, image_id)
        if not image:
            return
        duplicate = _find_near_duplicate_image(db, image)
        if duplicate:
            crud.create_analysis(
                db,
                image_id,
                "",
                f"近似页面，跳过重复分析: 已分析过 {duplicate.file_path}",
                status="skipped",
            )
            return
        context = _analysis_context(image)
        try:
            is_target, reason = await analyzer.is_target_page(image.file_path, context)
            if not is_target:
                crud.create_analysis(db, image_id, "", f"非目标页面，跳过分析: {reason}", status="skipped")
                return
            design, ops, status = await analyzer.analyze(image.file_path, context=context)
        except Exception as e:
            crud.create_analysis(db, image_id, "", f"分析失败: {e}", status="failed")
            return
        analysis = crud.create_analysis(db, image_id, design or "", ops or "", status=status)
        combined_text = f"{design or ''}\n{ops or ''}".strip()
        try:
            if combined_text:
                vector = await embedder.embed_single(combined_text)
                crud.create_embedding(db, analysis.id, vector, "combined")
            if design:
                v_design = await embedder.embed_single(design)
                crud.create_embedding(db, analysis.id, v_design, "design")
            if ops:
                v_ops = await embedder.embed_single(ops)
                crud.create_embedding(db, analysis.id, v_ops, "ops")
        except Exception as e:
            print(f"⚠️ 向量写入失败 image={image_id}: {e}")
    finally:
        db.close()

@router.post("", response_model=schemas.ImageOut)
def create_image(image: schemas.ImageCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    db_image = crud.create_image(db, image)
    background_tasks.add_task(_analyze_and_embed, db_image.id)
    return db_image

@router.post("/bulk", response_model=List[schemas.ImageOut])
def create_images_bulk(images: List[schemas.ImageCreate], background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """批量创建图片记录（脚本上报用）"""
    results = []
    for image in images:
        db_image = crud.create_image(db, image)
        background_tasks.add_task(_analyze_and_embed, db_image.id)
        results.append(db_image)
    return results

@router.get("/{image_id}", response_model=schemas.ImageOut)
def get_image(image_id: UUID, db: Session = Depends(get_db)):
    img = crud.get_image(db, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    return img

@router.get("/{image_id}/file")
def get_image_file(image_id: UUID, db: Session = Depends(get_db)):
    """直接返回图片文件，避免前端处理静态路径"""
    img = crud.get_image(db, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    file_path = analyzer._resolve_image_path(img.file_path)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Image file not found on disk")
    return FileResponse(file_path)

@router.post("/{image_id}/analyze")
def trigger_analyze(image_id: UUID, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    img = crud.get_image(db, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    background_tasks.add_task(_analyze_and_embed, image_id)
    return {"message": "Analysis triggered", "image_id": image_id}
