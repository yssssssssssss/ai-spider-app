from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session
from uuid import UUID
import os
from types import SimpleNamespace
from typing import List
from PIL import Image, ImageOps, UnidentifiedImageError
from app.database import get_db
from app import crud, schemas, models
from app.config import settings
from app.services.llm_analyzer import analyzer
from app.services.embedder import embedder
from app.services.auth import data_scope_user_id, get_current_user, require_at_least
from app.services.goal_validator import refresh_task_run_goal_validation
from app.services.model_trace import capture_model_calls, model_purpose
from app.services.inspection import Specification, build_inspection, skill_snapshot, validate_skill_output

router = APIRouter(prefix="/images", tags=["images"])

NEAR_DUPLICATE_SIZE = (16, 16)
NEAR_DUPLICATE_MAX_PIXEL_DELTA = 6.0
NEAR_DUPLICATE_MAX_HASH_DISTANCE = 24
ANALYZED_STATUSES = ("success", "partial")
WATCH_TASK_PREFIX = "[持续观察]"


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
        .filter(models.Analysis.skill_id == None)  # noqa: E711 — 只看旧格式分析记录
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


def _is_watch_task(task) -> bool:
    return bool(task) and str(task.name or "").startswith(WATCH_TASK_PREFIX)


def _watch_focus_question(task) -> str | None:
    if not task:
        return None
    for run in getattr(task, "watch_runs", []) or []:
        plan = getattr(run, "plan", None)
        focus = getattr(plan, "focus_question", None)
        if focus:
            return focus
    return None

def _analysis_context(image, db: Session | None = None) -> dict:
    task = image.task
    request = task.request if task else None
    keywords = []
    if request and request.keywords:
        keywords = request.keywords
    elif task and task.keyword:
        keywords = [task.keyword]
    is_watch = _is_watch_task(task)
    context = {
        "target_app": image.source_app or (task.target_app if task else None) or (request.target_app if request else None),
        "target_scenario": image.scenario or (task.target_scenario if task else None) or (request.target_scenario if request else None),
        "keywords": keywords,
        "focus_question": _watch_focus_question(task) if is_watch else (request.description if request else None),
        "prompt_profile": "watch" if is_watch else "default",
    }
    return context


def _record_analysis(db: Session, image: models.Image, design: str, ops: str, status: str = "success",
                     skill_id=None, skill_key: str | None = None, result_json: dict | None = None,
                     provenance_json: dict | None = None, inspection_json: dict | None = None):
    analysis = crud.create_analysis(
        db, image.id, design, ops, status=status,
        skill_id=skill_id, skill_key=skill_key, result_json=result_json,
        provenance_json=provenance_json, inspection_json=inspection_json,
    )
    if image.task_id:
        refresh_task_run_goal_validation(db, image.task_id, image.task_run_id)
    return analysis


async def _analyze_and_embed(image_id: UUID):
    with capture_model_calls() as calls:
        await _analyze_image(image_id, calls)


async def _analyze_image(image_id: UUID, calls: list):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        image = crud.get_image(db, image_id)
        if not image:
            return
        definition = None
        target_validation = None

        def record(design, ops, **kwargs):
            return _record_analysis(db, image, design, ops, provenance_json={
                "schema_version": 1, "implementation_version": "inspection-v1",
                "skill": definition, "target_validation": target_validation,
                "binding_mode": "run_snapshot" if image.task_run and image.task_run.analysis_skills_snapshot_json is not None else "current_skill_at_analysis",
                "model_calls": list(calls),
            }, **kwargs)

        # 重复检测
        skill_ids = getattr(image.task, "analysis_skill_ids", None) or []
        bound_skills = db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id.in_(skill_ids)).all() if skill_ids else []
        run_snapshot = image.task_run.analysis_skills_snapshot_json if image.task_run else None
        if run_snapshot is not None:
            bound_skills = [SimpleNamespace(**{key: value for key, value in item.items() if key != "sha256"}) for item in run_snapshot]
            skill_ids = [item.id for item in bound_skills]

        def reject(status, message):
            nonlocal definition
            for skill in bound_skills:
                definition = skill_snapshot(skill)
                record("", message, status=status, skill_id=skill.id, skill_key=str(skill.id))
            if not bound_skills:
                record("", message, status=status)
        # A different checklist/version must be evaluated even on an identical image.
        duplicate = _find_near_duplicate_image(db, image) if not skill_ids else None
        if duplicate:
            record(
                "", f"近似页面，跳过重复分析: 已分析过 {duplicate.file_path}", status="skipped",
            )
            return
        context = _analysis_context(image, db)
        # 判断目标页面（对所有 skill 共用一次）
        try:
            with model_purpose("target_validation"):
                is_target, reason = await analyzer.is_target_page(image.file_path, context)
            target_validation = {"is_target": is_target, "reason": reason}
            if not is_target:
                reject("skipped", f"非目标页面，跳过分析: {reason}")
                return
        except Exception as e:
            reject("failed", f"目标页面判断失败: {e}")
            return

        # 没有选择 skill → 使用系统默认内置分析（向后兼容）
        if not skill_ids:
            try:
                design, ops, status = await analyzer.analyze(image.file_path, context=context)
            except Exception as e:
                record("", f"分析失败: {e}", status="failed")
                return
            analysis = record(design or "", ops or "", status=status)
            await _embed_analysis(db, analysis, design, ops)
            return

        # 有选择 skill → 加载 skill 并按每个 skill 执行分析
        skills = [skill for skill in bound_skills if skill.status == "active"]
        for skill in bound_skills:
            if skill.status != "active":
                definition = skill_snapshot(skill)
                record("", "任务绑定的 Skill 已停用，请检查配置", status="failed", skill_id=skill.id, skill_key=str(skill.id))
        if len(bound_skills) != len(set(skill_ids)):
            definition = None
            record("", "任务绑定的部分 Skill 已停用或不存在，请检查配置", status="failed")
        for skill in skills:
            definition = skill_snapshot(skill)
            try:
                if skill.is_system:
                    # 内置 skill：同时写入旧字段 + result_json
                    design, ops, status = await analyzer.analyze(image.file_path, context={**context, "analysis_prompt_override": skill.prompt})
                    result_json = {"design_analysis": design, "ops_analysis": ops} if design and ops else None
                    validate_skill_output(result_json or {}, skill.output_schema_json or {})
                    analysis = record(
                        design or "", ops or "", status=status,
                        skill_id=skill.id, skill_key=f"system_{skill.profile}", result_json=result_json,
                    )
                    await _embed_analysis(db, analysis, design, ops, result_json=result_json)
                else:
                    # 自定义 skill：只写入 result_json
                    with model_purpose(f"skill:{skill.id}"):
                        result, status = await analyzer.analyze_with_skill(image.file_path, skill, context)
                    inspection = None
                    if skill.skill_type == "inspection":
                        with Image.open(_resolve_image_path(image.file_path)) as screenshot:
                            inspection = build_inspection(result, Specification.model_validate(definition["specification_json"]),
                                                          image, calls, definition, screenshot.size)
                    analysis = record(
                        "", "", status=status,
                        skill_id=skill.id, skill_key=str(skill.id), result_json=result,
                        inspection_json=inspection,
                    )
                    await _embed_skill_result(db, analysis, result)
            except Exception as e:
                record(
                    "", f"Skill {skill.name} 分析失败: {e}", status="failed",
                    skill_id=skill.id, skill_key=str(skill.id),
                )
    finally:
        db.close()


async def _embed_analysis(db, analysis, design, ops, result_json=None):
    """为内置分析结果生成 embedding"""
    analysis_id = analysis.id
    combined_text = f"{design or ''}\n{ops or ''}".strip()
    try:
        if combined_text:
            vector = await embedder.embed_single(combined_text)
            crud.create_embedding(db, analysis_id, vector, "combined")
        if design:
            v_design = await embedder.embed_single(design)
            crud.create_embedding(db, analysis_id, v_design, "design")
        if ops:
            v_ops = await embedder.embed_single(ops)
            crud.create_embedding(db, analysis_id, v_ops, "ops")
        crud.update_embedding_status(db, analysis_id, "success")
    except Exception as e:
        db.rollback()
        crud.update_embedding_status(db, analysis_id, "failed", str(e))
        print(f"⚠️ 向量写入失败 analysis={analysis_id}: {e}")


async def _embed_skill_result(db, analysis, result_json):
    """为自定义 skill 结果生成 embedding"""
    if not result_json:
        return
    analysis_id = analysis.id
    import json
    content = analysis.inspection_json.get("checks") if analysis.inspection_json else result_json
    combined_text = json.dumps(content, ensure_ascii=False)
    try:
        if combined_text:
            vector = await embedder.embed_single(combined_text)
            crud.create_embedding(db, analysis_id, vector, "combined")
        crud.update_embedding_status(db, analysis_id, "success")
    except Exception as e:
        db.rollback()
        crud.update_embedding_status(db, analysis_id, "failed", str(e))
        print(f"⚠️ skill 向量写入失败 analysis={analysis_id}: {e}")

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
            analyses=[schemas.AnalysisOut.model_validate(item) for item in image.analyses],
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
    if img.oss_url:
        return RedirectResponse(img.oss_url)
    file_path = analyzer._resolve_image_path(img.file_path)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Image file not found on disk")
    return FileResponse(file_path)


@router.get("/{image_id}/analysis-history")
def analysis_history(image_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    image = _get_owned_image(db, image_id, user)
    return [
        {"revision_id": str(revision.id), "archived_at": revision.archived_at, "analysis": revision.payload_json}
        for analysis in image.analyses for revision in analysis.revisions
    ]

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
