import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.config import settings
from app.services.goal_validator import refresh_task_run_goal_validation
from app.services.task_events import push_event, task_event


WORKER_NOTE_PREFIX = "worker:"
TASK_STATUS_QUEUED = "queued"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_COMPLETED = "completed"
TASK_STATUS_FAILED = "failed"
PHONE_TASK_MODES = {"autoglm", "uiautomator2", "scroll_promo"}
ALLOWED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class WorkerDispatchError(ValueError):
    pass


class WorkerOwnershipError(WorkerDispatchError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _lease_expires(now: datetime | None = None) -> datetime:
    return (now or _utc_now()) + timedelta(seconds=max(30, settings.WORKER_LEASE_SECONDS))


def is_worker_device(device: models.Device | None) -> bool:
    return bool(device and device.notes and device.notes.startswith(WORKER_NOTE_PREFIX))


def _is_worker_device_for_node(device: models.Device | None, node_key: str) -> bool:
    return bool(device and device.notes and device.notes.startswith(f"{WORKER_NOTE_PREFIX}{node_key}"))


def _is_fresh_worker_device(device: models.Device, node_key: str, now: datetime | None = None) -> bool:
    if device.status != "online" or not _is_worker_device_for_node(device, node_key):
        return False
    if not device.last_seen_at:
        return False
    return (now or _utc_now()) - device.last_seen_at <= timedelta(seconds=max(5, settings.WORKER_DEVICE_STALE_SECONDS))


def has_available_worker_device(db: Session, *, device_id: UUID | None = None) -> bool:
    now = _utc_now()
    for device in crud.list_devices(db):
        if device_id is not None and device.id != device_id:
            continue
        if is_worker_device(device) and device.status == "online" and device.last_seen_at:
            if now - device.last_seen_at <= timedelta(seconds=max(5, settings.WORKER_DEVICE_STALE_SECONDS)):
                return True
    return False


def _worker_devices_for_claim(db: Session, node_key: str, serials: set[str]) -> list[models.Device]:
    if not serials:
        return []
    now = _utc_now()
    devices = []
    for device in crud.list_devices(db):
        if device.serial in serials and _is_fresh_worker_device(device, node_key, now):
            devices.append(device)
    return devices


def _run_log_path(run: models.TaskRun) -> Path:
    rel_path = run.log_path or os.path.join("logs", "tasks", str(run.task_id), f"{run.id}.log")
    path = Path(settings.PROJECT_ROOT, rel_path) if not os.path.isabs(rel_path) else Path(rel_path)
    root = Path(settings.PROJECT_ROOT).resolve()
    resolved = path.resolve()
    if root not in resolved.parents and resolved != root:
        raise WorkerDispatchError("Unsafe task log path")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _run_output_dir(run: models.TaskRun) -> Path:
    rel_path = run.output_dir or os.path.join("data", "tasks", str(run.task_id), "runs", str(run.id))
    path = Path(settings.PROJECT_ROOT, rel_path) if not os.path.isabs(rel_path) else Path(rel_path)
    root = Path(settings.PROJECT_ROOT).resolve()
    resolved = path.resolve()
    if root not in resolved.parents and resolved != root:
        raise WorkerDispatchError("Unsafe task output path")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _relative_to_project(path: Path) -> str:
    return os.path.relpath(str(path), settings.PROJECT_ROOT)


def _finish_queue_tail() -> None:
    try:
        from app.services.task_queue import start_next_queued_task

        start_next_queued_task()
    except Exception as exc:
        print(f"⚠️ 启动下一条排队任务失败: {exc}")


def _fail_run(db: Session, run: models.TaskRun, *, exit_code: int | None, reason: str) -> models.TaskRun:
    now = _utc_now()
    crud.update_task_status(db, run.task_id, TASK_STATUS_FAILED)
    updated = crud.update_task_run(
        db,
        run.id,
        status=TASK_STATUS_FAILED,
        completed_at=now,
        exit_code=exit_code,
        failure_reason=reason,
        worker_error=reason,
    )
    crud.release_device_for_run(db, run.id)
    push_event(str(run.task_id), task_event("error", message=reason))
    push_event(str(run.task_id), task_event("done", status=TASK_STATUS_FAILED))
    _finish_queue_tail()
    return updated


def reap_expired_worker_runs(db: Session) -> int:
    now = _utc_now()
    expired = (
        db.query(models.TaskRun)
        .filter(models.TaskRun.status == TASK_STATUS_RUNNING)
        .filter(models.TaskRun.worker_node_key.isnot(None))
        .filter(models.TaskRun.worker_lease_expires_at.isnot(None))
        .filter(models.TaskRun.worker_lease_expires_at < now)
        .all()
    )
    for run in expired:
        _fail_run(db, run, exit_code=None, reason="worker lease expired")
    return len(expired)


def _task_supported(task: models.Task, capabilities: set[str]) -> bool:
    mode = task.mode or "uiautomator2"
    if mode not in PHONE_TASK_MODES:
        return False
    return not capabilities or mode in capabilities


def _claimable_run_and_device(
    db: Session,
    *,
    node_key: str,
    device_serials: set[str],
    capabilities: set[str],
) -> tuple[models.TaskRun, models.Device] | None:
    devices = _worker_devices_for_claim(db, node_key, device_serials)
    devices_by_id = {device.id: device for device in devices}
    devices_by_serial = {device.serial: device for device in devices}
    if not devices:
        return None

    runs = (
        db.query(models.TaskRun)
        .join(models.Task, models.TaskRun.task_id == models.Task.id)
        .filter(models.Task.status == TASK_STATUS_QUEUED)
        .filter(models.TaskRun.status == TASK_STATUS_QUEUED)
        .order_by(models.TaskRun.created_at.asc(), models.TaskRun.attempt_no.asc())
        .with_for_update(skip_locked=True)
        .all()
    )
    for run in runs:
        task = run.task
        if not task or not _task_supported(task, capabilities):
            continue
        if run.device_id:
            device = devices_by_id.get(run.device_id)
            if device:
                return run, device
            continue
        for serial in sorted(devices_by_serial):
            return run, devices_by_serial[serial]
    return None


def claim_next_run(
    db: Session,
    *,
    node_key: str,
    device_serials: list[str],
    capabilities: list[str],
) -> schemas.WorkerClaimOut:
    node_key = _clean(node_key)
    if not node_key:
        raise WorkerDispatchError("node_key is required")
    reap_expired_worker_runs(db)

    claim = _claimable_run_and_device(
        db,
        node_key=node_key,
        device_serials={_clean(serial) for serial in device_serials if _clean(serial)},
        capabilities={_clean(capability) for capability in capabilities if _clean(capability)},
    )
    if not claim:
        return schemas.WorkerClaimOut(claimed=False, poll_seconds=settings.WORKER_POLL_SECONDS)

    run, device = claim
    if not crud.mark_device_busy(db, device.id, run.id):
        return schemas.WorkerClaimOut(claimed=False, poll_seconds=settings.WORKER_POLL_SECONDS)

    now = _utc_now()
    output_dir = os.path.join("data", "tasks", str(run.task_id), "runs", str(run.id))
    log_path = os.path.join("logs", "tasks", str(run.task_id), f"{run.id}.log")
    run = crud.update_task_run(
        db,
        run.id,
        status=TASK_STATUS_RUNNING,
        started_at=now,
        device_id=device.id,
        worker_node_key=node_key,
        worker_claimed_at=now,
        worker_lease_expires_at=_lease_expires(now),
        artifact_count=run.artifact_count or 0,
        output_dir=output_dir,
        log_path=log_path,
    )
    crud.update_task_status(db, run.task_id, TASK_STATUS_RUNNING)
    _run_output_dir(run)
    _run_log_path(run)
    push_event(str(run.task_id), task_event("started"))
    return schemas.WorkerClaimOut(
        claimed=True,
        poll_seconds=settings.WORKER_POLL_SECONDS,
        run=schemas.WorkerTaskRunOut.model_validate(run),
        task=schemas.TaskOut.model_validate(run.task),
        device=schemas.DeviceOut.model_validate(device),
    )


def _owned_run(db: Session, run_id: UUID, node_key: str) -> models.TaskRun:
    run = crud.get_task_run(db, run_id)
    if not run:
        raise WorkerDispatchError("task run not found")
    if run.worker_node_key != _clean(node_key):
        raise WorkerOwnershipError("task run is not owned by this worker")
    return run


def extend_run_lease(db: Session, run_id: UUID, node_key: str) -> datetime:
    run = _owned_run(db, run_id, node_key)
    if run.status != TASK_STATUS_RUNNING:
        raise WorkerDispatchError("task run is not running")
    expires_at = _lease_expires()
    crud.update_task_run(db, run.id, worker_lease_expires_at=expires_at)
    return expires_at


def finish_worker_run(db: Session, run_id: UUID, node_key: str, exit_code: int, screenshot_count: int) -> models.TaskRun:
    run = _owned_run(db, run_id, node_key)
    if run.status != TASK_STATUS_RUNNING:
        raise WorkerDispatchError("task run is not running")
    if exit_code != 0:
        return _fail_run(db, run, exit_code=exit_code, reason=f"worker process exited with {exit_code}")
    if (run.artifact_count or 0) <= 0:
        return _fail_run(db, run, exit_code=exit_code, reason="no images collected")

    now = _utc_now()
    crud.update_task_status(db, run.task_id, TASK_STATUS_COMPLETED)
    updated = crud.update_task_run(
        db,
        run.id,
        status=TASK_STATUS_COMPLETED,
        completed_at=now,
        exit_code=exit_code,
    )
    crud.release_device_for_run(db, run.id)
    push_event(str(run.task_id), task_event("done", status=TASK_STATUS_COMPLETED, screenshots=screenshot_count))
    _finish_queue_tail()
    return updated


def fail_worker_run(db: Session, run_id: UUID, node_key: str, exit_code: int, failure_reason: str) -> models.TaskRun:
    run = _owned_run(db, run_id, node_key)
    if run.status not in (TASK_STATUS_RUNNING, TASK_STATUS_QUEUED):
        raise WorkerDispatchError("task run is already closed")
    return _fail_run(db, run, exit_code=exit_code, reason=_clean(failure_reason) or "worker failed")


def save_worker_artifact(
    db: Session,
    *,
    run_id: UUID,
    node_key: str,
    filename: str,
    content: bytes,
    source_app: str | None = None,
    scenario: str | None = None,
    captured_at: datetime | None = None,
) -> schemas.WorkerArtifactOut:
    run = _owned_run(db, run_id, node_key)
    if run.status != TASK_STATUS_RUNNING:
        raise WorkerDispatchError("task run is not running")
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        raise WorkerDispatchError("unsupported artifact type")
    if not content:
        raise WorkerDispatchError("empty artifact")

    digest = hashlib.sha256(content).hexdigest()
    upload_dir = _run_output_dir(run) / "worker_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = upload_dir / f"{digest}{suffix}"
    rel_path = _relative_to_project(artifact_path)

    existing = crud.get_image_by_file_and_task(db, rel_path, run.task_id)
    if existing:
        return schemas.WorkerArtifactOut(
            image_id=existing.id,
            file_path=existing.file_path,
            sha256=digest,
            duplicate=True,
            oss_url=existing.oss_url,
        )

    if not artifact_path.exists():
        artifact_path.write_bytes(content)

    task = crud.get_task(db, run.task_id)
    oss_url = ""
    oss_key = ""
    try:
        from app.services.oss_uploader import oss_uploader

        result = oss_uploader.upload(str(artifact_path), scenario_name="screenshot")
        if result.get("success"):
            oss_url = result.get("url") or ""
            oss_key = result.get("key") or ""
        else:
            print(f"  ⚠️ worker artifact OSS 上传失败: {result.get('error')}")
    except Exception as exc:
        print(f"  ⚠️ worker artifact OSS 上传异常: {exc}")

    image = crud.create_image(
        db,
        schemas.ImageCreate(
            file_path=rel_path,
            oss_url=oss_url or None,
            oss_key=oss_key or None,
            source_app=_clean(source_app) or (task.target_app if task else None),
            scenario=_clean(scenario) or (task.target_scenario if task else None),
            captured_at=captured_at or _utc_now(),
            task_id=run.task_id,
            task_run_id=run.id,
            device_id=run.device_id,
        ),
    )
    crud.increment_task_run_artifact_count(db, run.id)
    refresh_task_run_goal_validation(db, run.task_id, run.id)
    push_event(str(run.task_id), task_event("new_image", image_id=str(image.id)))
    try:
        from app.services.collector_bridge import _trigger_analysis

        _trigger_analysis(image.id)
    except Exception as exc:
        print(f"⚠️ worker artifact 自动分析启动失败 {image.id}: {exc}")

    return schemas.WorkerArtifactOut(
        image_id=image.id,
        file_path=image.file_path,
        sha256=digest,
        duplicate=False,
        oss_url=image.oss_url,
    )


def append_worker_log(db: Session, run_id: UUID, node_key: str, text: str) -> str:
    run = _owned_run(db, run_id, node_key)
    path = _run_log_path(run)
    if not run.log_path:
        crud.update_task_run(db, run.id, log_path=_relative_to_project(path))
    with path.open("a", encoding="utf-8", errors="replace") as handle:
        handle.write(text)
        if text and not text.endswith("\n"):
            handle.write("\n")
    return _relative_to_project(path)
