from contextlib import contextmanager
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.services import audit_projects as service
from app.services.auth import get_current_user, require_at_least

router = APIRouter(tags=["audit-projects"], dependencies=[Depends(get_current_user)])


def _get_or_404(db: Session, model, object_id: UUID):
    obj = db.get(model, object_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"{model.__name__} not found")
    return obj


@contextmanager
def _service_errors(db: Session):
    try:
        yield
    except (ValueError, LookupError) as exc:
        db.rollback()
        raise HTTPException(status_code=400 if isinstance(exc, ValueError) else 404, detail=str(exc)) from exc


@router.get("/audit-projects", response_model=list[schemas.AuditProjectListOut])
def list_projects(db: Session = Depends(get_db)):
    with _service_errors(db):
        return service.list_projects(db)


@router.post("/audit-projects", response_model=schemas.AuditProjectOut)
def create_project(
    body: schemas.AuditProjectCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    with _service_errors(db):
        project = service.create_project(db, body.name, body.description, user.id)
        db.commit()
        db.refresh(project)
    return project


# Static path must precede /audit-projects/{project_id}.
@router.get("/audit-projects/app-candidates", response_model=list[schemas.AuditAppCandidateOut])
def app_candidates(db: Session = Depends(get_db)):
    with _service_errors(db):
        return service.app_candidates(db)


@router.get("/audit-projects/{project_id}", response_model=schemas.AuditProjectDetailOut)
def project_detail(project_id: UUID, db: Session = Depends(get_db)):
    project = _get_or_404(db, models.AuditProject, project_id)
    with _service_errors(db):
        return service.project_detail(db, project)


@router.patch("/audit-projects/{project_id}", response_model=schemas.AuditProjectOut)
def update_project(
    project_id: UUID,
    body: schemas.AuditProjectUpdate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(require_at_least("operator")),
):
    project = _get_or_404(db, models.AuditProject, project_id)
    with _service_errors(db):
        service.update_project(project, body.model_dump(exclude_unset=True))
        db.commit()
        db.refresh(project)
    return project


@router.delete("/audit-projects/{project_id}", response_model=schemas.AuditDeleteOut)
def delete_project(
    project_id: UUID,
    db: Session = Depends(get_db),
    _user: models.User = Depends(require_at_least("operator")),
):
    project = _get_or_404(db, models.AuditProject, project_id)
    db.delete(project)
    db.commit()
    return {"ok": True}


@router.post("/audit-projects/{project_id}/pages", response_model=schemas.AuditPageOut)
def create_page(
    project_id: UUID,
    body: schemas.AuditPageCreate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(require_at_least("operator")),
):
    project = _get_or_404(db, models.AuditProject, project_id)
    with _service_errors(db):
        page = service.create_page(db, project, body.name, body.business_key)
        db.commit()
        db.refresh(page)
    return page


@router.post("/audit-projects/{project_id}/imports/h5", response_model=schemas.AuditH5ImportOut)
def import_h5(
    project_id: UUID,
    file: UploadFile = File(...),
    venue_ids: str | None = Form(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    project = _get_or_404(db, models.AuditProject, project_id)
    with _service_errors(db):
        result = service.import_h5_upload(db, project, file.file.read(), file.filename or "results.json", venue_ids, user.id)
        db.commit()
    return result


@router.get("/audit-pages/{page_id}", response_model=schemas.AuditPageDetailOut)
def page_detail(page_id: UUID, db: Session = Depends(get_db)):
    page = _get_or_404(db, models.AuditPage, page_id)
    with _service_errors(db):
        return service.page_detail(db, page)


@router.post("/audit-pages/{page_id}/records/app", response_model=schemas.AuditRecordOut)
def add_app_record(
    page_id: UUID,
    body: schemas.AuditAppRecordCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    page = _get_or_404(db, models.AuditPage, page_id)
    with _service_errors(db):
        if body.baseline_record_id is not None:
            service.get_project_record(db, page.project_id, body.baseline_record_id)
        record = service.add_app_record(db, page, body.task_run_id, body.skill_id, body.phase, body.baseline_record_id, user.id)
        db.commit()
        db.refresh(record)
    return record


@router.patch("/audit-records/{record_id}", response_model=schemas.AuditRecordOut)
def update_record(
    record_id: UUID,
    body: schemas.AuditRecordUpdate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(require_at_least("operator")),
):
    record = _get_or_404(db, models.AuditRecord, record_id)
    with _service_errors(db):
        service.update_record(db, record, body.model_dump(exclude_unset=True))
        db.commit()
        db.refresh(record)
    return record


@router.delete("/audit-records/{record_id}", response_model=schemas.AuditDeleteOut)
def delete_record(
    record_id: UUID,
    db: Session = Depends(get_db),
    _user: models.User = Depends(require_at_least("operator")),
):
    record = _get_or_404(db, models.AuditRecord, record_id)
    db.delete(record)
    db.commit()
    return {"ok": True}


@router.get("/audit-records/{post_id}/compare", response_model=schemas.AuditComparisonOut)
def compare_records(post_id: UUID, pre_id: UUID | None = None, db: Session = Depends(get_db)):
    post = _get_or_404(db, models.AuditRecord, post_id)
    with _service_errors(db):
        return service.record_comparison(db, post, pre_id)
