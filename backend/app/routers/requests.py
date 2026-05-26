from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database import get_db
from app import crud, schemas

router = APIRouter(prefix="/requests", tags=["requests"])

@router.post("", response_model=schemas.RequestOut)
def create_request(req: schemas.RequestCreate, db: Session = Depends(get_db)):
    return crud.create_request(db, req)

@router.get("/{request_id}", response_model=schemas.RequestOut)
def get_request(request_id: UUID, db: Session = Depends(get_db)):
    r = crud.get_request(db, request_id)
    if not r:
        raise HTTPException(status_code=404, detail="Request not found")
    return r
