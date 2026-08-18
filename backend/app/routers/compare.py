import os
import re
import shutil
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.config import settings
from app.database import get_db
from app.services.auth import data_scope_user_id, get_current_user, require_at_least
from app.services.compare_analyzer import compare_analyzer

router = APIRouter(prefix="/compare", tags=["compare"])

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_REPORT_ASSETS = 10
MAX_FOCUS_QUESTION_LENGTH = 1000


def _clean_name(value: str | None, fallback: str) -> str:
    name = re.sub(r"\s+", " ", str(value or "").strip())
    return name[:120] or fallback


def _clean_text(value: str | None, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:limit]


def _asset_display_name(image: models.Image) -> str:
    parts = [
        image.source_app or (image.task.target_app if image.task else None),
        image.scenario or (image.task.target_scenario if image.task else None),
        str(image.id)[:8],
    ]
    return "-".join(str(part).strip() for part in parts if part)


def _get_visible_image(db: Session, image_id: UUID, user: models.User) -> models.Image:
    scope_user_id = data_scope_user_id(user)
    image = crud.get_image_for_user(db, image_id, scope_user_id) if scope_user_id else crud.get_image(db, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    return image


def _get_owned_asset(db: Session, asset_id: UUID, user: models.User) -> models.ComparisonAsset:
    asset = db.query(models.ComparisonAsset).filter(models.ComparisonAsset.id == asset_id).first()
    if not asset or asset.status == "deleted":
        raise HTTPException(status_code=404, detail="Comparison asset not found")
    scope_user_id = data_scope_user_id(user)
    if scope_user_id and asset.created_by != scope_user_id:
        raise HTTPException(status_code=404, detail="Comparison asset not found")
    return asset


def _skill_out(skill: models.ComparisonSkill) -> schemas.ComparisonSkillOut:
    return schemas.ComparisonSkillOut.model_validate(skill)


def _get_active_skill(db: Session, skill_id: UUID) -> models.ComparisonSkill:
    skill = db.query(models.ComparisonSkill).filter(models.ComparisonSkill.id == skill_id).first()
    if not skill or skill.status != "active":
        raise HTTPException(status_code=404, detail="Comparison skill not found")
    return skill


@router.get("/assets", response_model=list[schemas.ComparisonAssetOut])
def list_assets(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    q = db.query(models.ComparisonAsset).filter(models.ComparisonAsset.status == "active")
    scope_user_id = data_scope_user_id(user)
    if scope_user_id:
        q = q.filter(models.ComparisonAsset.created_by == scope_user_id)
    return q.order_by(models.ComparisonAsset.created_at.desc()).limit(500).all()


@router.get("/assets/{asset_id}/file")
def get_asset_file(
    asset_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    asset = _get_owned_asset(db, asset_id, user)
    if asset.image_id:
        image = asset.image
        if image and image.oss_url:
            from fastapi.responses import RedirectResponse

            return RedirectResponse(image.oss_url)
        file_path = image.file_path if image else None
    else:
        file_path = asset.file_path
    if not file_path:
        raise HTTPException(status_code=404, detail="Asset file not found")
    path = Path(file_path)
    if not path.is_absolute():
        path = Path(settings.PROJECT_ROOT) / path
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Asset file not found")
    return FileResponse(path)


@router.post("/assets/from-image", response_model=schemas.ComparisonAssetOut)
def create_asset_from_image(
    body: schemas.ComparisonAssetCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    image = _get_visible_image(db, body.image_id, user)
    existing = (
        db.query(models.ComparisonAsset)
        .filter(models.ComparisonAsset.image_id == image.id)
        .filter(models.ComparisonAsset.created_by == user.id)
        .filter(models.ComparisonAsset.status == "active")
        .first()
    )
    if existing:
        return existing
    asset = models.ComparisonAsset(
        source_type="image",
        image_id=image.id,
        display_name=_asset_display_name(image),
        source_app=image.source_app or (image.task.target_app if image.task else None),
        scenario=image.scenario or (image.task.target_scenario if image.task else None),
        notes=body.notes,
        created_by=user.id,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.post("/assets/upload", response_model=schemas.ComparisonAssetOut)
def upload_asset(
    file: UploadFile = File(...),
    display_name: str | None = Form(None),
    source_app: str | None = Form(None),
    scenario: str | None = Form(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported image format")
    folder = Path(settings.PROJECT_ROOT) / "data" / "comparison_uploads" / str(user.id)
    folder.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4()}{ext}"
    path = folder / filename
    with path.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    asset = models.ComparisonAsset(
        source_type="upload",
        file_path=os.path.relpath(path, settings.PROJECT_ROOT),
        display_name=_clean_name(display_name or file.filename, filename),
        source_app=_clean_name(source_app, "") or None,
        scenario=_clean_name(scenario, "") or None,
        created_by=user.id,
    )
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.post("/basket", response_model=schemas.ComparisonBasketItemOut)
def add_basket_item(
    body: schemas.ComparisonBasketItemCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    asset = _get_owned_asset(db, body.asset_id, user)
    existing = (
        db.query(models.ComparisonBasketItem)
        .filter(models.ComparisonBasketItem.user_id == user.id)
        .filter(models.ComparisonBasketItem.asset_id == asset.id)
        .first()
    )
    if existing:
        return existing
    item = models.ComparisonBasketItem(user_id=user.id, asset_id=asset.id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/basket", response_model=list[schemas.ComparisonBasketItemOut])
def list_basket_items(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return (
        db.query(models.ComparisonBasketItem)
        .join(models.ComparisonAsset, models.ComparisonBasketItem.asset_id == models.ComparisonAsset.id)
        .filter(models.ComparisonBasketItem.user_id == user.id)
        .filter(models.ComparisonAsset.status == "active")
        .order_by(models.ComparisonBasketItem.created_at.desc())
        .all()
    )


@router.delete("/basket/{item_id}")
def delete_basket_item(
    item_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    item = (
        db.query(models.ComparisonBasketItem)
        .filter(models.ComparisonBasketItem.id == item_id)
        .filter(models.ComparisonBasketItem.user_id == user.id)
        .first()
    )
    if item:
        db.delete(item)
        db.commit()
    return {"ok": True}


@router.delete("/basket")
def clear_basket(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    db.query(models.ComparisonBasketItem).filter(models.ComparisonBasketItem.user_id == user.id).delete()
    db.commit()
    return {"ok": True}


@router.get("/reports", response_model=list[schemas.ComparisonReportOut])
def list_reports(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    q = db.query(models.ComparisonReport)
    scope_user_id = data_scope_user_id(user)
    if scope_user_id:
        q = q.filter(models.ComparisonReport.created_by == scope_user_id)
    return q.order_by(models.ComparisonReport.created_at.desc()).limit(20).all()


@router.post("/reports", response_model=schemas.ComparisonReportOut)
async def create_report(
    body: schemas.ComparisonReportCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    if not body.asset_ids:
        raise HTTPException(status_code=400, detail="Select at least one comparison asset")
    asset_ids = list(dict.fromkeys(body.asset_ids))
    if len(asset_ids) > MAX_REPORT_ASSETS:
        raise HTTPException(status_code=400, detail=f"Select at most {MAX_REPORT_ASSETS} comparison assets")
    assets = [_get_owned_asset(db, asset_id, user) for asset_id in asset_ids]
    skill = _get_active_skill(db, body.skill_id)
    focus_question = _clean_text(body.focus_question, MAX_FOCUS_QUESTION_LENGTH) or None
    report = models.ComparisonReport(
        asset_ids_json=[str(asset.id) for asset in assets],
        skill_id=skill.id,
        skill_name=skill.name,
        skill_version=skill.version,
        focus_question=focus_question,
        status="running",
        created_by=user.id,
    )
    db.add(report)
    db.commit()
    db.refresh(report)

    try:
        report.report = await compare_analyzer.generate_report(assets, skill, focus_question)
        report.status = "success"
        report.error = None
    except Exception as exc:
        report.status = "failed"
        report.error = str(exc)[:1000]
    report.completed_at = models.utc_now()
    db.commit()
    db.refresh(report)
    return report


@router.get("/skills", response_model=list[schemas.ComparisonSkillOut])
def list_skills(
    include_deleted: bool = False,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    q = db.query(models.ComparisonSkill)
    if not include_deleted:
        q = q.filter(models.ComparisonSkill.status != "deleted")
    return q.order_by(models.ComparisonSkill.updated_at.desc()).all()


@router.post("/skills", response_model=schemas.ComparisonSkillOut)
def create_skill(
    body: schemas.ComparisonSkillCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    if not body.name.strip() or not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Skill name and prompt are required")
    skill = models.ComparisonSkill(
        name=_clean_name(body.name, "未命名 Skill"),
        description=body.description,
        scenario_tags_json=body.scenario_tags_json or [],
        prompt=body.prompt.strip(),
        output_schema_json=body.output_schema_json or {},
        status=body.status if body.status in {"active", "disabled"} else "active",
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return _skill_out(skill)


@router.patch("/skills/{skill_id}", response_model=schemas.ComparisonSkillOut)
def update_skill(
    skill_id: UUID,
    body: schemas.ComparisonSkillUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    skill = db.query(models.ComparisonSkill).filter(models.ComparisonSkill.id == skill_id).first()
    if not skill or skill.status == "deleted":
        raise HTTPException(status_code=404, detail="Skill not found")
    if body.name is not None:
        skill.name = _clean_name(body.name, "未命名 Skill")
    if body.description is not None:
        skill.description = body.description
    if body.scenario_tags_json is not None:
        skill.scenario_tags_json = body.scenario_tags_json
    if body.prompt is not None:
        if not body.prompt.strip():
            raise HTTPException(status_code=400, detail="Skill prompt is required")
        skill.prompt = body.prompt.strip()
        skill.version += 1
    if body.output_schema_json is not None:
        skill.output_schema_json = body.output_schema_json
    if body.status is not None:
        if body.status not in {"active", "disabled"}:
            raise HTTPException(status_code=400, detail="Invalid skill status")
        skill.status = body.status
    skill.updated_by = user.id
    db.commit()
    db.refresh(skill)
    return _skill_out(skill)


@router.post("/skills/upload", response_model=schemas.ComparisonSkillOut)
def upload_skill(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    filename = file.filename or "uploaded-skill.md"
    if Path(filename).suffix.lower() not in {".md", ".txt"}:
        raise HTTPException(status_code=400, detail="Only Markdown or text skill files are supported")
    content = file.file.read().decode("utf-8", errors="replace").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Skill file is empty")
    name = Path(filename).stem.replace("_", " ").replace("-", " ")
    skill = models.ComparisonSkill(
        name=_clean_name(name, "上传 Skill"),
        description="由 Markdown 上传创建",
        scenario_tags_json=[],
        prompt=content,
        output_schema_json={},
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return _skill_out(skill)


@router.delete("/skills/{skill_id}")
def delete_skill(
    skill_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    skill = db.query(models.ComparisonSkill).filter(models.ComparisonSkill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    skill.status = "deleted"
    skill.updated_by = user.id
    db.commit()
    return {"ok": True}
