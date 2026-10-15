"""T9d contracts: append-only decisions, effective closure and rule accuracy."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]
from app import models
from app.database import engine, get_db, ensure_schema
from app.routers import audit_workspace as router
from app.services import audit_analytics as analytics
from app.services.auth import create_access_token
from scripts.export_gold_set import export_run


def rule(rid):
    return {'rule_id': rid, 'title': rid, 'enabled': True, 'carriers': ['h5'], 'clause': '一', 'duplicate_of': None}


@pytest.mark.parametrize('status,review,expected,excepted,recapture', [
    ('fail', None, 'fail', False, False),
    ('pass', {'verdict': 'confirmed'}, 'pass', False, False),
    ('fail', {'verdict': 'confirmed'}, 'fail', False, False),
    ('uncertain', {'verdict': 'confirmed'}, 'fail', False, False),
    ('fail', {'verdict': 'false_positive'}, 'pass', False, False),
    ('fail', {'verdict': 'false_positive', 'corrected_status': 'not_applicable'}, 'not_applicable', False, False),
    ('pass', {'verdict': 'false_negative'}, 'fail', False, False),
    ('not_applicable', {'verdict': 'false_negative', 'corrected_status': 'pass'}, 'pass', False, False),
    ('fail', {'verdict': 'exception', 'corrected_status': 'fail'}, 'pass', True, False),
    ('uncertain', {'verdict': 'recapture', 'corrected_status': 'fail'}, 'uncertain', False, True),
])
def test_effective_status(status, review, expected, excepted, recapture):
    before = deepcopy(review)
    assert analytics.effective_status(status, review) == {
        'effective_status': expected, 'excepted': excepted, 'needs_recapture': recapture}
    assert review == before


@pytest.fixture
def context():
    assert 'test' in (engine.url.database or ''), 'Use a disposable test database'
    ensure_schema()
    with engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode='create_savepoint') as db:
            spec = models.AuditSpec(key=uuid4().hex, name='复核规范')
            version = models.AuditSpecVersion(spec=spec, version=1, label='v1', carrier_scope='h5',
                sha256=uuid4().hex, source_json={}, rules_json=[rule('A'), rule('B'), rule('C')])
            project = models.AuditProject(name='复核项目')
            pre = models.AuditRun(name='pre', carrier='h5', phase='pre', spec_version=version, project=project,
                source_kind='h5_import', source_ref_json={})
            post = models.AuditRun(name='post', carrier='h5', phase='post', spec_version=version, project=project,
                source_kind='h5_import', source_ref_json={}, created_at=models.utc_now() + timedelta(seconds=1))
            before = models.AuditTarget(run=pre, business_key='page', name='page', outcome='issues',
                findings_json=[{'rule_id': 'A', 'title': 'A', 'status': 'fail', 'observed': 'before'}])
            target = models.AuditTarget(run=post, business_key='page', name='page', outcome='issues',
                findings_json=[{'rule_id': 'A', 'title': 'A', 'status': 'fail', 'observed': 'after'},
                               {'rule_id': 'B', 'title': 'B', 'status': 'pass', 'method': 'dom', 'observed': ''}])
            user = models.User(username=uuid4().hex, password_hash='unused', role='operator')
            viewer = models.User(username=uuid4().hex, password_hash='unused', role='viewer')
            db.add_all([pre, post, before, target, user, viewer])
            db.flush()
            target.baseline_target_id = before.id
            db.commit()
            app = FastAPI()
            app.include_router(router.router, prefix='/api')
            app.dependency_overrides[get_db] = lambda: db
            with TestClient(app) as client:
                client.headers['Authorization'] = 'Bearer ' + create_access_token(user)
                yield SimpleNamespace(db=db, client=client, target=target, before=before, pre=pre, post=post,
                    version=version, viewer=viewer, project=project, user=user)
        transaction.rollback()


def review(ctx, verdict='false_positive', rule_id='A', **extra):
    return ctx.client.post(f'/api/audit-targets/{ctx.target.id}/reviews', json={
        'rule_id': rule_id, 'verdict': verdict, **extra})


@pytest.mark.parametrize('payload', [
    {'rule_id': 'A', 'verdict': 'bad'},
    {'rule_id': 'A', 'verdict': 'confirmed', 'corrected_status': 'uncertain'},
    {'rule_id': 'unknown', 'verdict': 'false_negative'},
    {'rule_id': 'unknown', 'verdict': 'confirmed'},
    {'rule_id': 'C', 'verdict': 'confirmed'},
])
def test_post_validation(context, payload):
    assert context.client.post(f'/api/audit-targets/{context.target.id}/reviews', json=payload).status_code == 422


def test_auth_missing_target_and_viewer(context):
    ctx = context
    url = f'/api/audit-targets/{uuid4()}/reviews'
    assert ctx.client.post(url, json={'rule_id': 'A', 'verdict': 'confirmed'}).status_code == 404
    assert ctx.client.get(url).status_code == 404
    ctx.client.headers['Authorization'] = 'Bearer ' + create_access_token(ctx.viewer)
    assert review(ctx).status_code == 403
    assert ctx.client.get(f'/api/audit-targets/{ctx.target.id}/reviews').status_code == 200
    assert ctx.client.get(f'/api/audit-specs/versions/{ctx.version.id}/quality').status_code == 200
    ctx.client.headers.clear()
    assert ctx.client.get(f'/api/audit-targets/{ctx.target.id}/reviews').status_code == 401


def test_append_only_latest_wins_and_missed_rules(context):
    ctx = context
    original = deepcopy(ctx.target.findings_json)
    first = review(ctx, note='误报记录').json()
    second = review(ctx, 'exception', note='接受例外').json()
    assert first['id'] != second['id'] and second['created_by'] == str(ctx.user.id)
    history = ctx.client.get(f'/api/audit-targets/{ctx.target.id}/reviews').json()
    assert [r['id'] for r in history] == [second['id'], first['id']]
    data = ctx.client.get(f'/api/audit-targets/{ctx.target.id}').json()
    assert data['findings_json'][0]['review']['id'] == second['id']
    assert data['findings_json'][0]['excepted'] is True
    assert data['findings_json'][0]['effective_status'] == 'pass'
    assert data['findings_json'][1]['review'] is None
    assert review(ctx, 'false_negative', 'B').status_code == 200
    assert review(ctx, 'false_negative', 'C').status_code == 200
    data = ctx.client.get(f'/api/audit-targets/{ctx.target.id}').json()
    assert {f['rule_id']: f['effective_status'] for f in data['findings_json']} == {'A': 'pass', 'B': 'fail', 'C': 'fail'}
    assert ctx.target.findings_json == original


def test_false_positive_updates_all_analytics_and_bulk_loading(context):
    ctx = context
    url = f'/api/audit-projects/{ctx.project.id}'
    response = ctx.client.get(url)
    assert response.status_code == 200, response.text
    assert response.json()['stages']['post']['count'] == 1
    assert review(ctx).status_code == 200
    cockpit = ctx.client.get(url).json()
    assert cockpit['stages']['closed']['count'] == 1
    assert cockpit['flow']['counts']['fixed'] == 1
    run = ctx.client.get(f'/api/audit-runs/{ctx.post.id}').json()
    assert run['pareto'][0]['fail'] == 0
    assert run['composition']['outcomes']['clean'] == 1
    matrix = ctx.client.get(f'{url}/matrix').json()
    assert matrix['pages'][0]['post'].startswith('P')
    assert matrix['pages'][0]['delta'].startswith('F')
    life = ctx.client.get(f'{url}/pages/page').json()
    assert life['stage'] == 'closed'
    assert life['timeline'][-1]['fail'] == 0 and life['timeline'][-1]['summary']['fail'] == 0
    # Expire the identity map: a many-target project still loads reviews in one query.
    for i in range(12):
        ctx.db.add(models.AuditTarget(run=ctx.post, name=str(i), outcome='clean', findings_json=[]))
    ctx.db.commit()
    ctx.db.expire_all()
    queries = []
    def record(conn, cursor, statement, parameters, execution_context, executemany):
        if statement.lstrip().upper().startswith('SELECT') and 'audit_finding_reviews' in statement:
            queries.append(statement)
    event.listen(engine, 'before_cursor_execute', record)
    try:
        assert ctx.client.get(url).status_code == 200
    finally:
        event.remove(engine, 'before_cursor_execute', record)
    assert len(queries) == 1


def test_quality_latest_counts_methods_and_sample_threshold(context):
    ctx = context
    review(ctx, 'confirmed')
    review(ctx, 'false_positive')  # latest wins: this must not also count as confirmed
    review(ctx, 'false_negative', 'B')
    review(ctx, 'recapture', 'B')
    for i, verdict in enumerate(['confirmed'] * 8 + ['exception']):
        target = models.AuditTarget(run=ctx.post, name=str(i), outcome='issues', findings_json=[
            {'rule_id': 'A', 'title': 'A', 'status': 'fail', 'evidence': {'method': 'pixel'}}])
        ctx.db.add(target); ctx.db.flush()
        ctx.db.add(models.AuditFindingReview(target_id=target.id, rule_id='A', verdict=verdict))
    ctx.db.add(models.AuditTarget(run=ctx.post, name='pending', outcome='needs_confirmation', findings_json=[
        {'rule_id': 'A', 'title': 'A', 'status': 'uncertain', 'method': 'dom'}]))
    ctx.db.commit()
    rows = {r['rule_id']: r for r in ctx.client.get(f'/api/audit-specs/versions/{ctx.version.id}/quality').json()['rules']}
    a = rows['A']
    assert (a['reviewed'], a['confirmed'], a['false_positive'], a['exception']) == (10, 8, 1, 1)
    assert a['insufficient'] is False
    assert a['fp_rate'] == pytest.approx(1 / 9)
    assert a['uncertain_rate'] == pytest.approx(1 / 12)
    assert a['by_method']['pixel']['reviewed'] == 9
    assert a['by_method']['model']['fp_rate'] == 1
    assert rows['B']['reviewed'] == 1 and rows['B']['recapture'] == 1
    assert rows['B']['fn_rate'] is None and rows['B']['insufficient'] is True
    assert rows['C']['reviewed'] == 0 and rows['C']['fp_rate'] is None
    review(ctx, 'false_negative', 'B')
    rows = {r['rule_id']: r for r in ctx.client.get(f'/api/audit-specs/versions/{ctx.version.id}/quality').json()['rules']}
    assert rows['B']['fn_rate'] == 1
    assert ctx.client.get(f'/api/audit-specs/versions/{uuid4()}/quality').status_code == 404


def test_export_frozen_assets_labels_dom_and_recapture(context, tmp_path):
    from PIL import Image
    from app.services.audit_evidence import store_asset
    ctx = context
    image = tmp_path / 'screen.png'
    Image.new('RGB', (20, 30), 'red').save(image)
    import hashlib
    data = image.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    store_asset(ctx.db, data, digest, ctx.post.id)
    source = tmp_path / 'capture'
    folder = source / 'venues' / 'old-record'
    folder.mkdir(parents=True)
    from scripts.export_gold_set import write_json
    write_json(folder / 'capture.json', {'venue': {'record_id': 'old-record', 'venue_name': 'page'}, 'screens': []})
    write_json(folder / 'dom-snapshot.json', {'viewport': [20, 30]})
    ctx.post.source_ref_json = {'source_dir': str(source)}
    ctx.target.findings_json = [{**f, 'evidence': {'items': [{'asset': digest, 'screen': 1, 'file': 'venues/old-record/screen.png'}]}} for f in ctx.target.findings_json]
    ctx.db.commit()
    review(ctx, 'exception')
    review(ctx, 'recapture', 'B')
    output = tmp_path / 'gold'
    manifest = export_run(ctx.db, ctx.post, output)
    assert len(manifest['targets']) == 1
    exported = manifest['targets'][0]
    assert exported['gold_labels'] == {'A': 'fail'}
    assert (output / exported['screenshots'][0]['file']).read_bytes() == data
    assert (output / exported['dom_snapshot']).is_file()
    assert (output / 'manifest.json').is_file()
    with pytest.raises(ValueError, match='empty'):
        export_run(ctx.db, ctx.post, output)


def test_review_is_append_only_and_target_delete_cascades(context):
    ctx = context
    result = review(ctx).json()
    with pytest.raises(ValueError, match='append-only'):
        with ctx.db.begin_nested():
            saved = ctx.db.get(models.AuditFindingReview, result['id'])
            saved.note = 'overwrite'
            ctx.db.flush()
    with pytest.raises(ValueError, match='append-only'):
        with ctx.db.begin_nested():
            ctx.db.delete(ctx.db.get(models.AuditFindingReview, result['id']))
            ctx.db.flush()
    ctx.db.expire_all()
    assert ctx.db.get(models.AuditFindingReview, result['id']).note is None
    ctx.db.delete(ctx.target)
    ctx.db.commit()
    ctx.db.expire_all()
    assert ctx.db.get(models.AuditFindingReview, result['id']) is None


def test_quality_ignores_capture_failed_placeholders():
    version = SimpleNamespace(id=uuid4(), rules_json=[{'rule_id': 'A', 'title': 'A'}])
    run = SimpleNamespace(spec_version=version)

    def target(outcome, status):
        return SimpleNamespace(outcome=outcome, run=run, reviews=[],
                               findings_json=[{'rule_id': 'A', 'title': 'A', 'status': status}])

    rows = analytics.rule_quality(version, [target('capture_failed', 'uncertain'), target('issues', 'uncertain'),
                                            target('clean', 'pass')])['rules']
    assert rows[0]['findings'] == 2
    assert rows[0]['uncertain_rate'] == 0.5
