from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from dataclasses import asdict
from app.database import get_db
from app import crud, schemas, models
from app.services.auth import get_current_user
from app.services.long_image_intent import parse_long_image_intent_with_llm

router = APIRouter(prefix="/requests", tags=["requests"])

@router.post("", response_model=schemas.RequestOut)
def create_request(req: schemas.RequestCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return crud.create_request(db, req, user_id=str(user.id))


@router.post("/long-image-intent", response_model=schemas.LongImageIntentOut)
def parse_request_long_image_intent(body: schemas.LongImageIntentParseRequest, _: models.User = Depends(get_current_user)):
    text = " ".join([
        body.text or "",
        body.target_app or "",
        body.target_scenario or "",
        "、".join(body.keywords or []),
        body.description or "",
    ])
    return asdict(parse_long_image_intent_with_llm(text))


@router.get("/{request_id}", response_model=schemas.RequestOut)
def get_request(request_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    r = crud.get_request_for_user(db, request_id, user.id)
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    return r
