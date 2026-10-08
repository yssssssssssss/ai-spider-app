import hmac
from datetime import datetime
from uuid import UUID
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.config import settings
from app.database import get_db
from app.services import worker_dispatch
from app.services.jd_new_floor_analyzer import jd_new_floor_analyzer
from app.services.jd_secondary_tab_analyzer import FRAME_KEYS, jd_secondary_tab_analyzer
from app.services.promotion_detector import promotion_detector


router = APIRouter(prefix="/worker", tags=["worker"])
WORKER_NOTE_PREFIX = "worker:"


class WorkerRegisterRequest(BaseModel):
    node_key: str
    name: str | None = None
    version: str | None = None


class WorkerHeartbeatRequest(BaseModel):
    node_key: str
    status: Literal["online", "offline"] = "online"


class WorkerDeviceIn(BaseModel):
    serial: str
    status: Literal["online", "offline"] = "online"
    notes: str | None = None
    name: str | None = None


class WorkerDevicesRequest(BaseModel):
    node_key: str
    devices: list[WorkerDeviceIn]


def require_worker_token(x_worker_token: str | None = Header(default=None)):
    expected = settings.WORKER_API_TOKEN.strip()
    if not expected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Worker token is not configured")
    if not x_worker_token or not hmac.compare_digest(x_worker_token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid worker token")


def _raise_worker_error(exc: worker_dispatch.WorkerDispatchError):
    if isinstance(exc, worker_dispatch.WorkerOwnershipError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _worker_note(node_key: str, notes: str | None = None) -> str:
    suffix = _clean(notes)
    return f"{WORKER_NOTE_PREFIX}{node_key}" + (f" {suffix}" if suffix else "")


def _is_worker_device(device: models.Device, node_key: str) -> bool:
    return bool(device.notes and device.notes.startswith(f"{WORKER_NOTE_PREFIX}{node_key}"))


@router.post("/register")
def register_worker(
    body: WorkerRegisterRequest,
    _: None = Depends(require_worker_token),
):
    node_key = _clean(body.node_key)
    if not node_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="node_key is required")
    return {"ok": True, "node_key": node_key}


@router.post("/heartbeat")
def worker_heartbeat(
    body: WorkerHeartbeatRequest,
    _: None = Depends(require_worker_token),
):
    node_key = _clean(body.node_key)
    if not node_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="node_key is required")
    return {"ok": True, "node_key": node_key, "status": body.status}


@router.post("/devices", response_model=schemas.DeviceRefreshOut)
def report_worker_devices(
    body: WorkerDevicesRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_worker_token),
):
    node_key = _clean(body.node_key)
    if not node_key:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="node_key is required")

    now = datetime.now()
    seen: set[str] = set()
    for item in body.devices:
        serial = _clean(item.serial)
        if not serial:
            continue
        seen.add(serial)
        existing = crud.get_device_by_serial(db, serial)
        if existing and existing.status == "busy" and item.status == "online":
            existing.last_seen_at = now
            existing.updated_at = now
            existing.notes = _worker_note(node_key, item.notes)
            db.commit()
            continue
        crud.upsert_device(
            db,
            serial=serial,
            name=_clean(item.name) or serial,
            status=item.status,
            last_seen_at=now,
            notes=_worker_note(node_key, item.notes),
        )

    for device in crud.list_devices(db):
        if device.serial in seen or not _is_worker_device(device, node_key) or device.status in ("busy", "disabled"):
            continue
        crud.upsert_device(
            db,
            serial=device.serial,
            name=device.name,
            status="offline",
            last_seen_at=device.last_seen_at,
            notes=_worker_note(node_key, "not reported by worker"),
        )

    return schemas.DeviceRefreshOut(
        devices=[schemas.DeviceOut.model_validate(device) for device in crud.list_devices(db)],
        adb_available=True,
    )


@router.post("/promotion-detect", response_model=schemas.WorkerPromotionDetectionOut)
async def detect_promotion_overlay(
    file: UploadFile = File(...),
    _: None = Depends(require_worker_token),
):
    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="image too large")
    try:
        return (await promotion_detector.detect_png(content)).to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"promotion detection failed: {exc}") from exc


@router.post("/jd-new-floor-analyze", response_model=schemas.WorkerJdNewFloorAnalysisOut)
async def analyze_jd_new_floor(
    file: UploadFile = File(...),
    _: None = Depends(require_worker_token),
):
    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="image too large")
    try:
        return (await jd_new_floor_analyzer.analyze_png(content)).to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"floor analysis failed: {exc}") from exc


@router.post("/jd-secondary-tab-locate", response_model=schemas.WorkerJdSecondaryTabLocatorOut)
async def locate_jd_secondary_tab(
    file: UploadFile = File(...),
    _: None = Depends(require_worker_token),
):
    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="image too large")
    try:
        return await jd_secondary_tab_analyzer.locate_z1_png(content)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"secondary Tab location failed: {exc}") from exc


@router.post("/jd-secondary-tab-analyze", response_model=schemas.WorkerJdSecondaryTabAnalysisOut)
async def analyze_jd_secondary_tab(
    z1_before: UploadFile = File(...),
    z1_after_left: UploadFile = File(...),
    z2_before: UploadFile = File(...),
    z2_after_left: UploadFile = File(...),
    z3_before: UploadFile = File(...),
    z1_top: int = Form(...),
    z1_bottom: int = Form(...),
    _: None = Depends(require_worker_token),
):
    uploads = {
        "z1_before": z1_before,
        "z1_after_left": z1_after_left,
        "z2_before": z2_before,
        "z2_after_left": z2_after_left,
        "z3_before": z3_before,
    }
    contents = {key: await uploads[key].read() for key in FRAME_KEYS}
    if any(len(content) > 15 * 1024 * 1024 for content in contents.values()):
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="image too large")
    try:
        return (await jd_secondary_tab_analyzer.analyze_pngs(contents, z1_top, z1_bottom)).to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"secondary Tab analysis failed: {exc}") from exc


@router.post("/task-runs/claim", response_model=schemas.WorkerClaimOut)
def claim_task_run(
    body: schemas.WorkerClaimRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_worker_token),
):
    try:
        return worker_dispatch.claim_next_run(
            db,
            node_key=body.node_key,
            device_serials=body.device_serials,
            capabilities=body.capabilities,
        )
    except worker_dispatch.WorkerDispatchError as exc:
        _raise_worker_error(exc)


@router.post("/task-runs/{run_id}/heartbeat")
def worker_run_heartbeat(
    run_id: UUID,
    body: schemas.WorkerRunHeartbeatRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_worker_token),
):
    try:
        lease_expires_at = worker_dispatch.extend_run_lease(db, run_id, body.node_key)
        return {"ok": True, "run_id": str(run_id), "lease_expires_at": lease_expires_at.isoformat()}
    except worker_dispatch.WorkerDispatchError as exc:
        _raise_worker_error(exc)


@router.post("/task-runs/{run_id}/result", response_model=schemas.WorkerTaskRunOut)
def upload_worker_result(
    run_id: UUID,
    body: schemas.WorkerRunResultRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_worker_token),
):
    try:
        return worker_dispatch.store_worker_result(db, run_id, body.node_key, body.result_json)
    except worker_dispatch.WorkerDispatchError as exc:
        _raise_worker_error(exc)


@router.post("/task-runs/{run_id}/finish", response_model=schemas.WorkerTaskRunOut)
def finish_worker_run(
    run_id: UUID,
    body: schemas.WorkerRunFinishRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_worker_token),
):
    try:
        return worker_dispatch.finish_worker_run(db, run_id, body.node_key, body.exit_code, body.screenshot_count)
    except worker_dispatch.WorkerDispatchError as exc:
        _raise_worker_error(exc)


@router.post("/task-runs/{run_id}/fail", response_model=schemas.WorkerTaskRunOut)
def fail_worker_run(
    run_id: UUID,
    body: schemas.WorkerRunFailRequest,
    db: Session = Depends(get_db),
    _: None = Depends(require_worker_token),
):
    try:
        return worker_dispatch.fail_worker_run(db, run_id, body.node_key, body.exit_code, body.failure_reason)
    except worker_dispatch.WorkerDispatchError as exc:
        _raise_worker_error(exc)


def _parse_captured_at(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="captured_at must be ISO datetime")


@router.post("/task-runs/{run_id}/artifacts", response_model=schemas.WorkerArtifactOut)
async def upload_worker_artifact(
    run_id: UUID,
    node_key: str = Form(...),
    source_app: str | None = Form(default=None),
    scenario: str | None = Form(default=None),
    captured_at: str | None = Form(default=None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: None = Depends(require_worker_token),
):
    content = await file.read()
    try:
        return worker_dispatch.save_worker_artifact(
            db,
            run_id=run_id,
            node_key=node_key,
            filename=file.filename or "artifact.png",
            content=content,
            source_app=source_app,
            scenario=scenario,
            captured_at=_parse_captured_at(captured_at),
        )
    except worker_dispatch.WorkerDispatchError as exc:
        _raise_worker_error(exc)


@router.post("/task-runs/{run_id}/logs")
async def upload_worker_log(
    run_id: UUID,
    request: Request,
    node_key: str,
    db: Session = Depends(get_db),
    _: None = Depends(require_worker_token),
):
    content = await request.body()
    if len(content) > 256 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="log chunk too large")
    try:
        log_path = worker_dispatch.append_worker_log(
            db,
            run_id,
            node_key,
            content.decode("utf-8", errors="replace"),
        )
        return {"ok": True, "run_id": str(run_id), "log_path": log_path}
    except worker_dispatch.WorkerDispatchError as exc:
        _raise_worker_error(exc)
