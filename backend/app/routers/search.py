from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import httpx
from app.database import get_db
from app import schemas, crud, models
from app.services.embedder import embedder
from app.services.auth import data_scope_user_id, get_current_user

router = APIRouter(prefix="/search", tags=["search"])

@router.post("", response_model=list[schemas.SearchResult])
async def search(query: schemas.SearchQuery, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    scope_user_id = data_scope_user_id(user)
    try:
        vector = await embedder.embed_single(query.query)
        rows = crud.search_by_embedding(db, vector, limit=query.limit, offset=query.offset, user_id=scope_user_id)
        return [
            schemas.SearchResult(
                image=schemas.ImageOut.model_validate(image),
                analysis=schemas.AnalysisOut.model_validate(analysis) if analysis else None,
                similarity=None,
                search_mode="vector",
            )
            for _, analysis, image in rows
        ]
    except (RuntimeError, httpx.HTTPError) as e:
        print(f"⚠️ 向量搜索失败，降级为文本搜索: {e}")

    rows = crud.search_by_text(db, query.query, limit=query.limit, offset=query.offset, user_id=scope_user_id)
    results = []
    for analysis, image in rows:
        results.append(schemas.SearchResult(
            image=schemas.ImageOut.model_validate(image),
            analysis=schemas.AnalysisOut.model_validate(analysis) if analysis else None,
            similarity=None,  # 仅按相关性排序，不显示具体数值
            search_mode="text",
        ))
    return results
