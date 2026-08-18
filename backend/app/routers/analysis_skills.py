import re
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services.auth import get_current_user, require_at_least

router = APIRouter(prefix="/admin/analysis-skills", tags=["analysis-skills"])


def _clean_name(value: str | None, fallback: str) -> str:
    name = re.sub(r"\s+", " ", str(value or "").strip())
    return name[:120] or fallback


@router.get("", response_model=list[schemas.AnalysisSkillOut])
def list_skills(
    profile: str | None = None,
    include_deleted: bool = False,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    q = db.query(models.AnalysisSkill)
    if profile:
        q = q.filter(models.AnalysisSkill.profile == profile)
    if not include_deleted:
        q = q.filter(models.AnalysisSkill.status != "deleted")
    return q.order_by(models.AnalysisSkill.updated_at.desc()).all()


@router.get("/{skill_id}", response_model=schemas.AnalysisSkillOut)
def get_skill(
    skill_id: UUID,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    skill = db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id == skill_id).first()
    if not skill or skill.status == "deleted":
        raise HTTPException(status_code=404, detail="Analysis skill not found")
    return skill


@router.post("", response_model=schemas.AnalysisSkillOut)
def create_skill(
    body: schemas.AnalysisSkillCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    if not body.name.strip() or not body.prompt.strip():
        raise HTTPException(status_code=400, detail="Skill name and prompt are required")
    skill = models.AnalysisSkill(
        name=_clean_name(body.name, "未命名 Skill"),
        description=body.description,
        prompt=body.prompt.strip(),
        output_schema_json=body.output_schema_json or {},
        scenario_tags_json=body.scenario_tags_json or [],
        profile=body.profile or "default",
        skill_type=body.skill_type or "analysis",
        status=body.status if body.status in {"active", "disabled"} else "active",
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


@router.patch("/{skill_id}", response_model=schemas.AnalysisSkillOut)
def update_skill(
    skill_id: UUID,
    body: schemas.AnalysisSkillUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    skill = db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id == skill_id).first()
    if not skill or skill.status == "deleted":
        raise HTTPException(status_code=404, detail="Analysis skill not found")
    if body.name is not None:
        skill.name = _clean_name(body.name, "未命名 Skill")
    if body.description is not None:
        skill.description = body.description
    if body.prompt is not None:
        if not body.prompt.strip():
            raise HTTPException(status_code=400, detail="Skill prompt is required")
        skill.prompt = body.prompt.strip()
        skill.version += 1
    if body.output_schema_json is not None:
        skill.output_schema_json = body.output_schema_json
    if body.scenario_tags_json is not None:
        skill.scenario_tags_json = body.scenario_tags_json
    if body.profile is not None:
        skill.profile = body.profile
    if body.skill_type is not None:
        skill.skill_type = body.skill_type
    if body.status is not None:
        if skill.is_system and body.status != "active":
            raise HTTPException(status_code=400, detail="System skill cannot be disabled")
        if body.status not in {"active", "disabled"}:
            raise HTTPException(status_code=400, detail="Invalid skill status")
        skill.status = body.status
    skill.updated_by = user.id
    db.commit()
    db.refresh(skill)
    return skill


@router.delete("/{skill_id}")
def delete_skill(
    skill_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    skill = db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id == skill_id).first()
    if not skill:
        raise HTTPException(status_code=404, detail="Analysis skill not found")
    if skill.is_system:
        raise HTTPException(status_code=400, detail="System skill cannot be deleted")
    skill.status = "deleted"
    skill.updated_by = user.id
    db.commit()
    return {"ok": True}


@router.post("/{skill_id}/toggle", response_model=schemas.AnalysisSkillOut)
def toggle_skill(
    skill_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    skill = db.query(models.AnalysisSkill).filter(models.AnalysisSkill.id == skill_id).first()
    if not skill or skill.status == "deleted":
        raise HTTPException(status_code=404, detail="Analysis skill not found")
    if skill.is_system:
        raise HTTPException(status_code=400, detail="System skill cannot be toggled")
    skill.status = "disabled" if skill.status == "active" else "active"
    skill.updated_by = user.id
    db.commit()
    db.refresh(skill)
    return skill


@router.post("/upload", response_model=schemas.AnalysisSkillOut)
def upload_skill(
    file: UploadFile = File(...),
    profile: str = "default",
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    filename = file.filename or "uploaded-skill.md"
    if Path(filename).suffix.lower() not in {".md", ".txt"}:
        raise HTTPException(status_code=400, detail="Only Markdown or text skill files are supported")
    content = file.file.read().decode("utf-8", errors="replace").strip()
    if not content:
        raise HTTPException(status_code=400, detail="Skill file is empty")
    # 解析一级标题作为名称
    name = Path(filename).stem.replace("_", " ").replace("-", " ")
    lines = content.splitlines()
    if lines and lines[0].startswith("# "):
        name = lines[0].lstrip("# ").strip()
    skill = models.AnalysisSkill(
        name=_clean_name(name, "上传 Skill"),
        description="由 Markdown 上传创建",
        prompt=content,
        output_schema_json={},
        scenario_tags_json=[],
        profile=profile,
        skill_type="analysis",
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill