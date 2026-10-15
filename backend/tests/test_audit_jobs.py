"""Lifecycle and API requirements for the AuditJob skeleton (no real executors)."""
from datetime import datetime
from pathlib import Path
import sys
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app import models
from app.database import engine, get_db, init_db
from app.routers import audit_workspace
from app.services import audit_jobs as jobs
from app.services.auth import create_access_token

STATUSES = ('queued', 'running', 'needs_action', 'ingesting', 'completed', 'failed', 'cancelled')
# Independent specification of the allowed edges, rather than reading the implementation's map.
EDGES = {
    ('queued', 'running'), ('running', 'ingesting'), ('ingesting', 'completed'),
    ('running', 'needs_action'), ('needs_action', 'running'),
    *((source, target) for source in ('queued', 'running', 'needs_action', 'ingesting')
      for target in ('failed', 'cancelled')),
}


@pytest.mark.parametrize('source', STATUSES)
@pytest.mark.parametrize('target', STATUSES)
def test_every_state_transition(source, target):
    job = models.AuditJob(status=source)
    if (source, target) in EDGES:
        jobs.transition_job(job, target, status_detail='进度', error='原因' if target == 'failed' else None)
        assert job.status == target
        assert job.status_detail == '进度'
        assert bool(job.finished_at) == (target in {'completed', 'failed', 'cancelled'})
    else:
        with pytest.raises(jobs.InvalidJobTransition):
            jobs.transition_job(job, target)
        assert job.status == source
        assert job.finished_at is None


@pytest.fixture
def db():
    if 'test' not in (engine.url.database or ''):
        pytest.skip('Never connect these tests to a development database')
    init_db()
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode='create_savepoint') as session:
            yield session
        transaction.rollback()


@pytest.fixture(autouse=True)
def registry(monkeypatch):
    monkeypatch.setattr(jobs, '_executors', {})


@pytest.fixture
def version(db):
    spec = models.AuditSpec(key='jobs-' + uuid4().hex, name='审核规范')
    db.add(spec)
    db.flush()
    version = models.AuditSpecVersion(spec_id=spec.id, version=1, label='v1', carrier_scope='both',
                                      rules_json=[], source_json={'audit_mode': 'h5_v2'}, sha256=uuid4().hex)
    db.add(version)
    db.commit()
    return version


@pytest.fixture
def project(db):
    project = models.AuditProject(name='测试项目')
    db.add(project)
    db.commit()
    return project


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(audit_workspace.router, prefix='/api')
    app.dependency_overrides[get_db] = lambda: db
    user = models.User(username='jobs-' + uuid4().hex, password_hash='unused', role='operator')
    db.add(user)
    db.commit()
    with TestClient(app) as client:
        client.headers['Authorization'] = 'Bearer ' + create_access_token(user)
        yield client


class FakeExecutor:
    def __init__(self, available=True):
        self.available = available
        self.starts = self.reconciles = self.resumes = self.cancels = 0

    def availability(self, spec_version):
        return self.available, None if self.available else '测试执行器不可用'

    def start(self, db, job):
        self.starts += 1  # Simulate waiting for an asynchronous worker to claim the job.

    def reconcile(self, db, job):
        self.reconciles += 1
        if job.status == 'queued':
            jobs.transition_job(job, 'running')
        elif job.status == 'running':
            jobs.transition_job(job, 'ingesting')
        elif job.status == 'ingesting':
            run = models.AuditRun(name=job.name, carrier=job.carrier, phase=job.phase,
                                   spec_version_id=job.spec_version_id, source_kind='app_task_run',
                                   summary_json={'targets': 0, 'outcomes': {}, 'capture_reasons': {}})
            db.add(run)
            db.flush()
            jobs.complete_with_run(db, job, run)

    def resume(self, db, job):
        self.resumes += 1

    def cancel(self, db, job):
        self.cancels += 1


def payload(version, **overrides):
    return {'name': '第一次审核', 'carrier': 'app', 'phase': 'pre', 'spec_version_id': str(version.id),
            'input': {'target_name': '首页', 'target_app': '京东', 'scenario': '首页走查'}, **overrides}


def job_row(db, version, status='queued', project_id=None):
    job = models.AuditJob(name='测试任务', carrier='app', phase='pre', spec_version_id=version.id,
                          status=status, project_id=project_id)
    if status in jobs.TERMINAL_STATUSES:
        job.finished_at = datetime(2026, 10, 15)
    db.add(job)
    db.flush()
    return job


@pytest.mark.parametrize('failure', ['scope', 'project', 'executor', 'spec', 'h5_mode'])
def test_create_validation_400_without_writes(client, db, version, failure):
    body = payload(version)
    jobs.register_executor('app', FakeExecutor())
    if failure in {'scope', 'h5_mode'}:
        replacement = models.AuditSpecVersion(spec_id=version.spec_id, version=2, label='v2',
            carrier_scope='h5' if failure == 'scope' else 'both', rules_json=[],
            source_json={} if failure == 'h5_mode' else {'audit_mode': 'h5_v2'}, sha256=uuid4().hex)
        db.add(replacement)
        db.commit()
        body['spec_version_id'] = str(replacement.id)
    if failure == 'project':
        body['project_id'] = str(uuid4())
    elif failure == 'executor':
        jobs.register_executor('app', FakeExecutor(available=False))
    elif failure == 'spec':
        body['spec_version_id'] = str(uuid4())
    elif failure == 'h5_mode':
        body['carrier'] = 'h5'
        jobs.register_executor('h5', FakeExecutor())
    response = client.post('/api/audit-jobs', json=body)
    assert response.status_code == 400, response.text
    assert db.query(models.AuditJob).count() == 0


def test_unregistered_executor_availability_and_create(client, db, version):
    for carrier in ('h5', 'app'):
        response = client.get(f'/api/audit-specs/versions/{version.id}/executor', params={'carrier': carrier})
        assert response.status_code == 200
        assert response.json() == {'available': False, 'reason': '该载体的执行器尚未接入'}
        response = client.post('/api/audit-jobs', json=payload(version, carrier=carrier))
        assert response.status_code == 400
    assert db.query(models.AuditJob).count() == 0


@pytest.mark.parametrize('status', ['completed', 'failed', 'cancelled'])
@pytest.mark.parametrize('action', ['continue', 'cancel'])
def test_terminal_actions_are_409(client, db, version, status, action):
    executor = FakeExecutor()
    jobs.register_executor('app', executor)
    job = job_row(db, version, status)
    finished_at = job.finished_at
    db.commit()
    response = client.post(f'/api/audit-jobs/{job.id}/{action}')
    assert response.status_code == 409, response.text
    db.refresh(job)
    assert job.status == status
    assert job.finished_at == finished_at
    assert executor.resumes == executor.cancels == 0


def test_fake_executor_full_flow_and_idempotent_reconcile(client, db, version, project):
    executor = FakeExecutor()
    jobs.register_executor('app', executor)
    response = client.post('/api/audit-jobs', json=payload(version, project_id=str(project.id)))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['status'] == 'queued'
    assert data['input_json']['target_name'] == '首页'
    assert data['created_by'] is not None
    assert executor.starts == 1
    job_id = data['id']
    for expected in ('running', 'ingesting', 'completed', 'completed'):
        response = client.get('/api/audit-jobs/' + job_id)
        assert response.status_code == 200, response.text
        assert response.json()['status'] == expected
    job = db.get(models.AuditJob, UUID(job_id))
    run_id = job.audit_run_id
    jobs.reconcile_job(db, job)
    jobs.reconcile_job(db, job)
    assert db.query(models.AuditRun).count() == 1
    assert job.audit_run_id == run_id
    assert job.finished_at is not None
    assert db.get(models.AuditRun, run_id).project_id == project.id
    assert executor.reconciles == 3


def test_list_filters_reconcile_and_project_read(client, db, version, project):
    executor = FakeExecutor()
    jobs.register_executor('app', executor)
    job = job_row(db, version, project_id=project.id)
    independent = job_row(db, version)
    terminal = job_row(db, version, 'failed', project.id)
    response = client.get('/api/audit-jobs', params={'project_id': str(project.id), 'status': 'active'})
    assert [row['id'] for row in response.json()] == [str(job.id)]
    assert response.json()[0]['status'] == 'running'
    assert independent.status == 'queued'
    response = client.get('/api/audit-jobs', params={'project_id': str(project.id), 'status': 'all'})
    assert {row['id'] for row in response.json()} == {str(job.id), str(terminal.id)}
    assert db.get(models.AuditJob, job.id).status == 'ingesting'
    response = client.get(f'/api/audit-projects/{project.id}')
    assert response.status_code == 200, response.text
    assert response.json()['run_count'] == 1
    assert db.get(models.AuditJob, job.id).status == 'completed'


def test_active_list_excludes_jobs_completed_during_reconcile(client, db, version):
    jobs.register_executor('app', FakeExecutor())
    job = job_row(db, version, 'ingesting')
    response = client.get('/api/audit-jobs', params={'status': 'active'})
    assert response.status_code == 200, response.text
    assert response.json() == []
    assert db.get(models.AuditJob, job.id).status == 'completed'
    assert db.query(models.AuditRun).count() == 1


def test_continue_and_cancel_hooks(client, db, version):
    executor = FakeExecutor()
    jobs.register_executor('app', executor)
    job = job_row(db, version, 'needs_action')
    response = client.post(f'/api/audit-jobs/{job.id}/continue')
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'running'
    assert executor.resumes == 1
    assert client.post(f'/api/audit-jobs/{job.id}/continue').status_code == 409
    response = client.post(f'/api/audit-jobs/{job.id}/cancel')
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'cancelled'
    assert response.json()['finished_at'] is not None
    assert executor.cancels == 1


def test_complete_preserves_existing_project(db, version, project):
    other = models.AuditProject(name='已有归属')
    db.add(other)
    db.flush()
    run = models.AuditRun(name='已有结果', carrier='app', phase='pre', spec_version_id=version.id,
                           project_id=other.id, source_kind='app_task_run')
    db.add(run)
    job = job_row(db, version, 'ingesting', project.id)
    jobs.complete_with_run(db, job, run)
    assert job.audit_run_id == run.id
    assert run.project_id == other.id


def make_run(db, version, carrier='h5', phase='pre'):
    run = models.AuditRun(name='可归入审核', carrier=carrier, phase=phase, spec_version_id=version.id,
                           source_kind='h5_import' if carrier == 'h5' else 'app_task_run',
                           targets=[models.AuditTarget(name='首页', business_key='home', outcome='clean')])
    db.add(run)
    db.flush()
    return run


def test_batch_assign_both_carriers_and_baseline(client, db, version, project):
    pre = make_run(db, version)
    post = make_run(db, version, 'app', 'post')
    response = client.get('/api/audit-runs', params={'unassigned': True})
    assert {row['carrier'] for row in response.json()} == {'h5', 'app'}
    response = client.post(f'/api/audit-projects/{project.id}/assign-runs',
                           json={'run_ids': [str(post.id), str(pre.id), str(pre.id)]})
    assert response.status_code == 200, response.text
    db.refresh(pre)
    db.refresh(post)
    assert pre.project_id == post.project_id == project.id
    assert post.targets[0].baseline_target_id == pre.targets[0].id


def test_batch_missing_id_has_zero_writes(client, db, version, project):
    pre = make_run(db, version)
    post = make_run(db, version, 'app', 'post')
    db.commit()
    response = client.post(f'/api/audit-projects/{project.id}/assign-runs',
                           json={'run_ids': [str(pre.id), str(post.id), str(uuid4())]})
    assert response.status_code == 400, response.text
    db.refresh(pre)
    db.refresh(post)
    assert pre.project_id is post.project_id is None
    assert post.targets[0].baseline_target_id is None


def test_viewer_reads_but_all_writes_forbidden(client, db, version, project):
    user = models.User(username='viewer-' + uuid4().hex, password_hash='unused', role='viewer')
    db.add(user)
    db.flush()
    job = job_row(db, version, 'needs_action')
    client.headers['Authorization'] = 'Bearer ' + create_access_token(user)
    for path in ('/api/audit-jobs', f'/api/audit-jobs/{job.id}',
                 f'/api/audit-specs/versions/{version.id}/executor?carrier=app'):
        assert client.get(path).status_code == 200
    for path, body in [('/api/audit-jobs', payload(version)),
                       (f'/api/audit-jobs/{job.id}/continue', None),
                       (f'/api/audit-jobs/{job.id}/cancel', None),
                       (f'/api/audit-projects/{project.id}/assign-runs', {'run_ids': [str(uuid4())]})]:
        assert client.post(path, json=body).status_code == 403
    client.headers.clear()
    assert client.get('/api/audit-jobs').status_code == 401


def test_missing_jobs_are_404(client):
    for action in ('', '/continue', '/cancel'):
        method = client.get if not action else client.post
        assert method('/api/audit-jobs/' + str(uuid4()) + action).status_code == 404
