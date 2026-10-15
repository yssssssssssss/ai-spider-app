import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from scripts.eval_audit_rules import baseline_diff, evaluate, main
from scripts.export_gold_set import gold_label
from scripts.pick_review_sample import select_sample


def test_eval_precision_recall_uncertain_recapture_and_baseline(tmp_path, capsys):
    manifest = {'targets': [
        {'target_id': 'one', 'gold_labels': {'A': 'fail', 'B': 'pass', 'C': 'fail', 'skip': 'fail'},
         'latest_reviews': [{'rule_id': 'skip', 'verdict': 'recapture'}]},
        {'target_id': 'two', 'gold_labels': {'A': 'pass', 'B': 'fail', 'C': 'fail'}},
        {'target_id': 'three', 'gold_labels': {'A': 'fail', 'B': 'not_applicable'}},
    ]}
    results = {'results': [
        {'venue': {'record_id': 'one'}, 'audit': {'checks': [
            {'rule_id': 'A', 'status': 'fail'}, {'rule_id': 'B', 'status': 'fail'},
            {'rule_id': 'C', 'status': 'uncertain'}, {'rule_id': 'skip', 'status': 'fail'}]}},
        {'venue': {'record_id': 'two'}, 'audit': {'checks': [
            {'rule_id': 'A', 'status': 'fail'}, {'rule_id': 'B', 'status': 'pass'}, {'rule_id': 'C', 'status': 'fail'}]}},
        {'venue': {'record_id': 'three'}, 'audit': {'checks': [
            {'rule_id': 'A', 'status': 'pass'}, {'rule_id': 'B', 'status': 'not_applicable'}]}},
    ]}
    report = evaluate(manifest, results)
    assert report['rules']['A']['precision'] == .5
    assert report['rules']['A']['recall'] == .5
    assert report['rules']['C']['precision'] == 1
    assert report['rules']['C']['recall'] == .5
    assert report['rules']['C']['uncertain_rate'] == .5
    assert report['totals']['samples'] == 8
    assert report['totals']['precision'] == .5
    assert report['totals']['recall'] == .4
    assert 'skip' not in report['rules']
    baseline = json.loads(json.dumps(report))
    baseline['rules']['A']['precision'] = .25
    baseline['totals']['recall'] = .2
    diff = baseline_diff(report, baseline)
    assert diff['rules']['A']['precision'] == .25
    assert diff['totals']['recall'] == pytest.approx(.2)
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    results_path = tmp_path / 'results.json'; results_path.write_text(json.dumps(results))
    baseline_path = tmp_path / 'baseline.json'; baseline_path.write_text(json.dumps(baseline))
    output = tmp_path / 'eval.json'
    main(['--gold', str(tmp_path), '--results', str(results_path), '--baseline', str(baseline_path), '--out', str(output)])
    assert json.loads(output.read_text())['diff'] == diff
    assert 'diff' in capsys.readouterr().out


@pytest.mark.parametrize('verdict,corrected,expected', [
    ('confirmed', None, 'fail'), ('false_negative', 'pass', 'fail'), ('exception', None, 'fail'),
    ('false_positive', None, 'pass'), ('false_positive', 'not_applicable', 'not_applicable'),
    ('recapture', None, None),
])
def test_gold_labels(verdict, corrected, expected):
    assert gold_label({'verdict': verdict, 'corrected_status': corrected}) == expected


def test_eval_missing_and_duplicate_predictions():
    manifest = {'targets': [{'target_id': 'one', 'gold_labels': {'A': 'fail'}}]}
    report = evaluate(manifest, {'results': []})
    assert report['totals']['missing'] == 1 and report['totals']['recall'] == 0
    assert report['totals']['precision'] is None
    with pytest.raises(ValueError, match='Duplicate'):
        evaluate(manifest, {'targets': [{'target_id': 'one', 'findings': [{'rule_id': 'A', 'status': 'fail'}] * 2}]})


def sample_target(statuses, *, spec='v1', outcome='clean', reason=None, page_state=None):
    return SimpleNamespace(id=uuid4(), run=SimpleNamespace(spec_version_id=spec), name='page',
        findings_json=[{'rule_id': str(i), 'status': status} for i, status in enumerate(statuses)],
        outcome=outcome, capture_reason=reason, summary_json={'capture_detail': {'page_state': page_state}})


def test_pick_categories_controls_gates_and_per_spec():
    failures = [sample_target(['fail'] * 3) for _ in range(8)]
    uncertain = sample_target(['uncertain'] * 6)
    controls = [sample_target(['pass'] * 4) for _ in range(5)]
    blocked = [sample_target(['fail'], outcome='capture_failed'), sample_target(['fail'], reason='login_required'),
               sample_target(['fail'], page_state='error'), sample_target([])]
    another = sample_target(['fail'], spec='v2')
    selected = select_sample([*failures, uncertain, *controls, *blocked, another], n=6, controls=3)
    v1 = [row for row in selected if row[0] == 'v1']
    assert len(v1) == 6
    assert [row[1] for row in v1].count('all_pass_control') == 3
    assert {row[1] for row in v1} == {'has_fail', 'most_uncertain', 'all_pass_control'}
    assert v1[1][2] == uncertain
    assert not {t.id for t in blocked} & {r[2].id for r in selected}
    assert [r[2] for r in selected if r[0] == 'v2'] == [another]
    assert select_sample([*failures, uncertain, *controls], 6, 3) == select_sample([*controls, uncertain, *failures], 6, 3)
    assert len(select_sample(failures, 20, 3)) == 8
    with pytest.raises(ValueError):
        select_sample(failures, 2, 3)


def test_rerun_reuses_existing_runner_and_checks_frozen_hashes(tmp_path, monkeypatch):
    import asyncio
    import hashlib
    from scripts import rerun_venue_audit as replay
    from scripts.eval_audit_rules import rerun_gold
    from scripts.export_gold_set import write_json
    gold, output = tmp_path / 'gold', tmp_path / 'rerun'
    screen = {'number': 1, 'file': 'venues/one/screen.png', 'sha256': hashlib.sha256(b'frozen').hexdigest(),
              'width': 10, 'height': 20, 'scroll_y': 0}
    venue = {'record_id': 'one', 'venue_name': 'one'}
    write_json(gold / 'venues/one/capture.json', {'venue': venue, 'screens': [screen]})
    (gold / screen['file']).write_bytes(b'frozen')
    write_json(gold / 'catalog.json', {'venues': [venue]})
    write_json(gold / 'manifest.json', {'targets': [{'record_id': 'one', 'capture_file': 'venues/one/capture.json', 'screenshots': [screen]}]})
    profile = tmp_path / 'profile.json'; write_json(profile, {'audit_mode': 'h5_v2'})
    called = []
    async def existing_runner(args, *, frozen_gold=False):
        called.append((args, frozen_gold))
        write_json(Path(args.output) / 'venues/one/audit.json', {'checks': [{'rule_id': 'A', 'status': 'fail'}]})
    from pathlib import Path
    monkeypatch.setattr(replay, 'main', existing_runner)
    result = asyncio.run(rerun_gold(gold.resolve(), str(profile), output))
    assert called[0][1] is True and called[0][0].fresh is True
    assert result['results'][0]['audit']['checks'][0]['status'] == 'fail'
    (gold / screen['file']).write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash mismatch'):
        asyncio.run(rerun_gold(gold.resolve(), str(profile), output))
