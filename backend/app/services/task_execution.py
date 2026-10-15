"""Shared prompt selection and task startup for operators and audit executors."""
from uuid import UUID

from sqlalchemy.orm import Session

from app import models
from app.services.task_goals import append_target_goal_checklist
from app.services.task_planner import append_execution_rules, keyword_instruction
from app.services.task_queue import TaskQueueDecision, start_or_enqueue_task


def build_autoglm_prompt(task, *, description: str | None = None) -> str:
    parts = []
    req = task.request
    app_name = task.target_app or (req.target_app if req else None)
    if app_name:
        parts.append(f'打开{app_name}App')
    keyword = task.keyword
    if req and req.keywords:
        keyword = '、'.join(req.keywords)
    scenario = task.target_scenario or (req.target_scenario if req else None)
    keyword_part = keyword_instruction([keyword] if keyword else [], scenario)
    if keyword_part:
        parts.append(keyword_part)
    if scenario:
        parts.append(f'找到{scenario}')
    description = description if description is not None else (req.description if req else None)
    if description:
        parts.append(description)
    parts.append('并截图保存到本地')
    instruction = append_execution_rules('，'.join(parts))
    return append_target_goal_checklist(instruction, getattr(task, 'target_goals_json', None))


def start_task(db: Session, task: models.Task, *, created_by: UUID | None,
               requested_device_id: UUID | None = None) -> TaskQueueDecision:
    prompt = (task.generated_instruction or build_autoglm_prompt(task)) if task.mode == 'autoglm' else None
    return start_or_enqueue_task(db, task, created_by=created_by,
                                 requested_device_id=requested_device_id, prompt=prompt)
