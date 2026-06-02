from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database import get_db
from app import crud, schemas, models
from app.services.auth import get_current_user

router = APIRouter(prefix="/requests", tags=["requests"])

@router.post("", response_model=schemas.RequestOut)
def create_request(req: schemas.RequestCreate, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return crud.create_request(db, req, user_id=str(user.id))

@router.get("/{request_id}", response_model=schemas.RequestOut)
def get_request(request_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    r = crud.get_request_for_user(db, request_id, user.id)
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    return r
