from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database import get_db
from app import crud, schemas, models
from app.services.analysis_skills import build_skill_snapshots
from app.services.auth import get_current_user
from app.services.jd_comparison import normalize_comparison_config
from app.services.request_interpreter import interpret_request_text

router = APIRouter(prefix="/requests", tags=["requests"])


@router.post("/interpret", response_model=schemas.RequestInterpretOut)
async def interpret_request(req: schemas.RequestInterpretIn, _: models.User = Depends(get_current_user)):
    return await interpret_request_text(req.natural_language)


@router.post("", response_model=schemas.RequestOut)
def create_request(req: schemas.RequestCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    snapshots = build_skill_snapshots(db, req.analysis_skill_ids, user)
    comparison_config = None
    if req.compare_jd_enabled:
        if req.schedule_enabled:
            raise HTTPException(status_code=400, detail="JD comparison only supports one-off collection requests")
        comparison_config = normalize_comparison_config(req.comparison)
    return crud.create_request(
        db,
        req,
        user_id=str(user.id),
        analysis_skill_snapshots=snapshots,
        comparison_config=comparison_config,
    )

@router.get("/{request_id}", response_model=schemas.RequestOut)
def get_request(request_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    r = crud.get_request_for_user(db, request_id, user.id)
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    return r
