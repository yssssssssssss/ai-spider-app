from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID
from typing import Optional
from app.database import get_db
from app import crud, schemas

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/requests", response_model=list[schemas.RequestOut])
def list_requests(status: Optional[str] = None, skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return crud.list_requests(db, status=status, skip=skip, limit=limit)

@router.put("/requests/{request_id}/approve", response_model=schemas.TaskOut)
def approve_request(request_id: UUID, body: schemas.ApproveRequest, db: Session = Depends(get_db)):
    req = crud.get_request(db, request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    crud.update_request_status(db, request_id, "approved")
    task = crud.create_task(
        db,
        name=f"Task from request {request_id}",
        keyword=body.keyword or (req.keywords[0] if req.keywords else ""),
        target_app=body.target_app or req.target_app,
        target_scenario=body.target_scenario or req.target_scenario,
        request_id=request_id,
        admin_id=body.admin_id
    )
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
    return task

@router.get("/tasks/{task_id}/progress")
def task_progress(task_id: UUID, db: Session = Depends(get_db)):
    task = crud.get_task(db, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    total = len(task.images)
    analyzed = sum(1 for img in task.images if img.analysis and img.analysis.status in ("success", "partial"))
    return {"task_id": task_id, "total_images": total, "analyzed": analyzed, "status": task.status}
