"""Evaluate rerun findings against frozen human labels, optionally rerunning H5 captures."""
import argparse
import asyncio
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]
from scripts.export_gold_set import gold_label, write_json


def evaluate(manifest, results):
    predictions = {}
    for target in results.get('results', results.get('targets', [])):
        identity = str(target.get('target_id') or target.get('record_id') or target.get('venue', {}).get('record_id'))
        checks = (target.get('audit') or {}).get('checks', target.get('findings', target.get('findings_json', [])))
        for finding in checks:
            key = (identity, finding['rule_id'])
            if key in predictions:
                raise ValueError(f'Duplicate prediction: {key}')
            if finding['status'] not in {'pass', 'fail', 'uncertain', 'not_applicable', 'disabled'}:
                raise ValueError(f'Unknown result status: {finding["status"]}')
            predictions[key] = finding['status']
    buckets = defaultdict(Counter)
    for target in manifest['targets']:
        labels = dict(target.get('gold_labels', {}))
        # Also enforce exclusions on externally produced manifests.
        for review in target.get('latest_reviews', []):
            label = gold_label(review)
            if label is None:
                labels.pop(review['rule_id'], None)
            else:
                labels[review['rule_id']] = label
        identity = str(target.get('record_id') or target['target_id'])
        for rule, label in labels.items():
            if label not in {'pass', 'fail', 'not_applicable'}:
                raise ValueError(f'Invalid gold label: {label}')
            status = predictions.get((identity, rule))
            counts = buckets[rule]
            counts['samples'] += 1
            counts['uncertain'] += status == 'uncertain'
            counts['missing'] += status is None
            counts['tp'] += label == 'fail' and status == 'fail'
            counts['fp'] += label != 'fail' and status == 'fail'
            counts['fn'] += label == 'fail' and status != 'fail'
            counts['tn'] += label != 'fail' and status != 'fail'

    def metrics(counts):
        return {**{k: counts[k] for k in ('samples', 'tp', 'fp', 'fn', 'tn', 'uncertain', 'missing')},
                'precision': counts['tp'] / (counts['tp'] + counts['fp']) if counts['tp'] + counts['fp'] else None,
                'recall': counts['tp'] / (counts['tp'] + counts['fn']) if counts['tp'] + counts['fn'] else None,
                'uncertain_rate': counts['uncertain'] / counts['samples'] if counts['samples'] else None}
    total = Counter()
    for counts in buckets.values():
        total.update(counts)
    return {'rules': {rule: metrics(counts) for rule, counts in sorted(buckets.items())}, 'totals': metrics(total)}


def baseline_diff(current, baseline):
    def diff(now, previous):
        return {key: now[key] - previous[key] if now.get(key) is not None and previous.get(key) is not None else None
                for key in ('precision', 'recall', 'uncertain_rate')}
    return {'totals': diff(current['totals'], baseline['totals']),
            'rules': {rule: diff(row, baseline.get('rules', {}).get(rule, {})) for rule, row in current['rules'].items()}}


async def rerun_gold(gold, profile, output):
    from scripts import rerun_venue_audit as replay
    from scripts.audit_spec_profile import build_profile

    manifest = json.loads((gold / 'manifest.json').read_text())
    catalog = json.loads((gold / 'catalog.json').read_text())
    if {v['record_id'] for v in catalog['venues']} != {t['record_id'] for t in manifest['targets']}:
        raise ValueError('Gold catalog differs from manifest')
    for target in manifest['targets']:
        capture = json.loads((gold / target['capture_file']).read_text())
        if capture['screens'] != target['screenshots']:
            raise ValueError('Gold capture differs from manifest')
        for screen in capture['screens']:
            path = (gold / screen['file']).resolve()
            if not path.is_relative_to(gold) or hashlib.sha256(path.read_bytes()).hexdigest() != screen['sha256']:
                raise ValueError('Gold screenshot hash mismatch')
    if Path(profile).is_file():
        spec = json.loads(Path(profile).read_text())
    else:
        from app import models
        from app.database import SessionLocal
        with SessionLocal() as db:
            version = db.get(models.AuditSpecVersion, UUID(profile))
            if version is None:
                raise ValueError('Spec version not found')
            spec = build_profile(version.rules_json, version.source_json)
    profile_path = output.parent / f'{output.name}-profile.json'
    write_json(profile_path, spec)
    await replay.main(SimpleNamespace(source=str(gold), output=str(output), spec=str(profile_path), limit=None,
        records_file=None, fresh=True, normalize_only=False, concurrency=6, no_gate=False), frozen_gold=True)
    results = []
    for venue in catalog['venues']:
        path = output / 'venues' / venue['record_id'] / 'audit.json'
        if not path.is_file():
            raise ValueError(f'Gold rerun failed for {venue["record_id"]}; see audit-error.json')
        results.append({'venue': venue, 'audit': json.loads(path.read_text())})
    return {'results': results}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gold', required=True, type=Path)
    parser.add_argument('--results', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--rerun', action='store_true')
    parser.add_argument('--profile', help='Spec version UUID or H5 rule profile JSON')
    args = parser.parse_args(argv)
    if args.rerun and not args.profile:
        parser.error('--rerun requires --profile')
    if not args.rerun and not args.results:
        parser.error('--results is required unless --rerun is used')
    gold = args.gold.resolve()
    try:
        if args.rerun:
            args.results = args.results or gold.parent / f'{gold.name}-rerun' / 'results.json'
            output = args.results.resolve().parent
            if output == gold or output.is_relative_to(gold):
                raise ValueError('Rerun output must be outside the frozen gold directory')
            if output.exists() and any(output.iterdir()):
                raise ValueError('Rerun output must be empty; use a new directory for each evaluation')
            results = asyncio.run(rerun_gold(gold, args.profile, output))
            write_json(args.results, results)
        else:
            results = json.loads(args.results.read_text())
        report = evaluate(json.loads((gold / 'manifest.json').read_text()), results)
        if args.baseline:
            report['diff'] = baseline_diff(report, json.loads(args.baseline.read_text()))
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if args.out:
            write_json(args.out, report)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
