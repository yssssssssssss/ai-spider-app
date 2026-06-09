from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session
from uuid import UUID
import os
from typing import Any, List
from PIL import Image, ImageOps, UnidentifiedImageError
from app.database import get_db
from app import crud, schemas, models
from app.config import settings
from app.services.llm_analyzer import analyzer
from app.services.embedder import embedder
from app.services.auth import data_scope_user_id, get_current_user, require_at_least
from app.services.goal_validator import refresh_task_run_goal_validation
from app.services.page_evidence import evidence_is_usable, merge_page_evidence

router = APIRouter(prefix="/images", tags=["images"])

NEAR_DUPLICATE_SIZE = (16, 16)
NEAR_DUPLICATE_MAX_PIXEL_DELTA = 6.0
NEAR_DUPLICATE_MAX_HASH_DISTANCE = 24
ANALYZED_STATUSES = ("success", "partial")


def _current_user_id(user) -> UUID | None:
    return data_scope_user_id(user)


def _get_owned_image(db: Session, image_id: UUID, user: models.User) -> models.Image:
    user_id = _current_user_id(user)
    image = crud.get_image_for_user(db, image_id, user_id) if user_id else crud.get_image(db, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    return image


def _ensure_image_task_owner(db: Session, image: schemas.ImageCreate, user: models.User):
    if not image.task_id:
        raise HTTPException(status_code=400, detail="task_id is required for user-owned images")
    scope_user_id = data_scope_user_id(user)
    task = crud.get_task_for_user(db, image.task_id, scope_user_id) if scope_user_id else crud.get_task(db, image.task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")


def _resolve_image_path(image_path: str) -> str:
    if os.path.isabs(image_path):
        return image_path
    return os.path.join(settings.PROJECT_ROOT, image_path)


def _page_signature(image_path: str) -> tuple[tuple[int, ...], tuple[int, ...]] | None:
    try:
        with Image.open(_resolve_image_path(image_path)) as img:
            gray = ImageOps.grayscale(img)
            small = gray.resize(NEAR_DUPLICATE_SIZE, Image.Resampling.LANCZOS)
            pixel_data = small.get_flattened_data() if hasattr(small, "get_flattened_data") else small.getdata()
            pixels = tuple(int(p) for p in pixel_data)
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


def _clean_target_value(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _append_page_target(targets: list[dict], seen: set[str], target: dict) -> None:
    key = _clean_target_value(target.get("target_key"))
    name = _clean_target_value(target.get("target_name"))
    if not key or not name or key in seen:
        return
    target["target_key"] = key
    target["target_name"] = name
    target["description"] = _clean_target_value(target.get("description"))
    target["goal_labels"] = [
        label
        for label in (_clean_target_value(item) for item in target.get("goal_labels", []))
        if label
    ]
    seen.add(key)
    targets.append(target)


def _page_evidence_targets(db: Session, image: models.Image) -> list[dict]:
    targets: list[dict] = []
    seen: set[str] = set()

    if image.task_id:
        group = crud.get_comparison_group_by_task(db, image.task_id)
        if group:
            for slot in crud.list_comparison_slots(db, group.id):
                _append_page_target(targets, seen, {
                    "target_key": slot.slot_key,
                    "target_name": slot.name,
                    "target_type": "comparison_slot",
                    "description": slot.description,
                    "goal_labels": [],
                })

    task = image.task
    raw_goals = task.target_goals_json if task and isinstance(task.target_goals_json, list) else []
    for index, goal in enumerate(raw_goals, start=1):
        if not isinstance(goal, dict):
            continue
        label = _clean_target_value(goal.get("label"))
        keywords = [
            keyword
            for keyword in (_clean_target_value(item) for item in goal.get("evidence_keywords", []))
            if keyword
        ]
        description = f"目标截图：{label}"
        if keywords:
            description += f"；判定关键词：{'、'.join(keywords)}"
        if goal.get("accepts_business_module"):
            description += (
                "；可接受终态：独立频道/会场页面，或当前页面中完整露出的同名/等价业务模块。"
                "完整业务模块需同时出现模块标题、多个商品/权益/活动项和核心利益点；"
                "单个入口按钮、“更多”按钮、单张卡片、加载态不算终态。"
            )
        _append_page_target(targets, seen, {
            "target_key": goal.get("target_key") or goal.get("key") or f"goal_{index}",
            "target_name": label,
            "target_type": goal.get("type") or "page_goal",
            "description": description,
            "goal_labels": [label],
        })
    return targets


async def _extract_page_evidence(image: models.Image, targets: list[dict], context: dict) -> dict | None:
    if not targets or not hasattr(analyzer, "extract_page_evidence"):
        return None
    try:
        evidence = await analyzer.extract_page_evidence(image.file_path, targets, context=context)
        return evidence if isinstance(evidence, dict) else None
    except Exception as e:
        print(f"⚠️ 页面证据提取失败 image={image.id}: {e}")
        return None


def _record_analysis(
    db: Session,
    image: models.Image,
    design: str,
    ops: str,
    status: str = "success",
    custom_analysis_json: dict | None = None,
):
    analysis = crud.create_analysis(
        db,
        image.id,
        design,
        ops,
        status=status,
        custom_analysis_json=custom_analysis_json,
    )
    if image.task_id:
        refresh_task_run_goal_validation(db, image.task_id, image.task_run_id)
    return analysis


def _skill_snapshots_for_image(image) -> list[dict]:
    task = image.task
    if task and task.analysis_skill_snapshots_json:
        return task.analysis_skill_snapshots_json
    if task and task.watch_runs:
        for watch_run in task.watch_runs:
            if any(snapshot.image_id == image.id for snapshot in watch_run.snapshots):
                if watch_run.plan and watch_run.plan.analysis_skill_snapshots_json:
                    return watch_run.plan.analysis_skill_snapshots_json
        for watch_run in task.watch_runs:
            if watch_run.task_id != task.id:
                continue
            if watch_run.plan and watch_run.plan.analysis_skill_snapshots_json:
                return watch_run.plan.analysis_skill_snapshots_json
    return []


def _analysis_texts(design: str, ops: str, custom_analysis_json: dict | None) -> dict[str, str]:
    results = (custom_analysis_json or {}).get("results") if isinstance(custom_analysis_json, dict) else None
    dynamic_text = "\n".join(
        row.get("analysis", "")
        for row in (results or [])
        if isinstance(row, dict) and row.get("analysis")
    ).strip()
    combined = dynamic_text or f"{design or ''}\n{ops or ''}".strip()
    texts = {"combined": combined} if combined else {}
    if design:
        texts["design"] = design
    if ops:
        texts["ops"] = ops
    return texts


async def _analyze_and_embed(image_id: UUID):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        image = crud.get_image(db, image_id)
        if not image:
            return
        duplicate = _find_near_duplicate_image(db, image)
        if duplicate:
            _record_analysis(
                db,
                image,
                "",
                f"近似页面，跳过重复分析: 已分析过 {duplicate.file_path}",
                status="skipped",
            )
            return
        context = _analysis_context(image)
        page_targets = _page_evidence_targets(db, image)
        page_evidence = await _extract_page_evidence(image, page_targets, context)
        try:
            is_target, reason = await analyzer.is_target_page(image.file_path, context)
            if not is_target and not evidence_is_usable(page_evidence):
                custom = merge_page_evidence({}, page_evidence) if page_evidence else None
                _record_analysis(db, image, "", f"非目标页面，跳过分析: {reason}", status="skipped", custom_analysis_json=custom)
                return
            skill_snapshots = _skill_snapshots_for_image(image)
            if hasattr(analyzer, "analyze_with_skills"):
                result = await analyzer.analyze_with_skills(image.file_path, skill_snapshots, context=context)
            else:
                design, ops, status = await analyzer.analyze(image.file_path, context=context)
                result = {
                    "design_analysis": design or "",
                    "ops_analysis": ops or "",
                    "custom_analysis_json": {},
                    "status": status,
                }
            design = result["design_analysis"]
            ops = result["ops_analysis"]
            status = result["status"]
            custom_analysis_json = merge_page_evidence(result.get("custom_analysis_json") or {}, page_evidence)
        except Exception as e:
            _record_analysis(db, image, "", f"分析失败: {e}", status="failed")
            return
        analysis = _record_analysis(
            db,
            image,
            design or "",
            ops or "",
            status=status,
            custom_analysis_json=custom_analysis_json,
        )
        if status in ("success", "partial"):
            try:
                from app.services.jd_comparison import process_image_for_comparison
                await process_image_for_comparison(image.id)
            except Exception as e:
                print(f"⚠️ JD 对照处理失败 image={image_id}: {e}")
        texts = _analysis_texts(design or "", ops or "", custom_analysis_json)
        try:
            vectors = {}
            for content_type, text in texts.items():
                vectors[content_type] = await embedder.embed_single(text)
            if vectors:
                crud.replace_embeddings(db, analysis.id, vectors)
            crud.update_embedding_status(db, analysis.id, "success")
        except Exception as e:
            crud.update_embedding_status(db, analysis.id, "failed", str(e))
            print(f"⚠️ 向量写入失败 image={image_id}: {e}")
    finally:
        db.close()

@router.post("", response_model=schemas.ImageOut)
def create_image(
    image: schemas.ImageCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    _ensure_image_task_owner(db, image, user)
    db_image = crud.create_image(db, image)
    background_tasks.add_task(_analyze_and_embed, db_image.id)
    return db_image

@router.post("/bulk", response_model=List[schemas.ImageOut])
def create_images_bulk(
    images: List[schemas.ImageCreate],
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    """批量创建图片记录（脚本上报用）"""
    results = []
    for image in images:
        _ensure_image_task_owner(db, image, user)
        db_image = crud.create_image(db, image)
        background_tasks.add_task(_analyze_and_embed, db_image.id)
        results.append(db_image)
    return results


@router.get("", response_model=List[schemas.SearchResult])
def list_images(
    skip: int = 0,
    limit: int = 100,
    task_id: UUID | None = None,
    analysis_status: str | None = None,
    embedding_status: str | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    user_id = _current_user_id(user)
    images = crud.list_images(
        db,
        skip=skip,
        limit=limit,
        task_id=task_id,
        analysis_status=analysis_status,
        embedding_status=embedding_status,
        user_id=user_id,
    )
    return [
        schemas.SearchResult(
            image=schemas.ImageOut.model_validate(image),
            analysis=schemas.AnalysisOut.model_validate(image.analysis) if image.analysis else None,
            similarity=None,
        )
        for image in images
    ]


@router.get("/{image_id}", response_model=schemas.ImageOut)
def get_image(image_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return _get_owned_image(db, image_id, user)

@router.get("/{image_id}/file")
def get_image_file(image_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """直接返回图片文件，避免前端处理静态路径"""
    img = _get_owned_image(db, image_id, user)
    file_path = analyzer._resolve_image_path(img.file_path)
    if not os.path.exists(file_path):
        if img.oss_url:
            return RedirectResponse(img.oss_url, status_code=302)
        raise HTTPException(status_code=404, detail="Image file not found on disk")
    return FileResponse(file_path)

@router.post("/{image_id}/analyze")
def trigger_analyze(
    image_id: UUID,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    _get_owned_image(db, image_id, user)
    background_tasks.add_task(_analyze_and_embed, image_id)
    return {"message": "Analysis triggered", "image_id": image_id}
