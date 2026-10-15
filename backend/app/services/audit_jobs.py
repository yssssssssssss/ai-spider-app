"""Audit execution lifecycle. Executors share the caller's transaction and never commit."""
from typing import Protocol
from uuid import UUID

from sqlalchemy.orm import Session

from app import models
from app.services.audit_workspace import CARRIER_SCOPES, assign_run

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
ACTIVE_STATUSES = frozenset({"queued", "running", "needs_action", "ingesting"})
TRANSITIONS = {
    "queued": {"running", "failed", "cancelled"},
    "running": {"needs_action", "ingesting", "failed", "cancelled"},
    "needs_action": {"running", "failed", "cancelled"},
    "ingesting": {"completed", "failed", "cancelled"},
}


class InvalidJobTransition(Exception):
    """The requested action conflicts with the job's current state."""


class AuditExecutor(Protocol):
    """resume observes running; cancel cleans up before the service marks cancelled."""
    def availability(self, spec_version: models.AuditSpecVersion) -> tuple[bool, str | None]: ...
    def start(self, db: Session, job: models.AuditJob) -> None: ...
    def reconcile(self, db: Session, job: models.AuditJob) -> None: ...
    def resume(self, db: Session, job: models.AuditJob) -> None: ...
    def cancel(self, db: Session, job: models.AuditJob) -> None: ...


_executors: dict[str, AuditExecutor] = {}


def register_executor(carrier: str, executor: AuditExecutor) -> None:
    if carrier not in {"h5", "app"}:
        raise ValueError("Carrier must be h5 or app")
    _executors[carrier] = executor


def executor_availability(spec_version: models.AuditSpecVersion, carrier: str) -> tuple[bool, str | None]:
    if carrier not in {"h5", "app"}:
        raise ValueError("Carrier must be h5 or app")
    executor = _executors.get(carrier)
    if executor is None:
        return False, "该载体的执行器尚未接入"
    if carrier not in CARRIER_SCOPES.get(spec_version.carrier_scope, []):
        return False, f"规范版本不支持 {carrier} 载体"
    if carrier == "h5" and spec_version.source_json.get("audit_mode") != "h5_v2":
        return False, "H5 执行仅支持 audit_mode=h5_v2 的规范"
    return executor.availability(spec_version)


def transition_job(job: models.AuditJob, status: str, *, status_detail: str | None = None,
                   error: str | None = None) -> None:
    if status not in TRANSITIONS.get(job.status, set()):
        raise InvalidJobTransition(f"Cannot transition audit job from {job.status} to {status}")
    job.status = status
    job.status_detail = status_detail
    job.error = error
    if status in TERMINAL_STATUSES:
        job.finished_at = models.utc_now()


def create_job(db: Session, *, name: str, carrier: str, phase: str, spec_version_id: UUID,
               project_id: UUID | None = None, input: dict | None = None,
               user_id: UUID | None = None) -> models.AuditJob:
    if not name or not name.strip():
        raise ValueError("Name is required")
    if phase not in {"pre", "post"}:
        raise ValueError("Phase must be pre or post")
    version = db.get(models.AuditSpecVersion, spec_version_id)
    if version is None:
        raise ValueError("Spec version not found")
    if carrier not in CARRIER_SCOPES.get(version.carrier_scope, []):
        raise ValueError(f"规范版本不支持 {carrier} 载体")
    if project_id is not None and db.get(models.AuditProject, project_id) is None:
        raise ValueError("Project not found")
    available, reason = executor_availability(version, carrier)
    if not available:
        raise ValueError(reason)
    job = models.AuditJob(name=name.strip(), carrier=carrier, phase=phase, spec_version_id=version.id,
                          project_id=project_id, input_json=input or {}, created_by=user_id,
                          status="queued")
    db.add(job)
    db.flush()
    _executors[carrier].start(db, job)
    db.flush()
    return job


def _lock_job(db: Session, job_id: UUID) -> models.AuditJob:
    # Refresh the identity map after acquiring the lock: another reader may have completed it.
    job = db.query(models.AuditJob).filter_by(id=job_id).with_for_update().populate_existing().one_or_none()
    if job is None:
        raise LookupError("AuditJob not found")
    return job


def reconcile_job(db: Session, job: models.AuditJob) -> models.AuditJob:
    job = _lock_job(db, job.id)
    executor = _executors.get(job.carrier)
    if job.status in ACTIVE_STATUSES and executor is not None:
        executor.reconcile(db, job)
        db.flush()
    return job


def continue_job(db: Session, job: models.AuditJob) -> models.AuditJob:
    job = _lock_job(db, job.id)
    if job.status != "needs_action":
        raise InvalidJobTransition("Only jobs needing action can continue")
    executor = _executors.get(job.carrier)
    if executor is None:
        raise ValueError("该载体的执行器尚未接入")
    transition_job(job, "running")
    executor.resume(db, job)
    db.flush()
    return job


def cancel_job(db: Session, job: models.AuditJob) -> models.AuditJob:
    job = _lock_job(db, job.id)
    if job.status in TERMINAL_STATUSES:
        raise InvalidJobTransition("Finished audit jobs cannot be cancelled")
    executor = _executors.get(job.carrier)
    if executor is not None:
        executor.cancel(db, job)
    transition_job(job, "cancelled")
    db.flush()
    return job


def recapture_failed(db: Session, job: models.AuditJob, *, user_id: UUID) -> models.AuditJob:
    job = _lock_job(db, job.id)
    if job.carrier != "h5" or job.status not in {"completed", "failed"}:
        raise InvalidJobTransition("仅已完成或失败的 H5 任务可重采")
    blocked = (job.executor_ref_json.get("summary") or {}).get("blocked_venue_ids")
    if not blocked:
        raise InvalidJobTransition("没有被闸门拦截的会场")
    data = {key: job.input_json[key] for key in ("catalog_url", "catalog_dir") if key in job.input_json}
    data.update(venue_ids=list(blocked), force_recapture=True)
    return create_job(db, name=job.name + " · 重采", carrier="h5", phase=job.phase,
                      spec_version_id=job.spec_version_id, project_id=job.project_id,
                      input=data, user_id=user_id)


def complete_with_run(db: Session, job: models.AuditJob, run: models.AuditRun) -> None:
    transition_job(job, "completed")
    db.flush()
    job.audit_run_id = run.id
    if job.project_id is not None and run.project_id is None:
        assign_run(db, run, db.get(models.AuditProject, job.project_id))
    db.flush()
