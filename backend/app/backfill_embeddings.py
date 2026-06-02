import argparse
import asyncio
import os
import sys

from sqlalchemy.orm import Session


CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
sys.path.insert(0, BACKEND_DIR)

from app import crud, models  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.services.embedder import embedder  # noqa: E402


def _analysis_text(analysis: models.Analysis) -> dict[str, str]:
    texts = {}
    combined = f"{analysis.design_analysis or ''}\n{analysis.ops_analysis or ''}".strip()
    if combined:
        texts["combined"] = combined
    if analysis.design_analysis:
        texts["design"] = analysis.design_analysis
    if analysis.ops_analysis:
        texts["ops"] = analysis.ops_analysis
    return texts


def _pending_analyses(db: Session, limit: int) -> list[models.Analysis]:
    return (
        db.query(models.Analysis)
        .filter(models.Analysis.status.in_(("success", "partial")))
        .filter(models.Analysis.embedding_status != "success")
        .order_by(models.Analysis.analyzed_at.desc().nullslast())
        .limit(limit)
        .all()
    )


async def backfill_embeddings(limit: int, dry_run: bool) -> int:
    if not dry_run:
        health = await embedder.probe()
        if not health.get("ok"):
            raise RuntimeError(f"Embedding service is not ready: {health.get('error')}")

    db = SessionLocal()
    count = 0
    try:
        analyses = _pending_analyses(db, limit)
        for analysis in analyses:
            texts = _analysis_text(analysis)
            if dry_run:
                print(f"DRY-RUN analysis={analysis.id} chunks={','.join(texts)}")
                count += 1
                continue
            try:
                for content_type, text in texts.items():
                    vector = await embedder.embed_single(text)
                    crud.create_embedding(db, analysis.id, vector, content_type)
                crud.update_embedding_status(db, analysis.id, "success")
                print(f"OK analysis={analysis.id}")
                count += 1
            except Exception as exc:
                crud.update_embedding_status(db, analysis.id, "failed", str(exc))
                print(f"FAILED analysis={analysis.id} error={exc}")
        return count
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Backfill embeddings for existing analysis rows.")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--run", action="store_true", help="Write embeddings. Default is dry-run.")
    args = parser.parse_args()
    count = asyncio.run(backfill_embeddings(limit=args.limit, dry_run=not args.run))
    print(f"processed={count}")


if __name__ == "__main__":
    main()
