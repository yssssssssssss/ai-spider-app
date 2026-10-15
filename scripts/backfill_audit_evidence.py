"""Attach report-referenced H5 images to an existing audit run."""
import argparse
import json
from pathlib import Path
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=UUID)
    parser.add_argument("--source", required=True, type=Path, help="Run directory or zip, with results.json for legacy runs")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    from app import models
    from app.database import SessionLocal
    from app.services.audit_evidence import DirectoryEvidenceSource, ZipEvidenceSource, attach_run_evidence

    try:
        source_type = DirectoryEvidenceSource if args.source.is_dir() else ZipEvidenceSource
        with SessionLocal() as db, source_type(args.source) as source:
            query = db.query(models.AuditRun).filter_by(id=args.run)
            run = (query if args.dry_run else query.with_for_update()).first()
            if run is None:
                raise ValueError("Audit run not found")
            stats = attach_run_evidence(db, run, source, dry_run=args.dry_run)
            if not args.dry_run:
                db.commit()
            print(json.dumps(stats, ensure_ascii=False))
    except (ValueError, OSError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
