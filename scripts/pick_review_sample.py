"""Pick a deterministic mix of failures, uncertainty and clean controls per spec."""
import argparse
from collections import defaultdict
from pathlib import Path
import sys
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def select_sample(targets, n=20, controls=3):
    if n < 1 or controls < 0 or controls > n:
        raise ValueError('n must be positive and controls must be between 0 and n')
    groups = defaultdict(list)
    for target in targets:
        detail = target.summary_json.get('capture_detail') or {}
        if target.outcome == 'capture_failed' or target.capture_reason or detail.get('page_state') == 'error':
            continue
        findings = target.findings_json
        if not findings:
            continue
        counts = {s: sum(f['status'] == s for f in findings) for s in ('fail', 'uncertain')}
        groups[str(target.run.spec_version_id)].append((target, counts))
    result = []
    for spec, rows in sorted(groups.items()):
        order = lambda row: (-row[1]['fail'], -row[1]['uncertain'], str(row[0].id))
        failed = sorted((r for r in rows if r[1]['fail']), key=order)
        uncertain = sorted((r for r in rows if r[1]['uncertain']), key=lambda r: (-r[1]['uncertain'], *order(r)))
        clean = sorted((r for r in rows if not r[1]['fail'] and not r[1]['uncertain']), key=order)[:controls]
        chosen, seen = [], set()
        # Alternate the two priority categories so uncertainty is not crowded out.
        for i in range(max(len(failed), len(uncertain))):
            for category, pool in (('has_fail', failed), ('most_uncertain', uncertain)):
                if i < len(pool) and pool[i][0].id not in seen and len(chosen) < n - len(clean):
                    row = pool[i]
                    seen.add(row[0].id)
                    chosen.append((category, row[0], row[1]))
        result.extend((spec, category, target, counts) for category, target, counts in chosen)
        result.extend((spec, 'all_pass_control', target, counts) for target, counts in clean)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, type=UUID)
    parser.add_argument('--n', type=int, default=20)
    parser.add_argument('--controls', type=int, default=3)
    args = parser.parse_args(argv)
    from app.database import SessionLocal
    from app.services.audit_workspace import load_run
    try:
        with SessionLocal() as db:
            run = load_run(db, args.run)
            if run is None:
                raise ValueError('Audit run not found')
            rows = select_sample(run.targets, args.n, args.controls)
            print('spec\tcategory\tfail\tuncertain\tname\turl')
            for spec, category, target, counts in rows:
                print(f'{spec}\t{category}\t{counts["fail"]}\t{counts["uncertain"]}\t{target.name}\thttp://localhost:6273/audit-targets/{target.id}')
    except ValueError as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
