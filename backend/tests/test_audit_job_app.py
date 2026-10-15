"""App audit requirements through the executor, audit APIs and fake Worker APIs."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
import sys
from threading import Barrier
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image as PillowImage
from sqlalchemy.orm import Session

from app import models
from app.config import settings
from app.database import engine, get_db, init_db
from app.routers import admin, audit_workspace, worker
from app.services import audit_job_app, audit_jobs, task_queue, worker_dispatch
from app.services.auth import create_access_token
from app.services.inspection import Specification


@pytest.fixture(scope='module', autouse=True)
def test_database():
    if 'test' not in (engine.url.database or ''):
        pytest.skip('Never connect these tests to a development database')
    init_db()


@pytest.fixture
def db():
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
            yield session
        transaction.rollback()


@pytest.fixture(autouse=True)
def executor(monkeypatch, tmp_path):
    monkeypatch.setattr(audit_jobs, '_executors', {})
    audit_job_app.register()
    monkeypatch.setattr(settings, 'PROJECT_ROOT', str(tmp_path))
    monkeypatch.setattr(settings, 'WORKER_API_TOKEN', 'app-audit-test')
    monkeypatch.setattr(task_queue, 'refresh_devices', lambda db: ([], True))
    monkeypatch.setattr(worker_dispatch, '_finish_queue_tail', lambda: None)
    from app.services import collector_bridge, oss_uploader
    monkeypatch.setattr(collector_bridge, '_trigger_analysis', lambda image_id: None)
    monkeypatch.setattr(oss_uploader.oss_uploader, 'upload', lambda *a, **kw: {'success': False, 'error': 'offline'})

    async def plan(**kwargs):
        return '打开京东App，找到首页并截图保存到本地'

    monkeypatch.setattr(audit_job_app, 'plan_task', plan)
    yield
    audit_jobs._executors.clear()


@pytest.fixture
def version(db):
    spec = models.AuditSpec(key='app-job-' + uuid4().hex, name='App 视觉规范')
    db.add(spec)
    db.flush()
    version = models.AuditSpecVersion(
        spec_id=spec.id, version=1, label='v1', carrier_scope='both', source_json={}, sha256=uuid4().hex,
        rules_json=[
            {'rule_id': 'APP-1', 'title': '标题清晰', 'clause': '', 'expected': '标题完整可见',
             'enabled': True, 'carriers': ['app', 'h5']},
            {'rule_id': 'OFF', 'title': '禁用条目', 'expected': '不执行', 'enabled': False, 'carriers': ['app']},
            {'rule_id': 'H5', 'title': 'H5 条目', 'expected': '不执行', 'enabled': True, 'carriers': ['h5']},
        ],
    )
    db.add(version)
    db.commit()
    return version


@pytest.fixture
def client(db):
    app = FastAPI()
    for router in (admin.router, audit_workspace.router, worker.router):
        app.include_router(router, prefix='/api')
    app.dependency_overrides[get_db] = lambda: db
    user = models.User(username='app-job-' + uuid4().hex, password_hash='unused', role='operator')
    db.add(user)
    db.commit()
    with TestClient(app) as client:
        client.headers.update({'Authorization': 'Bearer ' + create_access_token(user),
                               'X-Worker-Token': 'app-audit-test'})
        yield client


def test_specification_skill_filters_rules_and_reuses_version(db, version):
    skill = audit_job_app.ensure_inspection_skill(db, version)
    spec = Specification.model_validate(skill.specification_json)
    assert spec.title == 'App 视觉规范'
    assert spec.version == 'v1'
    assert spec.source == f'audit_spec_version:{version.id}'
    assert [r.model_dump() for r in spec.rules] == [
        {'id': 'APP-1', 'clause': '标题清晰', 'expected': '标题完整可见'},
    ]
    assert skill.prompt.strip()
    assert (skill.skill_type, skill.status, skill.is_system) == ('inspection', 'active', True)
    assert audit_job_app.ensure_inspection_skill(db, version).id == skill.id
    assert db.query(models.AnalysisSkill).filter_by(skill_type='inspection').count() == 1


def test_concurrent_skill_creation_serializes_on_version():
    # Independent committed transactions are essential: a shared savepoint cannot test row locking.
    with Session(engine) as db:
        spec = models.AuditSpec(key='concurrent-' + uuid4().hex, name='并发规范')
        db.add(spec)
        db.flush()
        version = models.AuditSpecVersion(spec_id=spec.id, version=1, label='v1', carrier_scope='app',
            source_json={}, sha256=uuid4().hex, rules_json=[{
                'rule_id': 'ONE', 'title': '标题', 'expected': '完整', 'enabled': True, 'carriers': ['app'],
            }])
        db.add(version)
        db.commit()
        spec_id, version_id = spec.id, version.id
    barrier = Barrier(2)
    def create():
        with Session(engine) as db:
            version = db.get(models.AuditSpecVersion, version_id)
            barrier.wait(timeout=10)
            skill = audit_job_app.ensure_inspection_skill(db, version)
            skill_id = skill.id
            db.commit()
            return skill_id
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first, second = [pool.submit(create) for _ in range(2)]
            assert first.result(timeout=15) == second.result(timeout=15)
        with Session(engine) as db:
            assert db.query(models.AnalysisSkill).filter(
                models.AnalysisSkill.specification_json['source'].astext == f'audit_spec_version:{version_id}',
            ).count() == 1
    finally:
        with Session(engine) as db:
            db.query(models.AnalysisSkill).filter(
                models.AnalysisSkill.specification_json['source'].astext == f'audit_spec_version:{version_id}',
            ).delete(synchronize_session=False)
            db.query(models.AuditSpecVersion).filter_by(id=version_id).delete()
            db.query(models.AuditSpec).filter_by(id=spec_id).delete()
            db.commit()


def test_no_app_rules_unavailable_and_creation_returns_400(client, db, version):
    other = models.AuditSpecVersion(spec_id=version.spec_id, version=2, label='v2', carrier_scope='both',
        source_json={}, sha256=uuid4().hex, rules_json=version.rules_json[1:])
    db.add(other)
    db.commit()
    available, reason = audit_job_app.AppAuditExecutor().availability(other)
    assert available is False
    assert reason
    response = client.post('/api/audit-jobs', json=job_payload(other))
    assert response.status_code == 400, response.text
    assert db.query(models.AuditJob).count() == 0


def job_payload(version, **overrides):
    return {'name': '首页审核', 'carrier': 'app', 'phase': 'pre', 'spec_version_id': str(version.id),
            'input': {'target_name': '首页', 'business_key': 'home', 'target_app': '京东', 'scenario': '首页',
                      'description': '等待页面完整加载'}, **overrides}


@pytest.fixture
def device(client):
    serial = 'audit-device-' + uuid4().hex
    response = client.post('/api/worker/devices', json={
        'node_key': 'audit-node', 'devices': [{'serial': serial, 'status': 'online'}],
    })
    assert response.status_code == 200, response.text
    return next(item for item in response.json()['devices'] if item['serial'] == serial)


def create_job(client, version, device, **overrides):
    body = job_payload(version, **overrides)
    body['input']['device_id'] = device['id']
    response = client.post('/api/audit-jobs', json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_start_binds_skill_goals_creator_and_reuses_skill(client, db, version, device):
    first = create_job(client, version, device)
    second = create_job(client, version, device)
    assert first['executor_ref_json']['skill_id'] == second['executor_ref_json']['skill_id']
    assert db.query(models.AnalysisSkill).filter_by(skill_type='inspection').count() == 1
    task = db.get(models.Task, UUID(first['executor_ref_json']['task_id']))
    run = db.get(models.TaskRun, UUID(first['executor_ref_json']['task_run_id']))
    assert task.name == first['name']
    assert task.mode == 'autoglm'
    assert [str(value) for value in task.analysis_skill_ids] == [first['executor_ref_json']['skill_id']]
    assert task.target_goals_json == [
        {'label': '首页', 'type': 'page', 'required': True, 'evidence_keywords': ['首页']},
    ]
    assert '目标截图清单：1. 首页' in task.generated_instruction
    assert str(task.created_by) == str(task.approved_by) == first['created_by']
    assert run.device_id == UUID(device['id'])
    assert run.analysis_skills_snapshot_json[0]['specification_json']['source'] == f'audit_spec_version:{version.id}'
    assert (first['status'], first['status_detail']) == ('running', '已排队等待设备')


def test_start_planner_failure_falls_back_and_keeps_description(client, db, version, device, monkeypatch):
    async def fail(**kwargs):
        raise RuntimeError('planner unavailable')
    monkeypatch.setattr(audit_job_app, 'plan_task', fail)
    job = create_job(client, version, device)
    task = db.get(models.Task, UUID(job['executor_ref_json']['task_id']))
    assert '打开京东App' in task.generated_instruction
    assert '找到首页' in task.generated_instruction
    assert '等待页面完整加载' in task.generated_instruction
    assert '目标截图清单：1. 首页' in task.generated_instruction


def test_start_with_running_event_loop_calls_async_planner(db, version, device):
    async def create():
        return audit_jobs.create_job(db, **job_payload(version))
    job = asyncio.run(create())
    task = db.get(models.Task, UUID(job.executor_ref_json['task_id']))
    assert task.generated_instruction.startswith('打开京东App，找到首页并截图保存到本地')


def test_local_start_marks_executing_and_reserves_device(client, db, version, monkeypatch):
    from app.services import task_runner
    monkeypatch.setattr(task_runner, 'start_task_process', lambda *args, **kwargs: None)
    local = models.Device(serial='local-' + uuid4().hex, status='online')
    db.add(local)
    db.commit()
    job = create_job(client, version, {'id': str(local.id)})
    assert job['status_detail'] == '执行中'
    run = db.get(models.TaskRun, UUID(job['executor_ref_json']['task_run_id']))
    assert run.status == 'running'
    db.refresh(local)
    assert local.current_task_run_id == run.id
    assert local.status == 'busy'


@pytest.mark.parametrize('status,detail', [('pending', '已排队等待设备'), ('queued', '已排队等待设备'), ('running', '执行中')])
def test_active_run_reconcile_updates_progress(client, db, version, device, status, detail):
    job = create_job(client, version, device)
    run = db.get(models.TaskRun, UUID(job['executor_ref_json']['task_run_id']))
    run.status = status
    db.commit()
    response = client.get('/api/audit-jobs/' + job['id'])
    assert response.json()['status'] == 'running'
    assert response.json()['status_detail'] == detail


def test_empty_goals_rejected_without_writes(client, db, version, device):
    body = job_payload(version)
    body['input']['scenario'] = '，'
    body['input']['target_name'] = '，'
    response = client.post('/api/audit-jobs', json=body)
    assert response.status_code == 400, response.text
    assert db.query(models.AuditJob).count() == db.query(models.Task).count() == 0
    assert db.query(models.AnalysisSkill).filter_by(skill_type='inspection').count() == 0


@pytest.mark.parametrize('error', [task_queue.TaskQueueError, ValueError])
def test_enqueue_failure_rolls_back_all_creation(client, db, version, device, monkeypatch, error):
    enqueue = task_queue._enqueue_task
    def fail_after_enqueue(*args, **kwargs):
        enqueue(*args, **kwargs)  # Exercise the legacy CRUD commits before failing.
        raise error('queue unavailable')
    monkeypatch.setattr(task_queue, '_enqueue_task', fail_after_enqueue)
    response = client.post('/api/audit-jobs', json=job_payload(version))
    assert response.status_code == 400, response.text
    assert 'queue unavailable' in response.text
    for model in (models.AuditJob, models.Task, models.TaskRun):
        assert db.query(model).count() == 0
    assert db.query(models.AnalysisSkill).filter_by(skill_type='inspection').count() == 0


@pytest.mark.parametrize('mode,instruction', [('autoglm', None), ('autoglm', '原有指令'), ('uiautomator2', None)])
def test_admin_run_task_retains_existing_start_behavior(client, db, device, mode, instruction):
    task = models.Task(name='原有任务', mode=mode, status='pending', target_app='京东',
                       target_scenario='首页', generated_instruction=instruction,
                       target_goals_json=[{'label': '首页'}])
    db.add(task)
    db.commit()
    response = client.post(f'/api/admin/tasks/{task.id}/run', json={'device_id': device['id']})
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'queued'
    db.refresh(task)
    if instruction:
        assert task.generated_instruction == instruction
    elif mode == 'autoglm':
        assert '目标截图清单：1. 首页' in task.generated_instruction
    else:
        assert task.generated_instruction is None


def claim(client, job, device):
    response = client.post('/api/worker/task-runs/claim', json={
        'node_key': 'audit-node', 'device_serials': [device['serial']], 'capabilities': ['autoglm'],
    })
    assert response.status_code == 200, response.text
    assert response.json()['claimed'] is True
    assert response.json()['run']['id'] == job['executor_ref_json']['task_run_id']


def artifact(client, job, color='red'):
    output = BytesIO()
    PillowImage.new('RGB', (8, 8), color).save(output, format='PNG')
    response = client.post(f"/api/worker/task-runs/{job['executor_ref_json']['task_run_id']}/artifacts",
        data={'node_key': 'audit-node'}, files={'file': ('screen.png', output.getvalue(), 'image/png')})
    assert response.status_code == 200, response.text
    return UUID(response.json()['image_id'])


def finish(client, job, verdict='reached', **result):
    run_id = job['executor_ref_json']['task_run_id']
    response = client.post(f'/api/worker/task-runs/{run_id}/result', json={
        'node_key': 'audit-node', 'result_json': {**({'target_verification': verdict} if verdict else {}), **result},
    })
    assert response.status_code == 200, response.text
    response = client.post(f'/api/worker/task-runs/{run_id}/finish', json={
        'node_key': 'audit-node', 'exit_code': 0, 'screenshot_count': 1,
    })
    assert response.status_code == 200, response.text
    return response.json()


def analysis(db, job, image_id, status='success', checks=True):
    row = models.Analysis(image_id=image_id, skill_id=UUID(job['executor_ref_json']['skill_id']),
                          status=status, design_analysis='首页标题清晰')
    if checks:
        row.inspection_json = {'checks': [
            {'rule_id': 'APP-1', 'clause': '标题清晰', 'expected': '标题完整可见',
             'status': 'pass', 'observed': '标题完整', 'reason': '文字没有截断'},
        ]}
    db.add(row)
    db.commit()
    return row


def test_worker_flow_waits_for_selected_skill_ingests_once_and_links_baseline(client, db, version, device):
    project = models.AuditProject(name='App 项目')
    db.add(project)
    db.commit()
    pre = create_job(client, version, device, project_id=str(project.id))
    claim(client, pre, device)
    image_id = artifact(client, pre)
    second_image_id = artifact(client, pre, 'blue')
    # Transient captures without inspection analyses must not delay ingestion.
    db.add(models.Image(file_path='captures/_temp_probe.png', task_id=UUID(pre['executor_ref_json']['task_id']),
                         task_run_id=UUID(pre['executor_ref_json']['task_run_id'])))
    # A completed default analysis must not mask a missing inspection Skill analysis.
    db.add(models.Analysis(image_id=image_id, status='success', design_analysis='首页'))
    db.commit()
    analysis(db, pre, second_image_id)
    finish(client, pre)
    job = db.get(models.AuditJob, UUID(pre['id']))
    db.refresh(job)
    assert (job.status, job.status_detail) == ('ingesting', '截图分析中 1/2')
    assert db.query(models.AuditRun).count() == 0
    pending = analysis(db, pre, image_id, status='running')
    response = client.get('/api/audit-jobs/' + pre['id'])
    assert response.json()['status'] == 'ingesting'
    pending.status = 'success'
    db.commit()
    response = client.get('/api/audit-jobs/' + pre['id'])
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'completed'
    pre_run = db.get(models.AuditRun, UUID(response.json()['audit_run_id']))
    assert pre_run.project_id == project.id
    assert pre_run.targets[0].business_key == 'home'
    assert pre_run.targets[0].name == '首页'
    assert pre_run.phase == 'pre'
    audit_jobs.reconcile_job(db, job)
    audit_jobs.reconcile_job(db, job)
    assert db.query(models.AuditRun).count() == 1

    post = create_job(client, version, device, phase='post', project_id=str(project.id))
    claim(client, post, device)
    analysis(db, post, artifact(client, post))
    finish(client, post)
    response = client.get('/api/audit-jobs/' + post['id'])
    assert response.json()['status'] == 'completed'
    post_run = db.get(models.AuditRun, UUID(response.json()['audit_run_id']))
    assert post_run.project_id == project.id
    assert post_run.targets[0].baseline_target_id == pre_run.targets[0].id


@pytest.mark.parametrize('verdict', ['not_reached', 'uncertain', None, 'disabled'])
def test_unverified_target_fails_without_audit_run(client, db, version, device, verdict):
    job = create_job(client, version, device)
    claim(client, job, device)
    analysis(db, job, artifact(client, job))
    finish(client, job, verdict, target_verification_records=[{'reason': '页面标题不符'}])
    response = client.get('/api/audit-jobs/' + job['id'])
    assert response.json()['status'] == 'failed'
    assert '目标页未确认到达，未收录' in response.json()['error']
    assert '页面标题不符' in response.json()['error']
    assert db.query(models.AuditRun).count() == 0


@pytest.mark.parametrize('validation', [
    {'status': 'missing', 'reason': '缺少目标页截图：首页'},
    {'status': 'missing', 'missing': ['首页']},
])
def test_missing_goal_fails_even_when_target_verification_reached(client, db, version, device, validation):
    job = create_job(client, version, device)
    claim(client, job, device)
    analysis(db, job, artifact(client, job))
    run = db.get(models.TaskRun, UUID(job['executor_ref_json']['task_run_id']))
    run.goal_validation_json = validation
    db.commit()
    finish(client, job)
    response = client.get('/api/audit-jobs/' + job['id'])
    assert response.json()['status'] == 'failed'
    assert '目标页未确认到达，未收录' in response.json()['error']
    assert '缺少目标页截图：首页' in response.json()['error']
    assert db.query(models.AuditRun).count() == 0


@pytest.mark.parametrize('status', ['success', 'partial', 'skipped', 'failed'])
def test_final_analyses_without_checks_fail_instead_of_waiting(client, db, version, device, status):
    job = create_job(client, version, device)
    claim(client, job, device)
    analysis(db, job, artifact(client, job), status=status, checks=False)
    finish(client, job)
    response = client.get('/api/audit-jobs/' + job['id'])
    assert response.json()['status'] == 'failed'
    assert 'inspection results' in response.json()['error']
    assert db.query(models.AuditRun).count() == 0


def test_worker_fail_hook_sets_job_failure(client, db, version, device):
    job = create_job(client, version, device)
    claim(client, job, device)
    response = client.post(f"/api/worker/task-runs/{job['executor_ref_json']['task_run_id']}/fail", json={
        'node_key': 'audit-node', 'exit_code': 1, 'failure_reason': '设备连接中断',
    })
    assert response.status_code == 200, response.text
    row = db.get(models.AuditJob, UUID(job['id']))
    db.refresh(row)
    assert (row.status, row.error) == ('failed', '设备连接中断')


@pytest.mark.parametrize('running', [False, True])
def test_cancel_queue_or_leave_running_device_and_never_ingest(client, db, version, device, running):
    job = create_job(client, version, device)
    if running:
        claim(client, job, device)
    else:
        # Cover release of a reservation as well as preventing future claims.
        reserved = db.get(models.Device, UUID(device['id']))
        reserved.status = 'busy'
        reserved.current_task_run_id = UUID(job['executor_ref_json']['task_run_id'])
        db.commit()
    response = client.post('/api/audit-jobs/' + job['id'] + '/cancel')
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'cancelled'
    run = db.get(models.TaskRun, UUID(job['executor_ref_json']['task_run_id']))
    db.refresh(run)
    device_row = db.get(models.Device, UUID(device['id']))
    db.refresh(device_row)
    if running:
        assert response.json()['status_detail'] == '设备任务继续运行，结果不会收录'
        assert run.status == 'running'
        assert device_row.current_task_run_id == run.id
        analysis(db, job, artifact(client, job))
        finish(client, job)
    else:
        assert run.status == run.task.status == 'failed'
        assert run.failure_reason == '审核任务已取消'
        assert device_row.current_task_run_id is None
        assert device_row.status == 'online'
        response = client.post('/api/worker/task-runs/claim', json={
            'node_key': 'audit-node', 'device_serials': [device['serial']], 'capabilities': ['autoglm'],
        })
        assert response.json()['claimed'] is False
    assert client.get('/api/audit-jobs/' + job['id']).json()['status'] == 'cancelled'
    assert db.query(models.AuditRun).count() == 0


def test_resume_is_unsupported(db):
    with pytest.raises(audit_jobs.InvalidJobTransition):
        audit_job_app.AppAuditExecutor().resume(db, models.AuditJob(status='running'))


@pytest.mark.parametrize('database_error', [False, True])
def test_reconcile_hook_error_rolls_back_only_hook_and_worker_finish_returns_200(client, db, version, device, monkeypatch, database_error):
    job = create_job(client, version, device)
    claim(client, job, device)
    artifact(client, job)
    def broken(db, row):
        row.error = '不得保存的修改'
        if database_error:
            db.add(models.AnalysisSkill(name='无效的 Skill', prompt=None))
        db.flush()
        raise RuntimeError('hook unavailable')
    monkeypatch.setattr(audit_jobs, 'reconcile_job', broken)
    response = finish(client, job)
    assert response['status'] == 'completed'
    row = db.get(models.AuditJob, UUID(job['id']))
    db.refresh(row)
    assert row.error is None
    assert row.status == 'running'
