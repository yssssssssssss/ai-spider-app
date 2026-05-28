from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import httpx
from app.database import get_db
from app import schemas, crud
from app.services.embedder import embedder

router = APIRouter(prefix="/search", tags=["search"])

@router.post("", response_model=list[schemas.SearchResult])
async def search(query: schemas.SearchQuery, db: Session = Depends(get_db)):
    try:
        vector = await embedder.embed_single(query.query)
        rows = crud.search_by_embedding(db, vector, limit=query.limit, offset=query.offset)
        return [
            schemas.SearchResult(
                image=schemas.ImageOut.model_validate(image),
                analysis=schemas.AnalysisOut.model_validate(analysis) if analysis else None,
                similarity=None,
            )
            for _, analysis, image in rows
        ]
    except (RuntimeError, httpx.HTTPError) as e:
        print(f"⚠️ 向量搜索失败，降级为文本搜索: {e}")

    rows = crud.search_by_text(db, query.query, limit=query.limit, offset=query.offset)
    results = []
    for analysis, image in rows:
        results.append(schemas.SearchResult(
            image=schemas.ImageOut.model_validate(image),
            analysis=schemas.AnalysisOut.model_validate(analysis) if analysis else None,
            similarity=None  # 仅按相关性排序，不显示具体数值
        ))
    return results
