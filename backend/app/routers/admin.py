import asyncio
import os
import re
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional
from pathlib import Path
from app.services.task_events import ensure_queue, task_event_type
from app.services.task_planner import append_execution_rules, keyword_instruction, plan_task
from app.services.task_goals import append_target_goal_checklist, build_target_goals
from app.services.task_queue import TaskQueueError, start_or_enqueue_task
from app.services.embedder import embedder
from app.services.auth import data_scope_user_id, get_current_user, require_at_least
from app.services.devices import refresh_devices
from app.services import exporter
from app.config import settings
from app.database import get_db
from app import crud, models, schemas

router = APIRouter(prefix="/admin", tags=["admin"])
EXPORT_MEDIA_TYPES = {
    "json": "application/json; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "zip": "application/zip",
}
TARGET_APP_SPLIT_PATTERN = re.compile(r"(?:\s*(?:、|，|,|/|\\|;|；|\+|和|及|与)\s*)+")


def _is_visible_task_image(image) -> bool:
    return not os.path.basename(image.file_path).startswith("_temp_")


def split_target_apps(target_app: str | None) -> list[str]:
    if not target_app:
        return []
    apps: list[str] = []
    for part in TARGET_APP_SPLIT_PATTERN.split(str(target_app)):
        app = part.strip().strip(" 　,，、/\\;；+")
        app = re.sub(r"(?:App|APP|app|应用)$", "", app).strip()
        if app and app not in apps:
            apps.append(app)
    return apps


def _task_name_part(value: str | None, fallback: str) -> str:
    part = re.sub(r"\s+", "", str(value or "").strip())
    part = part.strip("-")
    return part or fallback


def _next_daily_image_task_name(db: Session, target_app: str | None, keyword: str | None) -> str:
    date_key = datetime.now().strftime("%Y%m%d")
    daily_count = (
        db.query(func.count(models.Task.id))
        .filter(models.Task.name.like(f"%-{date_key}-%"))
        .filter(~models.Task.name.startswith("[持续观察]"))
        .scalar()
        or 0
    )
    return (
        f"{_task_name_part(target_app, '未命名目标')}-"
        f"{_task_name_part(keyword, '无关键词')}-"
        f"{date_key}-{daily_count + 1:03d}"
    )


def build_autoglm_prompt(task) -> str:
    """
    根据前端表单字段拼接 AutoGLM 可执行的自然语言指令。
    利用 task 关联的 request 获取完整上下文。
    """
    parts = []
    req = task.request

    # 1. 打开目标 App
    app_name = task.target_app or (req.target_app if req else None)
    if app_name:
        parts.append(f"打开{app_name}App")

    # 2. 关键词：搜索类场景才搜索，非输入类场景作为关注点
    keyword = task.keyword
    if req and req.keywords:
        keyword = "、".join(req.keywords)

    # 3. 目标场景/页面
    scenario = task.target_scenario or (req.target_scenario if req else None)
    keyword_part = keyword_instruction([keyword] if keyword else [], scenario)
    if keyword_part:
        parts.append(keyword_part)

    if scenario:
        parts.append(f"找到{scenario}")

    # 4. 补充说明
    if req and req.description:
        parts.append(req.description)

    # 5. 最终动作
    parts.append("并截图保存到本地")

    instruction = append_execution_rules("，".join(parts))
    return append_target_goal_checklist(instruction, getattr(task, "target_goals_json", None))


def _get_visible_request(db: Session, request_id: UUID, user: models.User) -> models.Request:
    scope_user_id = data_scope_user_id(user)
    req = crud.get_request_for_user(db, request_id, scope_user_id) if scope_user_id else crud.get_request(db, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    return req


def _get_visible_task(db: Session, task_id: UUID, user: models.User) -> models.Task:
    scope_user_id = data_scope_user_id(user)
    task = crud.get_task_for_user(db, task_id, scope_user_id) if scope_user_id else crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


def _get_visible_task_run(db: Session, run_id: UUID, user: models.User) -> models.TaskRun:
    scope_user_id = data_scope_user_id(user)
    run = crud.get_task_run_for_user(db, run_id, scope_user_id) if scope_user_id else crud.get_task_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Task run not found")
    return run


@router.get("/stats")
def get_admin_stats(db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    user_id = data_scope_user_id(user)
    request_count = db.query(func.count(models.Request.id))
    task_count = db.query(func.count(models.Task.id))
    pending_request_count = db.query(func.count(models.Request.id)).filter(models.Request.status == "pending")
    pending_task_count = db.query(func.count(models.Task.id)).filter(models.Task.status == "pending")
    if user_id is not None:
        request_count = request_count.filter(models.Request.user_id == str(user_id))
        task_count = task_count.filter(models.Task.created_by == user_id)
        pending_request_count = pending_request_count.filter(models.Request.user_id == str(user_id))
        pending_task_count = pending_task_count.filter(models.Task.created_by == user_id)
    return {
        "requests": request_count.scalar() or 0,
        "tasks": task_count.scalar() or 0,
        "pending_requests": pending_request_count.scalar() or 0,
        "pending_tasks": pending_task_count.scalar() or 0,
    }


@router.get("/embedding-health")
async def get_embedding_health(live: bool = False, _=Depends(require_at_least("operator"))):
    if live:
        return await embedder.probe()
    return embedder.health()


@router.get("/requests", response_model=list[schemas.RequestOut])
def list_requests(status: Optional[str] = None, skip: int = 0, limit: int = 100, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return [_request_out(db, req) for req in crud.list_requests(db, status=status, skip=skip, limit=limit, user_id=data_scope_user_id(user))]


@router.put("/requests/{request_id}/approve", response_model=schemas.TaskOut)
async def approve_request(
    request_id: UUID,
    body: schemas.ApproveRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    req = _get_visible_request(db, request_id, user)
    crud.update_request_status(db, request_id, "approved")

    keywords = req.keywords or []
    target_app = body.target_app or req.target_app
    target_apps = split_target_apps(target_app) or [target_app]
    target_scenario = body.target_scenario or req.target_scenario
    created_tasks = []

    for app_name in target_apps:
        target_goals = build_target_goals(app_name, target_scenario, keywords, req.description)
        generated_instruction = None
        try:
            generated_instruction = await plan_task(
                target_app=app_name,
                target_scenario=target_scenario,
                keywords=keywords,
                description=req.description,
            )
            generated_instruction = append_target_goal_checklist(generated_instruction, target_goals)
        except Exception as e:
            print(f"⚠️ LLM 指令生成异常: {e}")

        task_keyword = body.keyword or (keywords[0] if keywords else "")
        task = crud.create_task(
            db,
            name=_next_daily_image_task_name(db, app_name, task_keyword),
            keyword=task_keyword,
            target_app=app_name,
            target_scenario=target_scenario,
            request_id=request_id,
            admin_id=body.admin_id or user.username,
            mode=body.mode,
            created_by=UUID(str(req.user_id)) if _looks_uuid(req.user_id) else user.id,
            approved_by=user.id,
            target_goals_json=target_goals,
        )

        # 将 LLM 生成的指令存入 task
        if generated_instruction and task:
            crud.update_task_instruction(db, task.id, generated_instruction)
            task = crud.get_task(db, task.id)
        created_tasks.append(task)

    return created_tasks[0]


@router.put("/requests/{request_id}/reject", response_model=schemas.RequestOut)
def reject_request(
    request_id: UUID,
    body: schemas.RejectRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    _get_visible_request(db, request_id, user)
    req = crud.update_request_status(db, request_id, "rejected")
    return req


@router.get("/tasks", response_model=list[schemas.TaskOut])
def list_tasks(status: Optional[str] = None, skip: int = 0, limit: int = 100, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return [_task_out(db, task) for task in crud.list_tasks(db, status=status, skip=skip, limit=limit, user_id=data_scope_user_id(user))]


@router.patch("/tasks/{task_id}", response_model=schemas.TaskOut)
def update_task(
    task_id: UUID,
    body: schemas.TaskUpdate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    task = _get_visible_task(db, task_id, user)
    name = body.name.strip() if body.name is not None else None
    if not name:
        raise HTTPException(status_code=400, detail="Task name is required")
    if len(name) > 120:
        raise HTTPException(status_code=400, detail="Task name is too long")
    crud.update_task_name(db, task.id, name)
    return _task_out(db, crud.get_task(db, task.id))


@router.post("/tasks/{task_id}/run", response_model=schemas.TaskOut)
def run_task(
    task_id: UUID,
    body: schemas.RunTaskRequest | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    task = _get_visible_task(db, task_id, user)
    prompt = task.generated_instruction or build_autoglm_prompt(task) if task.mode == "autoglm" else None
    try:
        start_or_enqueue_task(
            db,
            task,
            created_by=user.id,
            requested_device_id=body.device_id if body else None,
            prompt=prompt,
        )
    except FileNotFoundError as e:
        crud.update_task_status(db, task_id, "failed")
        raise HTTPException(status_code=500, detail=str(e))
    except (TaskQueueError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _task_out(db, crud.get_task(db, task_id))


@router.post("/tasks/{task_id}/retry", response_model=schemas.TaskOut)
def retry_task(
    task_id: UUID,
    body: schemas.RetryTaskRequest | None = None,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_at_least("operator")),
):
    task = _get_visible_task(db, task_id, user)
    if task.status == "running":
        raise HTTPException(status_code=400, detail="Running task cannot be retried")
    if crud.count_task_runs(db, task_id) >= settings.TASK_MAX_RETRIES:
        raise HTTPException(status_code=400, detail="Max retry count reached")
    return run_task(task_id, body or schemas.RetryTaskRequest(), db, user)


@router.get("/tasks/{task_id}/runs", response_model=list[schemas.TaskRunOut])
def list_task_runs(task_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    _get_visible_task(db, task_id, user)
    return crud.list_task_runs(db, task_id)


@router.get("/task-runs/{run_id}", response_model=schemas.TaskRunOut)
def get_task_run(run_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    return _get_visible_task_run(db, run_id, user)


@router.get("/task-runs/{run_id}/logs")
def get_task_run_logs(run_id: UUID, lines: int = 200, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    run = _get_visible_task_run(db, run_id, user)
    path = _safe_log_path(run.log_path)
    if not path or not path.exists():
        return {"run_id": run_id, "logs": ""}
    text = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return {"run_id": run_id, "logs": "\n".join(text[-min(max(lines, 1), 1000):])}


@router.get("/tasks/{task_id}/progress")
def task_progress(task_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    task = _get_visible_task(db, task_id, user)
    images = [img for img in task.images if _is_visible_task_image(img)]
    analyzed = sum(1 for img in images if img.analysis and img.analysis.status in ("success", "partial", "skipped"))
    return {"task_id": task_id, "total_images": len(images), "analyzed": analyzed, "status": task.status}


@router.get("/tasks/{task_id}/images", response_model=list[schemas.SearchResult])
def task_images(task_id: UUID, skip: int = 0, limit: int = 100, run_id: UUID | None = None, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    scope_user_id = data_scope_user_id(user)
    _get_visible_task(db, task_id, user)
    return [
        schemas.SearchResult(
            image=schemas.ImageOut.model_validate(image),
            analysis=schemas.AnalysisOut.model_validate(image.analysis) if image.analysis else None,
            similarity=None,
        )
        for image in crud.list_images(db, skip=skip, limit=limit, task_id=task_id, user_id=scope_user_id)
        if (run_id is None or image.task_run_id == run_id)
        if _is_visible_task_image(image)
    ]


@router.get("/tasks/{task_id}/export")
def export_task(task_id: UUID, format: str = "json", db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    if format not in EXPORT_MEDIA_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported export format")
    if format == "zip" and user.role == "viewer":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    scope_user_id = data_scope_user_id(user)
    _get_visible_task(db, task_id, user)
    payload = exporter.task_export_payload(db, task_id, user_id=scope_user_id)
    if format == "json":
        content = exporter.json_bytes(payload)
        filename = f"task-{task_id}.json"
    elif format == "xlsx":
        content = exporter.excel_bytes(payload)
        filename = f"task-{task_id}.xlsx"
    else:
        content = exporter.task_zip_bytes(db, task_id, user_id=scope_user_id)
        filename = f"task-{task_id}.zip"
    return Response(
        content=content,
        media_type=EXPORT_MEDIA_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/devices", response_model=list[schemas.DeviceOut])
def list_devices(db: Session = Depends(get_db), _=Depends(get_current_user)):
    return crud.list_devices(db)


@router.post("/devices/refresh", response_model=schemas.DeviceRefreshOut)
def refresh_adb_devices(db: Session = Depends(get_db), _=Depends(require_at_least("operator"))):
    devices, adb_available = refresh_devices(db)
    return schemas.DeviceRefreshOut(devices=[schemas.DeviceOut.model_validate(device) for device in devices], adb_available=adb_available)

@router.get("/tasks/{task_id}/events")
async def task_events(task_id: UUID, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """SSE 端点：实时推送任务进度更新"""
    _get_visible_task(db, task_id, user)
    tid = str(task_id)
    queue = ensure_queue(tid)

    async def event_generator():
        while True:
            try:
                # 等待队列消息，超时 30 秒发送 keep-alive
                msg = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"data: {msg}\n\n"
                if task_event_type(msg) == "done":
                    break
            except asyncio.TimeoutError:
                yield ":heartbeat\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )


def _looks_uuid(value: str | None) -> bool:
    if not value:
        return False
    try:
        UUID(str(value))
        return True
    except ValueError:
        return False


def _task_out(db: Session, task: models.Task) -> schemas.TaskOut:
    latest = crud.get_latest_task_run(db, task.id)
    device = crud.get_device(db, latest.device_id) if latest and latest.device_id else None
    data = schemas.TaskOut.model_validate(task).model_dump()
    data["latest_run_id"] = latest.id if latest else None
    data["attempt_count"] = crud.count_task_runs(db, task.id)
    data["failure_reason"] = latest.failure_reason if latest else None
    data["device_serial"] = device.serial if device else None
    data["created_by_name"] = _user_name(db, task.created_by)
    data["approved_by_name"] = _user_name(db, task.approved_by)
    data["run_by_name"] = _user_name(db, task.run_by)
    if _is_goal_validation_only_failure(task, latest):
        data["status"] = "completed"
        data["completed_at"] = latest.completed_at or task.completed_at
    return schemas.TaskOut.model_validate(data)


def _request_out(db: Session, req: models.Request) -> schemas.RequestOut:
    data = schemas.RequestOut.model_validate(req).model_dump()
    data["user_display_name"] = _user_name(db, UUID(req.user_id)) if _looks_uuid(req.user_id) else req.user_id
    return schemas.RequestOut.model_validate(data)


def _is_goal_validation_only_failure(task: models.Task, run: models.TaskRun | None) -> bool:
    if not run or task.status != "failed" or run.status != "failed":
        return False
    validation = run.goal_validation_json if isinstance(run.goal_validation_json, dict) else {}
    if validation.get("status") != "missing":
        return False
    return any(_is_visible_task_image(image) for image in run.images)


def _user_name(db: Session, user_id: UUID | None) -> str | None:
    if not user_id:
        return None
    user = crud.get_user(db, user_id)
    if not user:
        return None
    return user.display_name or user.username


def _safe_log_path(log_path: str | None) -> Path | None:
    if not log_path:
        return None
    root = Path(settings.PROJECT_ROOT).resolve()
    path = Path(log_path)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Unsafe log path")
    return resolved
