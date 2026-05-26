from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from app import schemas, crud
from app.services.embedder import embedder

router = APIRouter(prefix="/search", tags=["search"])

@router.post("", response_model=list[schemas.SearchResult])
async def search(query: schemas.SearchQuery, db: Session = Depends(get_db)):
    vector = await embedder.embed_single(query.query)
    rows = crud.search_by_embedding(db, vector, limit=query.limit, offset=query.offset)
    results = []
    for emb, analysis, image in rows:
        similarity = 1.0
        results.append(schemas.SearchResult(
            image=schemas.ImageOut.model_validate(image),
            analysis=schemas.AnalysisOut.model_validate(analysis) if analysis else None,
            similarity=similarity
        ))
    return results
