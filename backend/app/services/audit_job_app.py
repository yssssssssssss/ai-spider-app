"""App audit execution. The AuditJob caller owns the transaction."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app import crud, models
from app.services import audit_jobs
from app.services.audit_workspace import create_app_run
from app.services.goal_validator import FINAL_ANALYSIS_STATUSES, missing_goal_failure_reason
from app.services.inspection import Specification
from app.services.task_execution import build_autoglm_prompt, start_task
from app.services.task_goals import append_target_goal_checklist, build_target_goals
from app.services.task_planner import plan_task

logger = logging.getLogger(__name__)


def _plan_instruction(task: models.Task, description: str | None) -> str:
    def plan():
        return asyncio.run(plan_task(target_app=task.target_app, target_scenario=task.target_scenario,
                                     keywords=[], description=description))
    try:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            instruction = plan()
        else:
            # asyncio.run cannot nest inside an event loop; only the planner runs in this thread.
            with ThreadPoolExecutor(max_workers=1) as pool:
                instruction = pool.submit(plan).result()
        if not instruction or not instruction.strip():
            raise ValueError('Planner returned an empty instruction')
    except Exception:
        logger.warning('App audit planner failed; using task prompt template', exc_info=True)
        instruction = build_autoglm_prompt(task, description=description)
    return append_target_goal_checklist(instruction, task.target_goals_json)


def _run_detail(run: models.TaskRun) -> str:
    return '执行中' if run.status == 'running' else '已排队等待设备'


def _app_rules(spec_version: models.AuditSpecVersion) -> list[dict]:
    return [rule for rule in spec_version.rules_json
            if rule.get('enabled') and 'app' in rule.get('carriers', [])]


def ensure_inspection_skill(db: Session, spec_version: models.AuditSpecVersion) -> models.AnalysisSkill:
    # Hold this lock until the caller commits, including the lookup after a concurrent creator.
    spec_version = db.query(models.AuditSpecVersion).filter_by(id=spec_version.id).with_for_update().one()
    source = f'audit_spec_version:{spec_version.id}'
    existing = db.query(models.AnalysisSkill).filter(
        models.AnalysisSkill.specification_json['source'].astext == source,
    ).first()
    if existing is not None:
        return existing
    rules = [{'id': rule['rule_id'], 'clause': (rule.get('clause') or '').strip() or rule.get('title') or rule['rule_id'],
              'expected': rule['expected']} for rule in _app_rules(spec_version)]
    specification = Specification(
        title=spec_version.spec.name, version=spec_version.label, source=source,
        document='\n\n'.join(f"{rule['id']} {rule['clause']}\n{rule['expected']}" for rule in rules), rules=rules,
    )
    skill = models.AnalysisSkill(
        # The analyzer renders inspection_prompt from specification_json; prompt is its supplement.
        name=f'{specification.title} {specification.version}', prompt='按绑定规范逐项检查截图。',
        specification_json=specification.model_dump(), skill_type='inspection', status='active', is_system=True,
    )
    db.add(skill)
    db.flush()
    return skill


class AppAuditExecutor:
    def availability(self, spec_version: models.AuditSpecVersion) -> tuple[bool, str | None]:
        return (True, None) if _app_rules(spec_version) else (False, '规范版本没有已启用的 App 规则')

    def start(self, db: Session, job: models.AuditJob) -> None:
        inputs = job.input_json
        for field in ('target_name', 'target_app', 'scenario'):
            if not isinstance(inputs.get(field), str) or not inputs[field].strip():
                raise ValueError(f'{field} is required')
        for field in ('description', 'business_key'):
            if inputs.get(field) is not None and not isinstance(inputs[field], str):
                raise ValueError(f'{field} must be a string')
        goals = [goal for goal in build_target_goals(
            inputs['target_app'], inputs['scenario'], [], inputs.get('description')) if goal.get('label')]
        if not goals:
            raise ValueError('目标截图清单不能为空')
        device_id = UUID(str(inputs['device_id'])) if inputs.get('device_id') else None
        skill = ensure_inspection_skill(db, db.get(models.AuditSpecVersion, job.spec_version_id))
        # Legacy CRUD commits must release savepoints, never the AuditJob transaction or version lock.
        with Session(bind=db.connection(), join_transaction_mode='create_savepoint') as task_db:
            task = crud.create_task(task_db, name=job.name, keyword='', target_app=inputs['target_app'],
                                    target_scenario=inputs['scenario'], mode='autoglm',
                                    created_by=job.created_by, approved_by=job.created_by, target_goals_json=goals)
            task.analysis_skill_ids = [skill.id]
            task.generated_instruction = _plan_instruction(task, inputs.get('description'))
            task_db.flush()
            try:
                decision = start_task(task_db, task, created_by=job.created_by, requested_device_id=device_id)
            except ValueError as exc:
                raise ValueError(str(exc)) from exc
            if decision.run is None:
                raise ValueError('Task startup did not create a run')
            job.executor_ref_json = {'skill_id': str(skill.id), 'task_id': str(task.id),
                                     'task_run_id': str(decision.run.id)}
            audit_jobs.transition_job(job, 'running', status_detail=_run_detail(decision.run))
            task_db.commit()

    def reconcile(self, db: Session, job: models.AuditJob) -> None:
        if job.status in audit_jobs.TERMINAL_STATUSES:
            return
        refs = job.executor_ref_json
        run = db.query(models.TaskRun).filter_by(id=UUID(refs['task_run_id'])).populate_existing().one_or_none()
        if run is None:
            audit_jobs.transition_job(job, 'failed', error='设备任务不存在')
            return
        if run.status in {'pending', 'queued', 'running'}:
            job.status_detail = _run_detail(run)
            return
        if run.status == 'failed':
            audit_jobs.transition_job(job, 'failed', error=run.failure_reason)
            return
        if run.status != 'completed':
            return
        result = run.result_json if isinstance(run.result_json, dict) else {}
        goal = run.goal_validation_json if isinstance(run.goal_validation_json, dict) else {}
        verification = result.get('target_verification')
        if verification != 'reached' or goal.get('status') == 'missing':
            reasons = [f'target_verification={verification or "missing"}']
            for record in result.get('target_verification_records') or []:
                if isinstance(record, dict) and record.get('reason'):
                    reasons.append(str(record['reason']))
            if goal.get('status') == 'missing':
                reasons.append(missing_goal_failure_reason(goal))
            elif goal.get('reason'):
                reasons.append(str(goal['reason']))
            audit_jobs.transition_job(job, 'failed', error='目标页未确认到达，未收录：' + '；'.join(reasons))
            return
        skill_id = UUID(refs['skill_id'])
        rows = db.query(models.Image.file_path, models.Analysis.status).outerjoin(
            models.Analysis, and_(models.Analysis.image_id == models.Image.id, models.Analysis.skill_id == skill_id),
        ).filter(models.Image.task_run_id == run.id).all()
        statuses = [status for file_path, status in rows if not Path(file_path).name.startswith('_temp_')]
        done = sum(status in FINAL_ANALYSIS_STATUSES for status in statuses)
        detail = f'截图分析中 {done}/{len(statuses)}'
        if job.status != 'ingesting':
            audit_jobs.transition_job(job, 'ingesting', status_detail=detail)
        else:
            job.status_detail = detail
        if done != len(statuses):
            return
        try:
            audit_run = create_app_run(
                db, task_run_id=run.id, skill_id=skill_id,
                spec_version=db.get(models.AuditSpecVersion, job.spec_version_id), name=job.name,
                target_name=job.input_json['target_name'], business_key=job.input_json.get('business_key'),
                phase=job.phase, project=db.get(models.AuditProject, job.project_id) if job.project_id else None,
                user_id=job.created_by,
            )
        except ValueError as exc:
            audit_jobs.transition_job(job, 'failed', error=str(exc))
            return
        audit_jobs.complete_with_run(db, job, audit_run)

    def cancel(self, db: Session, job: models.AuditJob) -> None:
        run = db.query(models.TaskRun).filter_by(
            id=UUID(job.executor_ref_json['task_run_id']),
        ).with_for_update().populate_existing().one_or_none()
        if run is None:
            return
        if run.status == 'running':
            job.status_detail = '设备任务继续运行，结果不会收录'
        elif run.status in {'pending', 'queued'}:
            run.status = run.task.status = 'failed'
            run.failure_reason = '审核任务已取消'
            run.completed_at = models.utc_now()
            db.flush()
            # Reuse device release without allowing its legacy commit to release the job lock.
            with Session(bind=db.connection(), join_transaction_mode='create_savepoint') as task_db:
                crud.release_device_for_run(task_db, run.id)
                task_db.commit()

    def resume(self, db: Session, job: models.AuditJob) -> None:
        raise audit_jobs.InvalidJobTransition('App 审核不支持继续操作')


def register() -> None:
    audit_jobs.register_executor('app', AppAuditExecutor())
