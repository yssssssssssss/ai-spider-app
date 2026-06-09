import time as time_module
import threading
from datetime import datetime
from uuid import UUID

from app import crud
from app.config import settings
from app.database import SessionLocal
from app.services.devices import refresh_devices
from app.services.task_executor import execution_mode, task_executor
from app.services.task_goals import append_target_goal_checklist, build_target_goals
from app.services.task_planner import append_execution_rules, keyword_instruction


REQUEST_SCHEDULER_ADMIN_ID = "request-scheduler"
_scheduler_started = False


def _looks_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        UUID(str(value))
        return True
    except ValueError:
        return False


def _request_owner_id(request) -> UUID | None:
    return UUID(str(request.user_id)) if _looks_uuid(request.user_id) else None


def request_is_due_on(request, run_date) -> bool:
    if not getattr(request, "schedule_enabled", False):
        return False
    start_date = getattr(request, "schedule_start_date", None)
    end_date = getattr(request, "schedule_end_date", None)
    cycle = getattr(request, "schedule_cycle", None)
    if not start_date or not end_date or not cycle:
        return False
    if run_date < start_date or run_date > end_date:
        return False
    if cycle == "daily":
        return True
    if cycle == "weekly":
        return run_date.weekday() == start_date.weekday()
    if cycle == "monthly":
        return run_date.day == start_date.day
    return False


def request_is_due_now(request, now: datetime) -> bool:
    schedule_time = getattr(request, "schedule_time", None)
    if not schedule_time or schedule_time > now.time():
        return False
    return request_is_due_on(request, now.date())


def _build_request_instruction(request) -> str:
    parts = []
    if request.target_app:
        parts.append(f"打开{request.target_app}App")
    keyword_part = keyword_instruction(request.keywords or [], request.target_scenario)
    if keyword_part:
        parts.append(keyword_part)
    if request.target_scenario:
        parts.append(f"找到{request.target_scenario}")
    if request.description:
        parts.append(request.description)
    parts.append("并截图保存到本地")
    return append_execution_rules("，".join(parts))


def _start_scheduled_task(db, task, *, prompt: str | None, start_process: bool, created_by: UUID | None):
    active_mode = execution_mode()
    crud.update_task_status(db, task.id, "queued" if active_mode == "worker" else "running")
    task = crud.get_task(db, task.id)

    if not start_process:
        return task

    device = None
    if active_mode == "local":
        refresh_devices(db)
        device = crud.acquire_device(db)
        if not device:
            crud.update_task_status(db, task.id, "failed")
            return crud.get_task(db, task.id)

    run = crud.create_task_run(
        db,
        task.id,
        status="queued" if active_mode == "worker" else "pending",
        execution_mode=active_mode,
        device_id=device.id if device else None,
        created_by=created_by,
    )
    if device and active_mode == "local":
        if not crud.mark_device_busy(db, device.id, run.id):
            crud.update_task_status(db, task.id, "failed")
            crud.update_task_run(db, run.id, status="failed", failure_reason="Device is busy")
            return crud.get_task(db, task.id)

    try:
        task_executor().run(task, prompt=prompt, task_run=run, created_by=created_by, device=device)
    except (FileNotFoundError, ValueError) as exc:
        crud.update_task_status(db, task.id, "failed")
        crud.update_task_run(db, run.id, status="failed", failure_reason=str(exc))
        crud.release_device_for_run(db, run.id)
    return crud.get_task(db, task.id)


def create_scheduled_request_task(db, request, run_date, *, start_process: bool = True):
    existing = crud.get_scheduled_task_for_request_date(db, request.id, run_date)
    if existing:
        return existing

    mode = request.approved_task_mode or "autoglm"
    owner_id = _request_owner_id(request)
    keywords = request.keywords or []
    target_goals = build_target_goals(request.target_app, request.target_scenario, keywords, request.description)
    prompt = append_target_goal_checklist(_build_request_instruction(request), target_goals) if mode == "autoglm" else None

    task = crud.create_task(
        db,
        name=f"[定时竞品搜集] {run_date.isoformat()}",
        keyword=keywords[0] if keywords else "",
        target_app=request.target_app,
        target_scenario=request.target_scenario,
        request_id=request.id,
        admin_id=REQUEST_SCHEDULER_ADMIN_ID,
        mode=mode,
        scheduled_run_date=run_date,
        created_by=owner_id,
        target_goals_json=target_goals,
        analysis_skill_snapshots=request.analysis_skill_snapshots_json or [],
    )
    if prompt:
        crud.update_task_instruction(db, task.id, prompt)
        task = crud.get_task(db, task.id)
    return _start_scheduled_task(db, task, prompt=prompt, start_process=start_process, created_by=owner_id)


def run_due_scheduled_requests(db, now: datetime | None = None, *, start_process: bool = True) -> int:
    now = now or datetime.now()
    created = 0
    for request in crud.list_scheduled_requests(db):
        if not request_is_due_now(request, now):
            continue
        if crud.get_scheduled_task_for_request_date(db, request.id, now.date()):
            continue
        create_scheduled_request_task(db, request, now.date(), start_process=start_process)
        created += 1
    return created


def _scheduler_loop():
    while True:
        db = SessionLocal()
        try:
            run_due_scheduled_requests(db)
        except Exception as exc:
            print(f"⚠️ 定时竞品搜集调度失败: {exc}")
        finally:
            db.close()
        time_module.sleep(max(10, settings.WATCH_SCHEDULER_INTERVAL_SECONDS))


def start_request_scheduler():
    global _scheduler_started
    if _scheduler_started or not settings.WATCH_SCHEDULER_ENABLED:
        return
    _scheduler_started = True
    thread = threading.Thread(target=_scheduler_loop, daemon=True, name="request-scheduler")
    thread.start()
