import shutil
import subprocess
from datetime import datetime

from sqlalchemy.orm import Session

from app import crud, models

WORKER_DEVICE_NOTE_PREFIX = "worker:"


def parse_adb_devices(output: str) -> list[dict[str, str]]:
    devices = []
    for line in output.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        devices.append({"serial": serial, "adb_state": state})
    return devices


def refresh_devices(db: Session) -> tuple[list[models.Device], bool]:
    if not shutil.which("adb"):
        return crud.list_devices(db), False

    result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10)
    if result.returncode != 0:
        return crud.list_devices(db), False

    now = datetime.now()
    seen = set()
    for item in parse_adb_devices(result.stdout):
        serial = item["serial"]
        seen.add(serial)
        adb_state = item["adb_state"]
        status = "online" if adb_state == "device" else "offline"
        notes = None if adb_state == "device" else adb_state
        existing = crud.get_device_by_serial(db, serial)
        if existing and existing.status == "busy" and adb_state == "device":
            existing.last_seen_at = now
            existing.updated_at = now
            db.commit()
            continue
        crud.upsert_device(db, serial=serial, status=status, last_seen_at=now, notes=notes)

    for device in crud.list_devices(db):
        if device.notes and device.notes.startswith(WORKER_DEVICE_NOTE_PREFIX):
            continue
        if device.serial not in seen and device.status not in ("disabled", "busy"):
            crud.upsert_device(db, serial=device.serial, status="offline", last_seen_at=device.last_seen_at, notes="not listed by adb")
    return crud.list_devices(db), True
