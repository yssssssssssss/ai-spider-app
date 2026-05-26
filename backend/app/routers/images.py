from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from app.database import get_db
from app import crud, schemas
from app.services.llm_analyzer import analyzer
from app.services.embedder import embedder

router = APIRouter(prefix="/images", tags=["images"])

async def _analyze_and_embed(image_id: UUID):
    from app.database import SessionLocal
    db = SessionLocal()
    try:
        image = crud.get_image(db, image_id)
        if not image:
            return
        design, ops, status = await analyzer.analyze(image.file_path)
        analysis = crud.create_analysis(db, image_id, design or "", ops or "")
        analysis.status = status
        db.commit()
        combined_text = f"{design or ''}\n{ops or ''}".strip()
        if combined_text:
            vector = await embedder.embed_single(combined_text)
            crud.create_embedding(db, analysis.id, vector, "combined")
        if design:
            v_design = await embedder.embed_single(design)
            crud.create_embedding(db, analysis.id, v_design, "design")
        if ops:
            v_ops = await embedder.embed_single(ops)
            crud.create_embedding(db, analysis.id, v_ops, "ops")
    finally:
        db.close()

@router.post("", response_model=schemas.ImageOut)
def create_image(image: schemas.ImageCreate, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    db_image = crud.create_image(db, image)
    background_tasks.add_task(_analyze_and_embed, db_image.id)
    return db_image

@router.get("/{image_id}", response_model=schemas.ImageOut)
def get_image(image_id: UUID, db: Session = Depends(get_db)):
    img = crud.get_image(db, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    return img

@router.post("/{image_id}/analyze")
def trigger_analyze(image_id: UUID, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    img = crud.get_image(db, image_id)
    if not img:
        raise HTTPException(status_code=404, detail="Image not found")
    background_tasks.add_task(_analyze_and_embed, image_id)
    return {"message": "Analysis triggered", "image_id": image_id}
