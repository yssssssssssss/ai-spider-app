"""Attach verified live Tab measurements to a completed two-screen H5 audit."""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from scripts.build_venue_recheck_report import build, csv_file, read, write
from scripts.recheck_tab_spacing import classify_spacing, spacing_report, verify_dom
from backend.app.services.visual_measurement import compare_length_range


def apply(root):
    catalog = read(root / 'catalog.json')
    spec = read(root / 'specification/walkthrough.json')
    policy = spec['spacing']
    interval = policy['acceptable_range_px']
    skipped_file = root / 'spacing-skip-overrides.json'
    skipped = {r['record_id']: r for r in read(skipped_file)['reviews']} if skipped_file.exists() else {}
    for venue in catalog['venues']:
        folder = root / 'venues' / venue['record_id']
        if not (folder / 'audit.json').exists() or (folder / 'audit-error.json').exists():
            raise ValueError('Finish all visual audits before attaching spacing reviews')
        review_file = root / 'spacing' / f'{venue["venue_id"]}-review.json'
        if review_file.exists():
            review = read(review_file)
            assert review['venue'] == venue
            verify_dom(root, review)
    reviews = []
    for venue in catalog['venues']:
        folder = root / 'venues' / venue['record_id']
        audit = read(folder / 'audit.json')
        capture = read(folder / 'capture.json')
        screen = capture['screens'][0]
        check = next(c for c in audit['checks'] if c['rule_id'] == 'OV-009')
        other_checks = deepcopy([c for c in audit['checks'] if c['rule_id'] != 'OV-009'])
        base = {'venue': venue, 'rule_id': 'OV-009', 'measurement_status': 'uncertain',
                'semantic_boundary_verified': False, 'screenshot_file': screen['file'],
                'screenshot_sha256': screen['sha256'], 'evidence_bbox_px': [0, 0, 390, 844]}
        if audit['page_state'] != 'ready':
            review = {**base, 'skip_reason': '原始两屏未展示正常会场；不能进行间距验收。'}
        elif venue['venue_id'] in policy.get('user_confirmed_skip_venue_ids', []):
            review = {**base, 'measurement_status': 'skipped', 'skip_reason': '用户确认的会场例外'}
        elif venue['record_id'] in skipped:
            override = skipped[venue['record_id']]
            assert override['venue_id'] == venue['venue_id']
            assert override['screen_sha256'] == {str(i + 1): s['sha256'] for i, s in enumerate(capture['screens'])}
            assert override['reason'] == '灰色示意楼层' and override['visual_verified'] is True
            review = {**base, 'measurement_status': 'skipped', 'skip_reason': override['reason'], 'skip_review': override}
        else:
            file = root / 'spacing' / f'{venue["venue_id"]}-review.json'
            review = read(file) if file.exists() else {**base, 'skip_reason': '未取得实际H5布局测量证据。'}
            assert review['venue'] == venue
            verify_dom(root, review)
        status = classify_spacing(review, policy)
        review['audit_status'] = status
        measured = review['measurement_status'] == 'measured'
        if measured:
            gap = review['distance_css_px']
            review['range_comparison'] = compare_length_range(gap, min_px=interval['min'], max_px=interval['max'])
            observed = f'实时H5：{review["upper_module"]}底部→分类Tab顶部，{gap:g}px；标准7–9px（含边界）。'
            reason = ('实际间距在标准范围内。' if status == 'pass' else '实际间距超出标准范围。') if status != 'uncertain' else review['skip_reason']
        else:
            observed = ('跳过本项：' if status == 'not_applicable' else '尚不能完成本项：') + review['skip_reason']
            reason = '按用户已确认的条件跳过，不计为通过。' if status == 'not_applicable' else review['skip_reason']
        evidence = [{'screen': 1, 'file': screen['file'], 'sha256': screen['sha256'],
                     'image_size': [390, 844], 'bbox_px': [0, 0, 390, 844]}]
        check.update(status=status, observed=observed, reason=reason, evidence=evidence,
                     method='live_h5_dom_spacing' if measured else 'h5_spacing_applicability',
                     change_source='verified_h5_tab_spacing', measurement_ids=[],
                     facts={k: v for k, v in review.items() if k != 'venue'})
        audit['spacing_review'] = check['facts']
        audit['summary'] = dict(Counter(c['status'] for c in audit['checks']))
        audit['mandatory_fail_count'] = sum(c['status'] == 'fail' and c['strength'] in {'mandatory', 'conditional_mandatory'} and not c.get('duplicate_of') for c in audit['checks'])
        audit['overall'] = 'visible_issues_found' if audit['mandatory_fail_count'] else 'partial_inspection'
        assert other_checks == [c for c in audit['checks'] if c['rule_id'] != 'OV-009']
        write(folder / 'audit.json', audit)
        reviews.append(review)
    packet = {'schema_version': 1, 'rule_id': 'OV-009', 'rule_version': spec['version'],
              'reviewed_at': datetime.now(timezone.utc).isoformat(), 'scope': policy['scope'],
              'acceptable_range_px': interval, 'results': reviews,
              'audit_status_counts': dict(Counter(r['audit_status'] for r in reviews)),
              'measurement_counts': dict(Counter(r['measurement_status'] for r in reviews))}
    write(root / 'spacing-review.json', packet)
    csv_file(root / 'spacing.csv', ['会场名称', '会场ID', '通天塔项目ID', '间距_CSS像素', '标准下限', '标准上限', '结论', '跳过或待确认原因', 'DOM记录', '截图'],
             [[r['venue']['venue_name'], r['venue']['venue_id'], r['venue']['project_id'], r.get('distance_css_px'), interval['min'], interval['max'], r['audit_status'], r.get('skip_reason') if r['audit_status'] in {'uncertain', 'not_applicable'} else '', r.get('dom_file'), r['screenshot_file']] for r in reviews])
    run = read(root / 'run.json')
    run.update(mode='full_h5_v5_reaudit_with_live_tab_spacing',
               report_note='全部会场按第5版规则重新审核：主体证据为每个会场已保存的两屏；OV-009另附实时H5截图与DOM测量，按7–9px判定。会场有待确认项时不计为全部通过。',
               live_spacing_status_counts=packet['audit_status_counts'],
               live_spacing_measurement_counts=packet['measurement_counts'])
    write(root / 'run.json', run)
    build(root)
    spacing_report(root, reviews, interval)
    print(packet['audit_status_counts'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    apply(Path(args.output).resolve())
