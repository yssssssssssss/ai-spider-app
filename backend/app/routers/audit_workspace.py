from contextlib import contextmanager
import json
import re
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app import models, schemas
from app.database import get_db
from app.services import audit_analytics as analytics, audit_workspace as service
from app.services.auth import get_current_user, require_at_least

router = APIRouter(tags=["audit-workspace"], dependencies=[Depends(get_current_user)])


def _get(db, model, object_id):
    obj = db.get(model, object_id)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} not found")
    return obj


@contextmanager
def _errors(db):
    try:
        yield
    except (ValueError, LookupError) as exc:
        db.rollback()
        raise HTTPException(400 if isinstance(exc, ValueError) else 404, str(exc)) from exc
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(400, "Audit data conflicts with an existing record") from exc


def _name(value):
    if not value or not value.strip():
        raise ValueError("Name is required")
    return value.strip()


def _version_out(version, run_count=0):
    return schemas.AuditVersionOut.model_validate(version).model_copy(update={
        "run_count": run_count, "enabled_rules": sum(r["enabled"] for r in version.rules_json),
    })


def _spec_out(spec, counts):
    versions = [_version_out(v, counts.get(v.id, 0)) for v in sorted(spec.versions, key=lambda v: -v.version)]
    return schemas.AuditSpecOut.model_validate(spec).model_copy(update={
        "versions": versions, "latest_version": versions[0] if versions else None,
    })


def _reference_counts(db):
    return dict(db.query(models.AuditRun.spec_version_id, func.count(models.AuditRun.id))
                .group_by(models.AuditRun.spec_version_id).all())


@router.get("/audit-specs", response_model=list[schemas.AuditSpecOut])
def list_specs(db: Session = Depends(get_db)):
    specs = db.query(models.AuditSpec).options(selectinload(models.AuditSpec.versions)).order_by(
        models.AuditSpec.created_at.desc(), models.AuditSpec.id).all()
    counts = _reference_counts(db)
    return [_spec_out(spec, counts) for spec in specs]


@router.post("/audit-specs", response_model=schemas.AuditSpecOut)
def create_spec(body: schemas.AuditSpecCreate, db: Session = Depends(get_db),
                user: models.User = Depends(require_at_least("operator"))):
    with _errors(db):
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", body.key):
            raise ValueError("Key must be a lowercase slug")
        spec = models.AuditSpec(key=body.key, name=_name(body.name), description=body.description, created_by=user.id)
        db.add(spec)
        db.commit()
        return _spec_out(spec, {})


@router.get("/audit-specs/{spec_id}", response_model=schemas.AuditSpecOut)
def spec_detail(spec_id: UUID, db: Session = Depends(get_db)):
    return _spec_out(_get(db, models.AuditSpec, spec_id), _reference_counts(db))


@router.post("/audit-specs/{spec_id}/versions", response_model=schemas.AuditVersionDetailOut)
def import_version(spec_id: UUID, file: UploadFile = File(...), carrier_scope: str = Form(...),
                   db: Session = Depends(get_db), user: models.User = Depends(require_at_least("operator"))):
    spec = _get(db, models.AuditSpec, spec_id)
    with _errors(db):
        version = service.import_spec_version(db, spec, file.file.read(), carrier_scope, user.id)
        db.commit()
        return _version_detail(db, version)


def _version_detail(db, version):
    base = _version_out(version, db.query(models.AuditRun).filter_by(spec_version_id=version.id).count())
    return {**base.model_dump(), "rules_json": version.rules_json, "source_json": version.source_json}


@router.get("/audit-spec-versions/{version_id}", response_model=schemas.AuditVersionDetailOut)
def version_detail(version_id: UUID, db: Session = Depends(get_db)):
    return _version_detail(db, _get(db, models.AuditSpecVersion, version_id))


@router.get("/audit-runs", response_model=list[schemas.AuditRunOut])
def list_runs(carrier: str | None = None, project_id: UUID | None = None, unassigned: bool = False,
              db: Session = Depends(get_db)):
    with _errors(db):
        if carrier is not None and carrier not in {"h5", "app"}:
            raise ValueError("Carrier must be h5 or app")
        query = db.query(models.AuditRun).options(joinedload(models.AuditRun.spec_version))
        if carrier:
            query = query.filter_by(carrier=carrier)
        if project_id:
            _get(db, models.AuditProject, project_id)
            query = query.filter_by(project_id=project_id)
        if unassigned:
            query = query.filter(models.AuditRun.project_id.is_(None))
        return query.order_by(models.AuditRun.created_at.desc(), models.AuditRun.id).all()


def _venue_ids(value):
    if value is None:
        return None
    # Accept a JSON array or comma-separated IDs, as in the original importer.
    values = json.loads(value) if value.lstrip().startswith("[") else value.split(",")
    if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
        raise ValueError("venue_ids must contain nonempty string IDs")
    return {v.strip() for v in values}


@router.post("/audit-runs/h5", response_model=schemas.AuditRunOut)
def create_h5_run(file: UploadFile = File(...), spec_version_id: UUID = Form(...), name: str = Form(...),
                  venue_ids: str | None = Form(None), project_id: UUID | None = Form(None), phase: str = Form("pre"),
                  db: Session = Depends(get_db), user: models.User = Depends(require_at_least("operator"))):
    version = _get(db, models.AuditSpecVersion, spec_version_id)
    project = _get(db, models.AuditProject, project_id) if project_id else None
    with _errors(db):
        ids = _venue_ids(venue_ids)
        run = service.create_h5_run(db, file.file.read(), file.filename or "results.json", version,
                                    name, phase, ids, project, user.id)
        db.commit()
        return run


@router.post("/audit-runs/app", response_model=schemas.AuditRunOut)
def create_app_run(body: schemas.AuditAppRunCreate, db: Session = Depends(get_db),
                   user: models.User = Depends(require_at_least("operator"))):
    version = _get(db, models.AuditSpecVersion, body.spec_version_id)
    project = _get(db, models.AuditProject, body.project_id) if body.project_id else None
    _get(db, models.TaskRun, body.task_run_id)
    _get(db, models.AnalysisSkill, body.skill_id)
    with _errors(db):
        run = service.create_app_run(db, body.task_run_id, body.skill_id, version, body.name,
                                     body.target_name, body.business_key, body.phase, project, user.id)
        db.commit()
        return run


@router.get("/audit-runs/{run_id}", response_model=schemas.AuditRunDetailOut)
def run_detail(run_id: UUID, outcome: str | None = None, db: Session = Depends(get_db)):
    run = service.load_run(db, run_id)
    if run is None:
        raise HTTPException(404, "AuditRun not found")
    with _errors(db):
        return {**schemas.AuditRunOut.model_validate(run).model_dump(), **analytics.run_cockpit(run, outcome)}


@router.patch("/audit-runs/{run_id}", response_model=schemas.AuditRunOut)
def update_run(run_id: UUID, body: schemas.AuditRunUpdate, db: Session = Depends(get_db),
               _user: models.User = Depends(require_at_least("operator"))):
    run = _get(db, models.AuditRun, run_id)
    changes = body.model_dump(exclude_unset=True)
    with _errors(db):
        if "name" in changes:
            run.name = _name(body.name)
        if "project_id" in changes:
            project = _get(db, models.AuditProject, body.project_id) if body.project_id else None
            service.assign_run(db, run, project)
        db.commit()
        return run


@router.delete("/audit-runs/{run_id}", response_model=schemas.AuditDeleteOut)
def delete_run(run_id: UUID, db: Session = Depends(get_db),
               _user: models.User = Depends(require_at_least("operator"))):
    db.delete(_get(db, models.AuditRun, run_id))
    db.commit()
    return {"ok": True}


@router.get("/audit-runs/{run_id}/targets", response_model=schemas.AuditTargetListOut)
def list_targets(run_id: UUID, page: int = 1, page_size: int = 20, search: str | None = None,
                 outcome: str | None = None, sort: str = "fail", db: Session = Depends(get_db)):
    run = service.load_run(db, run_id)
    if run is None:
        raise HTTPException(404, "AuditRun not found")
    with _errors(db):
        return analytics.target_list(run.targets, page=page, page_size=page_size, search=search, outcome=outcome, sort=sort)


@router.get("/audit-targets/{target_id}", response_model=schemas.AuditTargetOut)
def target_detail(target_id: UUID, db: Session = Depends(get_db)):
    return _get(db, models.AuditTarget, target_id)


@router.patch("/audit-targets/{target_id}", response_model=schemas.AuditTargetOut)
def update_target(target_id: UUID, body: schemas.AuditTargetUpdate, db: Session = Depends(get_db),
                  _user: models.User = Depends(require_at_least("operator"))):
    target = _get(db, models.AuditTarget, target_id)
    baseline = _get(db, models.AuditTarget, body.baseline_target_id) if body.baseline_target_id else None
    if baseline and (target.run.project_id is None or target.run.project_id != baseline.run.project_id
                     or not target.business_key or target.business_key != baseline.business_key):
        raise HTTPException(404, "Baseline not found for this project page")
    with _errors(db):
        service.set_target_baseline(db, target, baseline)
        db.commit()
        return target


@router.get("/audit-projects", response_model=list[schemas.AuditProjectListOut])
def list_projects(db: Session = Depends(get_db)):
    projects = db.query(models.AuditProject).order_by(models.AuditProject.created_at.desc(), models.AuditProject.id).all()
    runs = db.query(models.AuditRun).options(joinedload(models.AuditRun.spec_version), selectinload(models.AuditRun.targets)).filter(
        models.AuditRun.project_id.isnot(None)).all()
    by_project = {}
    for run in runs:
        by_project.setdefault(run.project_id, []).append(run)
    result = []
    for project in projects:
        cockpit = analytics.project_cockpit(by_project.get(project.id, []))
        result.append({**schemas.AuditProjectOut.model_validate(project).model_dump(),
                       **{key: cockpit[key] for key in ("page_count", "run_count", "stages")}})
    return result


@router.post("/audit-projects", response_model=schemas.AuditProjectOut)
def create_project(body: schemas.AuditProjectCreate, db: Session = Depends(get_db),
                   user: models.User = Depends(require_at_least("operator"))):
    with _errors(db):
        project = models.AuditProject(name=_name(body.name), description=body.description, created_by=user.id)
        db.add(project)
        db.commit()
        return project


@router.get("/audit-projects/{project_id}", response_model=schemas.AuditProjectDetailOut)
def project_detail(project_id: UUID, db: Session = Depends(get_db)):
    project = _get(db, models.AuditProject, project_id)
    return {**schemas.AuditProjectOut.model_validate(project).model_dump(),
            **analytics.project_cockpit(service.load_project_runs(db, project_id))}


@router.patch("/audit-projects/{project_id}", response_model=schemas.AuditProjectOut)
def update_project(project_id: UUID, body: schemas.AuditProjectUpdate, db: Session = Depends(get_db),
                   _user: models.User = Depends(require_at_least("operator"))):
    project = _get(db, models.AuditProject, project_id)
    with _errors(db):
        if "name" in body.model_fields_set:
            project.name = _name(body.name)
        if "description" in body.model_fields_set:
            project.description = body.description
        db.commit()
        return project


@router.delete("/audit-projects/{project_id}", response_model=schemas.AuditDeleteOut)
def delete_project(project_id: UUID, db: Session = Depends(get_db),
                   _user: models.User = Depends(require_at_least("operator"))):
    project = _get(db, models.AuditProject, project_id)
    # Explicitly detach so both directions of baseline links are cleared.
    for run in service.load_project_runs(db, project_id):
        service.assign_run(db, run, None)
    db.delete(project)
    db.commit()
    return {"ok": True}


@router.get("/audit-projects/{project_id}/matrix", response_model=schemas.AuditMatrixOut)
def project_matrix(project_id: UUID, db: Session = Depends(get_db)):
    _get(db, models.AuditProject, project_id)
    return analytics.project_matrix(service.load_project_runs(db, project_id))


@router.get("/audit-projects/{project_id}/pages/{page_key:path}", response_model=schemas.AuditPageLifelineOut)
def page_lifeline(project_id: UUID, page_key: str, db: Session = Depends(get_db)):
    _get(db, models.AuditProject, project_id)
    with _errors(db):
        return analytics.page_lifeline(service.load_project_runs(db, project_id), page_key)


@router.get("/audit-app-candidates", response_model=list[schemas.AuditAppCandidateOut])
def app_candidates(db: Session = Depends(get_db)):
    return service.app_candidates(db)
