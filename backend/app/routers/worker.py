import hmac
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.config import settings
from app.database import get_db


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


@router.post("/task-runs/claim", status_code=status.HTTP_204_NO_CONTENT)
def claim_task_run(_: None = Depends(require_worker_token)):
    return Response(status_code=status.HTTP_204_NO_CONTENT)
