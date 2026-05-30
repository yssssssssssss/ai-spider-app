import asyncio
import os
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional
from app.services.task_events import ensure_queue
from app.services.task_planner import append_execution_rules, keyword_instruction, plan_task
from app.services.task_runner import start_task_process
from app.database import get_db
from app import crud, schemas

router = APIRouter(prefix="/admin", tags=["admin"])


def _is_visible_task_image(image) -> bool:
    return not os.path.basename(image.file_path).startswith("_temp_")


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

    return append_execution_rules("，".join(parts))

@router.get("/requests", response_model=list[schemas.RequestOut])
def list_requests(status: Optional[str] = None, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.list_requests(db, status=status, skip=skip, limit=limit)


@router.put("/requests/{request_id}/approve", response_model=schemas.TaskOut)
async def approve_request(request_id: UUID, body: schemas.ApproveRequest, db: Session = Depends(get_db)):
    req = crud.get_request(db, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    crud.update_request_status(db, request_id, "approved")

    # 调用 LLM 生成 AutoGLM 可执行指令
    keywords = req.keywords or []
    generated_instruction = None
    try:
        generated_instruction = await plan_task(
            target_app=body.target_app or req.target_app,
            target_scenario=body.target_scenario or req.target_scenario,
            keywords=keywords,
            description=req.description,
        )
    except Exception as e:
        print(f"⚠️ LLM 指令生成异常: {e}")

    task = crud.create_task(
        db,
        name=f"Task from request {request_id}",
        keyword=body.keyword or (keywords[0] if keywords else ""),
        target_app=body.target_app or req.target_app,
        target_scenario=body.target_scenario or req.target_scenario,
        request_id=request_id,
        admin_id=body.admin_id,
        mode=body.mode
    )

    # 将 LLM 生成的指令存入 task
    if generated_instruction and task:
        crud.update_task_instruction(db, task.id, generated_instruction)

    # 重新加载 task 以包含更新后的字段
    if task:
        task = crud.get_task(db, task.id)

    return task


@router.put("/requests/{request_id}/reject", response_model=schemas.RequestOut)
def reject_request(request_id: UUID, body: schemas.RejectRequest, db: Session = Depends(get_db)):
    req = crud.update_request_status(db, request_id, "rejected")
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    return req


@router.get("/tasks", response_model=list[schemas.TaskOut])
def list_tasks(status: Optional[str] = None, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.list_tasks(db, status=status, skip=skip, limit=limit)


@router.post("/tasks/{task_id}/run", response_model=schemas.TaskOut)
def run_task(task_id: UUID, db: Session = Depends(get_db)):
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    crud.update_task_status(db, task_id, "running")
    task = crud.get_task(db, task_id)

    prompt = task.generated_instruction or build_autoglm_prompt(task) if task.mode == "autoglm" else None
    try:
        start_task_process(task, prompt=prompt)
    except FileNotFoundError as e:
        crud.update_task_status(db, task_id, "failed")
        raise HTTPException(status_code=500, detail=str(e))
    except ValueError as e:
        crud.update_task_status(db, task_id, "failed")
        raise HTTPException(status_code=400, detail=str(e))
    return task


@router.get("/tasks/{task_id}/progress")
def task_progress(task_id: UUID, db: Session = Depends(get_db)):
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    images = [img for img in task.images if _is_visible_task_image(img)]
    analyzed = sum(1 for img in images if img.analysis and img.analysis.status in ("success", "partial", "skipped"))
    return {"task_id": task_id, "total_images": len(images), "analyzed": analyzed, "status": task.status}


@router.get("/tasks/{task_id}/images", response_model=list[schemas.SearchResult])
def task_images(task_id: UUID, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return [
        schemas.SearchResult(
            image=schemas.ImageOut.model_validate(image),
            analysis=schemas.AnalysisOut.model_validate(image.analysis) if image.analysis else None,
            similarity=None,
        )
        for image in crud.list_images(db, skip=skip, limit=limit, task_id=task_id)
        if _is_visible_task_image(image)
    ]

@router.get("/tasks/{task_id}/events")
async def task_events(task_id: UUID):
    """SSE 端点：实时推送任务进度更新"""
    tid = str(task_id)
    queue = ensure_queue(tid)

    async def event_generator():
        while True:
            try:
                # 等待队列消息，超时 30 秒发送 keep-alive
                msg = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"data: {msg}\n\n"
                if msg == "DONE":
                    break
            except asyncio.TimeoutError:
                yield ":heartbeat\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"}
    )
