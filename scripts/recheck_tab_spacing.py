"""Apply a confirmed spacing range to saved, verified H5 measurements."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from html import escape
import json
import math
from pathlib import Path
import shutil
import sys
from urllib.parse import urlsplit
from PIL import Image

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
sys.path.insert(0, str(PROJECT / 'backend'))
from app.services.visual_measurement import compare_length_range
from scripts.build_venue_recheck_report import build, csv_file, read, write


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def classify_spacing(review, policy):
    if review['measurement_status'] == 'skipped':
        confirmed = review['venue']['venue_id'] in policy.get('user_confirmed_skip_venue_ids', [])
        confirmed |= policy.get('skip_when_gray_demo_floor', False) and review.get('skip_reason') == '灰色示意楼层'
        return 'not_applicable' if confirmed else 'uncertain'
    if review['measurement_status'] != 'measured' or not review.get('semantic_boundary_verified'):
        return 'uncertain'
    interval = policy['acceptable_range_px']
    result = compare_length_range(review['distance_css_px'], min_px=interval['min'], max_px=interval['max'])
    return 'pass' if result['status'] == 'within_range' else 'fail'


def verify_dom(root, review):
    if review['measurement_status'] != 'measured':
        return
    for file_key, hash_key in [('dom_file', 'dom_sha256'), ('screenshot_file', 'screenshot_sha256')]:
        assert sha(root / review[file_key]) == review[hash_key], 'Measurement evidence changed'
    dom = read(root / review['dom_file'])
    assert dom['venue'] == review['venue'], 'DOM venue identity changed'
    measurement = dom['measurement']
    expected_url, measured_url = urlsplit(review['venue']['preview_url']), urlsplit(measurement['source']['url_without_query'])
    assert (expected_url.scheme, expected_url.netloc, expected_url.path) == (measured_url.scheme, measured_url.netloc, measured_url.path), 'Measurement reached another venue'
    assert measurement['source']['viewport_css_px'] == {'width': 390, 'height': 844}
    assert measurement['source']['visual_viewport']['scale'] == 1
    with Image.open(root / review['screenshot_file']) as image:
        assert image.size == (390, 844), 'Screenshot scale changed'
    distance, = measurement['distances']
    assert distance['status'] == 'measured' and distance['distance_css_px'] == review['distance_css_px']
    targets = {e['id']: e for e in measurement['elements']}
    assert all(e['status'] == 'measured' for e in targets.values())
    gap = targets['category-tabs']['rect_css_px']['top'] - targets['upper-module']['rect_css_px']['bottom']
    assert math.isclose(gap, review['distance_css_px'])


def spacing_report(root, reviews, interval):
    labels = {'pass': '符合', 'fail': '不符合', 'not_applicable': '跳过', 'uncertain': '待确认'}
    rows, cards = [], []
    for review in reviews:
        venue, status = review['venue'], review['audit_status']
        measured = review['measurement_status'] == 'measured'
        gap = f'{review["distance_css_px"]:g}px' if measured else '—'
        position = review['upper_module'] + ' → 分类Tab' if measured else review['skip_reason']
        rows.append(f'<tr data-venue-id="{venue["venue_id"]}" data-status="{status}"><td>{escape(venue["venue_name"])}</td><td>{venue["venue_id"]}<br>通天塔：{venue["project_id"]}</td><td>{escape(position)}</td><td>{gap}</td><td><span class="badge {status}">{labels[status]}</span></td><td><a href="#{venue["venue_id"]}">证据</a></td></tr>')
        if measured:
            bottom, top = review['upper_bottom_css_px'], review['tab_top_css_px']
            marks = f'<rect x="0" y="{min(bottom,top)}" width="390" height="{abs(top-bottom)}" fill="#f59e0b" fill-opacity="0.25"/><line x1="0" x2="390" y1="{bottom}" y2="{bottom}" stroke="#2563eb"/><line x1="0" x2="390" y1="{top}" y2="{top}" stroke="#059669"/>'
            detail = f'模块底部 {bottom:.4f} → Tab顶部 {top:.4f}。<a href="{review["dom_file"]}">原始测量记录</a>'
            if status == 'uncertain':
                detail += '；' + escape(review.get('skip_reason', '组件语义边界未确认。'))
        else:
            x, y, right, bottom = review['evidence_bbox_px']
            marks = f'<rect x="{x}" y="{y}" width="{right-x}" height="{bottom-y}" fill="none" stroke="#d97706"/>'
            detail = escape(review['skip_reason'])
        cards.append(f'<section id="{venue["venue_id"]}"><h2>{escape(venue["venue_name"])} · {gap} · {labels[status]}</h2><p>{detail}</p><svg viewBox="0 0 390 844" role="img" aria-label="间距证据"><image href="{review["screenshot_file"]}" width="390" height="844"/>{marks}</svg></section>')
    html = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>分类Tab上方间距复核</title><style>body{font:15px/1.65 system-ui;margin:24px;background:#f3f5f8;color:#1e293b}main{max-width:1280px;margin:auto}table{border-collapse:collapse;background:white;width:100%}th,td{padding:10px;text-align:left;border-bottom:1px solid #e2e8f0}.table-wrap{overflow:auto}.badge{padding:4px 8px;border-radius:6px}.pass{background:#dcfce7;color:#166534}.fail{background:#fee2e2;color:#991b1b}.not_applicable{background:#e2e8f0}a{color:#245bc5}.evidence{display:flex;flex-wrap:wrap;gap:20px}section{width:390px;padding:16px;background:white;border-radius:10px;overflow-wrap:anywhere}h2{font-size:18px}svg{width:100%;height:auto}</style><main><h1>分类Tab上方间距复核</h1>'''
    html += f'<p>标准：{interval["min"]}–{interval["max"]}px，包含边界值。测量上方可见模块底部至分类Tab容器顶部，不含Tab内部留白。</p><p>采用已保存的实时H5布局测量；CSS视口和导出截图同为390×844，像素按1:1对应。本版直接判定实际间距，不做812高度换算。</p><p><a href="report.html">全部检查报告</a> · <a href="spacing.csv">间距CSV</a> · <a href="spacing-review.json">完整记录</a></p><div class="table-wrap"><table id="spacing-table"><thead><tr><th>会场</th><th>对应ID</th><th>测量位置/跳过原因</th><th>间距</th><th>结论</th><th>证据</th></tr></thead><tbody>'
    html += ''.join(rows) + '</tbody></table></div><div class="evidence">' + ''.join(cards) + '</div></main></html>'
    (root / 'spacing-report.html').write_text(html, encoding='utf-8')


def recheck(source, output, spec_path):
    if source == output or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError('Output must be separate from the source report')
    spec, packet, review_packet = read(spec_path), read(source / 'results.json'), read(source / 'spacing-review.json')
    interval = spec['spacing']['acceptable_range_px']
    compare_length_range(0, min_px=interval['min'], max_px=interval['max'])
    reviews = review_packet['results']
    assert {r['venue']['venue_id'] for r in reviews} == {r['venue']['venue_id'] for r in packet['results']}
    source_hash = sha(source / 'results.json')
    for review in reviews:
        verify_dom(source, review)
    shutil.copytree(source, output, dirs_exist_ok=True)
    for name in ['manifest.sha256', 'validation.json', 'browser-validation.json', 'spacing-validation.json']:
        (output / name).unlink(missing_ok=True)
    shutil.copyfile(spec_path, output / 'specification/walkthrough.json')
    shutil.copyfile(spec_path.with_suffix('.md'), output / 'specification/user-policy.md')
    policy, interval = spec['spacing'], spec['spacing']['acceptable_range_px']
    rule = next(r for r in spec['rules'] if r['id'] == 'OV-009')
    old = {r['venue']['venue_id']: r['audit'] for r in packet['results']}
    timestamp = datetime.now(timezone.utc).isoformat()
    for review in reviews:
        venue = review['venue']
        audit_file = output / 'venues' / venue['record_id'] / 'audit.json'
        audit = read(audit_file)
        check = next(c for c in audit['checks'] if c['rule_id'] == 'OV-009')
        review['previous_check'] = json.loads(json.dumps(check))
        review['previous_length_comparison'] = review.pop('length_comparison', None)
        for key in ['equivalent_812_px', 'expected_image_px', 'difference_image_px']:
            review.pop(key, None)
        status = classify_spacing(review, policy)
        review['audit_status'] = status
        if review['measurement_status'] == 'measured':
            gap = review['distance_css_px']
            review['range_comparison'] = compare_length_range(gap, min_px=interval['min'], max_px=interval['max'])
            observed = f'{review["upper_module"]}底部→分类Tab顶部：{gap:g}px；标准{interval["min"]}–{interval["max"]}px（含边界）。'
            reason = '实际间距在标准范围内，符合要求。' if status == 'pass' else '实际间距不在标准范围内，不符合要求。' if status == 'fail' else '尚未确认真实组件边界，不能判定。'
        else:
            observed = f'本会场跳过OV-009：{review["skip_reason"]}。'
            reason = '按用户确认的条件跳过，不计为通过。'
        check.update(status=status, title=rule['title'], expected=rule['expected'], remediation=rule['remediation'],
                     previous_status=review['previous_check']['status'], observed=observed, reason=reason,
                     change_source='user_confirmed_spacing_range', facts={k:v for k,v in review.items() if k not in ['venue','previous_check']})
        audit['summary'] = dict(Counter(c['status'] for c in audit['checks']))
        audit['mandatory_fail_count'] = sum(c['status'] == 'fail' and c['strength'] in ['mandatory','conditional_mandatory'] and not c.get('duplicate_of') for c in audit['checks'])
        audit['overall'] = 'visible_issues_found' if audit['mandatory_fail_count'] else 'partial_inspection'
        audit['specification'].update(version=spec['version'], title=spec['title'], profile_sha256=sha(spec_path))
        audit['spacing_review'] = {k:v for k,v in review.items() if k != 'previous_check'}
        audit['audited_at'] = timestamp
        audit['limits'] = 'OV-009按已确认的7–9px范围复判，其他22项沿用第4版；没有新增模型调用或页面采集。'
        assert [c for c in audit['checks'] if c['rule_id'] != 'OV-009'] == [c for c in old[venue['venue_id']]['checks'] if c['rule_id'] != 'OV-009']
        write(audit_file, audit)
    review_packet.update(rule_version=spec['version'], reviewed_at=timestamp, previous_output=str(source),
                         previous_results_sha256=source_hash, acceptable_range_px=interval,
                         audit_status_counts=dict(Counter(r['audit_status'] for r in reviews)))
    review_packet.pop('expected_image_px', None)
    write(output / 'spacing-review.json', review_packet)
    csv_file(output / 'spacing.csv', ['会场名称','会场ID','通天塔项目ID','间距_CSS像素','标准下限','标准上限','结论','跳过原因','DOM记录','截图'],
             [[r['venue']['venue_name'],r['venue']['venue_id'],r['venue']['project_id'],r.get('distance_css_px'),interval['min'],interval['max'],r['audit_status'],r.get('skip_reason'),r.get('dom_file'),r['screenshot_file']] for r in reviews])
    run = read(output / 'run.json')
    run.update(status='processing', mode='confirmed_OV009_range_review', rule_version=spec['version'], rule_profile_sha256=sha(spec_path), started_at=timestamp, unit_policy='user_confirmed_h5_pixel_range', new_model_calls=0)
    write(output / 'run.json', run)
    build(output)
    spacing_report(output, reviews, interval)
    (output / 'README.md').write_text('# 10个会场：7–9px间距标准与报告更新\n\nOV-009按当前H5实际间距7–9px（含边界）判定，3个通过、4个不符合、3个跳过。使用上一轮保存的DOM与截图，其他22项完全一致，无新模型调用或页面采集。旧版本报告保持原样。\n\n顶部按会场统计，每个会场只计一次；疑似问题优先，其次待确认。浅红为疑似问题，浅绿为未发现强制项问题。默认展开疑似问题和待确认项，会场明细只显示激活项，隐藏概述和警告段落。全部23项仍保存在JSON和CSV中。\n\n[审核报告](report.html) · [间距明细](spacing-report.html) · [间距CSV](spacing.csv)\n', encoding='utf-8')
    assert sha(source / 'results.json') == source_hash, 'Source report changed'
    print(json.dumps({'output':str(output), 'spacing_status_counts':review_packet['audit_status_counts'], 'new_model_calls':0},ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--spec', required=True)
    args = parser.parse_args()
    recheck(Path(args.source).resolve(), Path(args.output).resolve(), Path(args.spec).resolve())
