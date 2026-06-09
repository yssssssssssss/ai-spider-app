from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.database import get_db
from app.services.analysis_skills import MAX_SKILL_MARKDOWN_LENGTH, parse_skill_markdown, prepare_skill_update
from app.services.auth import get_current_user, require_roles

router = APIRouter(tags=["analysis-skills"])


def _skill_out(db: Session, skill: models.AnalysisSkill) -> dict:
    owner = crud.get_user(db, skill.owner_id) if skill.owner_id else None
    return {
        "id": skill.id,
        "name": skill.name,
        "instruction_md": skill.instruction_md,
        "owner_id": skill.owner_id,
        "owner_name": (owner.display_name or owner.username) if owner else None,
        "is_official": skill.is_official,
        "status": skill.status,
        "created_at": skill.created_at,
        "updated_at": skill.updated_at,
    }


def _own_editable_skill(db: Session, skill_id: UUID, user: models.User) -> models.AnalysisSkill:
    skill = crud.get_analysis_skill(db, skill_id)
    if not skill:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis skill not found")
    if skill.owner_id != user.id or skill.is_official:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Analysis skill is not editable")
    return skill


@router.get("/analysis-skills", response_model=list[schemas.AnalysisSkillOut])
def list_analysis_skills(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    return [_skill_out(db, skill) for skill in crud.list_visible_analysis_skills(db, user)]


@router.post("/analysis-skills", response_model=schemas.AnalysisSkillOut)
def create_analysis_skill(
    body: schemas.AnalysisSkillCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    parsed = parse_skill_markdown(body.instruction_md, fallback_name=body.name)
    skill = crud.create_analysis_skill(db, owner_id=user.id, **parsed)
    return _skill_out(db, skill)


@router.post("/analysis-skills/upload-md", response_model=schemas.AnalysisSkillUploadOut)
async def upload_analysis_skill_markdown(
    file: UploadFile = File(...),
    _: models.User = Depends(get_current_user),
):
    if not file.filename or not file.filename.endswith(".md"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only .md files are supported")
    content = await file.read(MAX_SKILL_MARKDOWN_LENGTH + 1)
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Markdown must be UTF-8") from exc
    return parse_skill_markdown(text)


@router.patch("/analysis-skills/{skill_id}", response_model=schemas.AnalysisSkillOut)
def update_analysis_skill(
    skill_id: UUID,
    body: schemas.AnalysisSkillUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    current = _own_editable_skill(db, skill_id, user)
    updates = prepare_skill_update(
        current_name=current.name,
        current_instruction_md=current.instruction_md,
        name=body.name,
        instruction_md=body.instruction_md,
        status_value=body.status,
    )
    skill = crud.update_analysis_skill(db, skill_id, **updates)
    return _skill_out(db, skill)


@router.delete("/analysis-skills/{skill_id}", response_model=schemas.AnalysisSkillOut)
def delete_analysis_skill(
    skill_id: UUID,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    _own_editable_skill(db, skill_id, user)
    skill = crud.update_analysis_skill(db, skill_id, status="disabled")
    return _skill_out(db, skill)


@router.get("/admin/analysis-skills", response_model=list[schemas.AnalysisSkillOut])
def admin_list_analysis_skills(
    db: Session = Depends(get_db),
    _: models.User = Depends(require_roles("admin")),
):
    return [_skill_out(db, skill) for skill in crud.list_all_analysis_skills(db)]


@router.post("/admin/analysis-skills", response_model=schemas.AnalysisSkillOut)
def admin_create_analysis_skill(
    body: schemas.AnalysisSkillCreate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_roles("admin")),
):
    parsed = parse_skill_markdown(body.instruction_md, fallback_name=body.name)
    skill = crud.create_analysis_skill(db, owner_id=None, **parsed)
    return _skill_out(db, skill)


@router.patch("/admin/analysis-skills/{skill_id}", response_model=schemas.AnalysisSkillOut)
def admin_update_analysis_skill(
    skill_id: UUID,
    body: schemas.AnalysisSkillUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_roles("admin")),
):
    current = crud.get_analysis_skill(db, skill_id)
    if not current:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis skill not found")
    updates = prepare_skill_update(
        current_name=current.name,
        current_instruction_md=current.instruction_md,
        name=body.name,
        instruction_md=body.instruction_md,
        status_value=body.status,
    )
    if current.is_official and updates.get("name"):
        existing = crud.get_official_analysis_skill_by_name(db, updates["name"], exclude_id=current.id)
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Official analysis skill name already exists")
    try:
        skill = crud.update_analysis_skill(db, skill_id, **updates)
    except IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Official analysis skill name already exists") from exc
    if not skill:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis skill not found")
    return _skill_out(db, skill)


@router.delete("/admin/analysis-skills/{skill_id}", response_model=schemas.AnalysisSkillOut)
def admin_delete_analysis_skill(
    skill_id: UUID,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_roles("admin")),
):
    skill = crud.update_analysis_skill(db, skill_id, status="disabled")
    if not skill:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis skill not found")
    return _skill_out(db, skill)


@router.patch("/admin/analysis-skills/{skill_id}/official", response_model=schemas.AnalysisSkillOut)
def admin_update_analysis_skill_official(
    skill_id: UUID,
    body: schemas.AnalysisSkillOfficialUpdate,
    db: Session = Depends(get_db),
    _: models.User = Depends(require_roles("admin")),
):
    current = crud.get_analysis_skill(db, skill_id)
    if not current:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis skill not found")
    if body.is_official:
        existing = crud.get_official_analysis_skill_by_name(db, current.name, exclude_id=current.id)
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Official analysis skill name already exists")
    try:
        skill = crud.update_analysis_skill(db, skill_id, is_official=body.is_official)
    except IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Official analysis skill name already exists") from exc
    return _skill_out(db, skill)
