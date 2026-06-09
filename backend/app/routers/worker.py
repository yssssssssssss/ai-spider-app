import os
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.config import settings
from app.database import get_db
from app.routers.images import _analyze_and_embed
from app.services.collector_bridge import _finish_run

router = APIRouter(prefix="/worker", tags=["worker"])


def require_worker_token(x_worker_token: str | None = Header(default=None, alias="X-Worker-Token")):
    if not x_worker_token or x_worker_token != settings.WORKER_API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid worker token")


def _safe_name(filename: str | None) -> str:
    name = os.path.basename(filename or "screenshot.png")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    return name or "screenshot.png"


def _project_path(relative_path: str | None) -> Path:
    if not relative_path:
        raise HTTPException(status_code=400, detail="Missing path")
    root = Path(settings.PROJECT_ROOT).resolve()
    resolved = (root / relative_path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Unsafe path")
    return resolved


def _get_worker(db: Session, node_key: str) -> models.Worker:
    worker = crud.get_worker_by_node_key(db, node_key)
    if not worker:
        raise HTTPException(status_code=404, detail="Worker not registered")
    return worker


def _get_worker_run(db: Session, run_id: UUID, node_key: str) -> models.TaskRun:
    worker = _get_worker(db, node_key)
    run = crud.get_task_run(db, run_id)
    if not run or run.worker_id != worker.id:
        raise HTTPException(status_code=404, detail="Task run not found for worker")
    crud.update_task_run(db, run.id, heartbeat_at=datetime.now(timezone.utc).replace(tzinfo=None))
    return crud.get_task_run(db, run.id)


def _device_out(db: Session, device: models.Device) -> schemas.DeviceOut:
    data = schemas.DeviceOut.model_validate(device).model_dump()
    worker = crud.get_worker(db, device.worker_id) if device.worker_id else None
    data["worker_name"] = worker.name if worker else None
    return schemas.DeviceOut.model_validate(data)


@router.post("/register", response_model=schemas.WorkerOut)
def register_worker(
    body: schemas.WorkerRegisterRequest,
    db: Session = Depends(get_db),
    _=Depends(require_worker_token),
):
    return crud.upsert_worker(
        db,
        node_key=body.node_key,
        name=body.name,
        version=body.version,
        notes=body.notes,
        status="online",
    )


@router.post("/heartbeat", response_model=schemas.WorkerOut)
def heartbeat_worker(
    body: schemas.WorkerHeartbeatRequest,
    db: Session = Depends(get_db),
    _=Depends(require_worker_token),
):
    return crud.upsert_worker(
        db,
        node_key=body.node_key,
        status=body.status,
        version=body.version,
        notes=body.notes,
    )


@router.post("/devices", response_model=schemas.WorkerDeviceReportOut)
def report_devices(
    body: schemas.WorkerDeviceReportRequest,
    db: Session = Depends(get_db),
    _=Depends(require_worker_token),
):
    worker = _get_worker(db, body.node_key)
    crud.upsert_worker(db, node_key=worker.node_key, status="online")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    seen = set()
    devices = []
    for item in body.devices:
        seen.add(item.serial)
        devices.append(crud.upsert_device(
            db,
            serial=item.serial,
            name=item.name,
            status=item.status,
            source="worker",
            worker_id=worker.id,
            last_seen_at=now,
            notes=item.notes,
        ))
    for device in crud.list_devices(db):
        if device.worker_id == worker.id and device.serial not in seen and device.status != "busy":
            crud.upsert_device(
                db,
                serial=device.serial,
                name=device.name,
                status="offline",
                source="worker",
                worker_id=worker.id,
                last_seen_at=device.last_seen_at,
                notes="not reported by worker",
            )
    return schemas.WorkerDeviceReportOut(
        worker=schemas.WorkerOut.model_validate(crud.get_worker(db, worker.id)),
        devices=[_device_out(db, device) for device in devices],
    )


@router.post("/task-runs/claim", response_model=schemas.WorkerClaimOut)
def claim_task_run(
    body: schemas.WorkerClaimRequest,
    db: Session = Depends(get_db),
    _=Depends(require_worker_token),
):
    worker = _get_worker(db, body.node_key)
    crud.upsert_worker(db, node_key=worker.node_key, status="online")
    run = crud.claim_next_worker_task_run(db, worker.id)
    if not run:
        return Response(status_code=204)
    task = crud.get_task(db, run.task_id)
    device = crud.get_device(db, run.device_id) if run.device_id else None
    return schemas.WorkerClaimOut(
        run=schemas.TaskRunOut.model_validate(run),
        task=schemas.TaskOut.model_validate(task),
        prompt=task.generated_instruction,
        device_serial=device.serial if device else None,
        max_steps=settings.AUTOGLM_MAX_STEPS,
    )


@router.post("/task-runs/{run_id}/logs")
def append_task_run_logs(
    run_id: UUID,
    body: schemas.WorkerLogAppendRequest,
    db: Session = Depends(get_db),
    _=Depends(require_worker_token),
):
    run = _get_worker_run(db, run_id, body.node_key)
    path = _project_path(run.log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing_size = path.stat().st_size if path.exists() else 0
    content = body.content.encode("utf-8", errors="replace")
    if existing_size + len(content) > settings.WORKER_LOG_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Worker log is too large")
    with path.open("a", encoding="utf-8") as fh:
        fh.write(body.content)
    return {"run_id": run_id, "bytes": len(content)}


@router.post("/task-runs/{run_id}/images", response_model=schemas.ImageOut)
async def upload_task_run_image(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    node_key: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _=Depends(require_worker_token),
):
    run = _get_worker_run(db, run_id, node_key)
    task = crud.get_task(db, run.task_id)
    filename = _safe_name(file.filename)
    if not filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        raise HTTPException(status_code=400, detail="Unsupported image type")

    data = await file.read(settings.WORKER_UPLOAD_MAX_BYTES + 1)
    if len(data) > settings.WORKER_UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Image file is too large")

    output_dir = run.output_dir or os.path.join("data", "tasks", str(task.id), "runs", str(run.id), "worker")
    target_path = _project_path(os.path.join(output_dir, filename))
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(data)
    rel_path = os.path.relpath(target_path, settings.PROJECT_ROOT)

    image = crud.create_image(db, schemas.ImageCreate(
        file_path=rel_path,
        source_app=task.target_app if task else None,
        scenario=task.target_scenario if task else None,
        captured_at=datetime.now(timezone.utc).replace(tzinfo=None),
        task_id=task.id if task else None,
        task_run_id=run.id,
        device_id=run.device_id,
    ))
    background_tasks.add_task(_analyze_and_embed, image.id)
    return image


@router.post("/task-runs/{run_id}/finish", response_model=schemas.TaskRunOut)
def finish_task_run(
    run_id: UUID,
    body: schemas.WorkerFinishRequest,
    db: Session = Depends(get_db),
    _=Depends(require_worker_token),
):
    run = _get_worker_run(db, run_id, body.node_key)
    status = "completed" if body.status == "completed" else "failed"
    _finish_run(
        db,
        run.task_id,
        run.id,
        status,
        exit_code=body.exit_code,
        failure_reason=body.failure_reason,
    )
    return crud.get_task_run(db, run.id)
