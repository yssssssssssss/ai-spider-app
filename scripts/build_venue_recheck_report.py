"""Build audit results and pixel evidence, comparing a frozen baseline when present."""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.venue_check_evidence import CheckEvidenceBuilder


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def csv_file(path, headings, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headings)
        for row in rows:
            values = [str(value) if value is not None else "" for value in row]
            writer.writerow(["'" + value if value.startswith(("=", "+", "-", "@")) else value for value in values])


def evidence_page(folder, audit, capture):
    colors = {"feeds_background": "#0077CC", "card_background": "#BE185D", "floor_gap": "#D97706", "card_gap": "#008500", "cart_margin": "#8B5CF6"}
    frames = []
    fact_marks = []
    if audit.get("report_type") == "official_venue_h5_user_policy_v2":
        for check in audit["checks"]:
            facts = check.get("facts", {})
            if check["rule_id"] not in {"OV-005", "OV-015", "OV-016", "OV-017", "OV-018"} or not facts or not any(facts.values()):
                continue
            for index, entry in enumerate(check["evidence"]):
                fact_marks.append({"id": f'{check["rule_id"]}-{index}', "screen": entry["screen"], "bbox_px": entry["bbox_px"],
                                   "label": check["title"], "observed": check["observed"]})
    for screen in capture["screens"]:
        marks = []
        for fact in fact_marks:
            if fact["screen"] == screen["number"]:
                x, y, right, bottom = fact["bbox_px"]
                marks.append(f'<rect data-key="{escape(fact["id"])}" x="{x}" y="{y}" width="{right-x}" height="{bottom-y}" '
                             'fill="none" stroke="#DC2626" stroke-width="1"/>')
        for item in audit["visual_measurements"]:
            if item["screen"] != screen["number"] or "bbox_px" not in item:
                continue
            color = colors[item["role"]]
            key = escape(item["id"], quote=True)
            boxes = [(item["bbox_px"], "none", "3 2")]
            boxes += [(band["bbox_px"], color, "") for band in item.get("result", {}).get("bands", [])]
            if "solid_sample" in item:
                boxes.extend((sample["bbox_px"], color, "") for sample in item.get("solid_samples", [item["solid_sample"]]))
            for (x, y, right, bottom), fill, dash in boxes:
                marks.append(f'<rect data-key="{key}" x="{x}" y="{y}" width="{right-x}" height="{bottom-y}" '
                             f'fill="{fill}" fill-opacity="0.18" stroke="{color}" stroke-width="1" stroke-dasharray="{dash}"/>')
        frames.append(f'<figure><figcaption>截图 {screen["number"]} · 滚动 {screen["scroll_y"]} px</figcaption>'
                      f'<svg viewBox="0 0 {screen["width"]} {screen["height"]}" role="img" aria-label="测量区域标注">'
                      f'<image href="{escape(Path(screen["file"]).name)}" width="{screen["width"]}" height="{screen["height"]}"/>{"".join(marks)}</svg></figure>')
    rows = []
    for fact in fact_marks:
        rows.append(f'<section><label><input type="checkbox" data-toggle="{escape(fact["id"])}" checked> '
                    f'{escape(fact["label"])} · 截图{fact["screen"]}</label><p>{escape(fact["observed"])}</p></section>')
    for item in audit["visual_measurements"]:
        result = item.get("result", {})
        value = (f'主色 {result["dominant_hex"]}，占比 {result["dominant_ratio"]:.1%}' if "dominant_hex" in result else
                 "条带 " + "/".join(str(b["length_px"]) for b in result.get("bands", [])) + " 截图像素" if "bands" in result else item["status"])
        rows.append(f'<section><label><input type="checkbox" data-toggle="{escape(item["id"], quote=True)}" checked> '
                    f'{escape(item["label"])} · 截图{item["screen"]}</label><p>{escape(value)}</p>'
                    f'<details><summary>坐标、取样和测量数据</summary><pre>{escape(json.dumps(item, ensure_ascii=False, indent=2))}</pre></details></section>')
    v = audit["venue"]
    html = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>像素测量证据</title>
<style>body{{font:14px/1.6 system-ui;margin:24px;color:#1e293b;background:#f3f5f8}}.frames{{display:flex;gap:18px;flex-wrap:wrap}}figure{{margin:0;width:390px;max-width:100%}}svg{{width:100%;height:auto}}section{{background:white;padding:12px;margin:12px 0;border-radius:8px}}pre{{white-space:pre-wrap;word-break:break-word}}</style>
<a href="../../report.html">返回总报告</a><h1>{escape(v["venue_name"])} · 像素测量证据</h1>
<p>会场ID：{escape(v["venue_id"])}　通天塔项目ID：{escape(v["project_id"])}</p>
<p>虚线框是模型定位的搜索区域；彩色实线框是纯色取样或背景色条带；红框是文字、商品或人物事实的定位证据，部分经过原图复核。条带不自动等同于精确组件间隔。勾选可切换标注。</p>
<div class="frames">{"".join(frames)}</div>{"".join(rows)}
<script>for(const input of document.querySelectorAll('[data-toggle]'))input.onchange=()=>{{for(const mark of document.querySelectorAll('[data-key]'))if(mark.dataset.key===input.dataset.toggle)mark.style.display=input.checked?'':'none';}};</script></html>'''
    (folder / "visual-evidence.html").write_text(html, encoding="utf-8")


def venue_status(audit):
    if audit is None:
        return "pending"
    if audit["page_state"] != "ready":
        return "page_error"
    if audit["mandatory_fail_count"]:
        return "visible_issues"
    if any(c["status"] == "uncertain" and c.get("enabled", True) for c in audit["checks"]):
        return "needs_confirmation"
    return "partial_inspection"


TEMPLATE = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>官方会场审核</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f3f5f8;color:#1e293b;font:14px/1.65 system-ui,sans-serif}
header,main{max-width:1280px;margin:auto;padding:24px}h1{font-size:26px;margin:0 0 6px}h3{font-size:15px;margin:16px 0 6px}p{margin:6px 0}.muted,small{color:#64748b}
.badge{display:inline-block;padding:4px 10px;border-radius:6px;background:#e2e8f0;margin:4px}
.badge.visible_issues{background:#fee2e2;color:#991b1b}.badge.partial_inspection{background:#dcfce7;color:#166534}.badge.needs_confirmation{background:#fef3c7;color:#92400e}
.controls{display:flex;gap:12px;flex-wrap:wrap;margin-top:16px}input[type=search],select{padding:10px;border:1px solid #cbd5e1;border-radius:8px;background:white}input[type=search]{flex:1;min-width:240px}
a{color:#245bc5}.card{padding:20px;background:white;border:1px solid #dde3ec;border-radius:12px;margin-bottom:20px}.card h2{font-size:18px;margin:0 0 6px}.ids{font-family:ui-monospace,monospace;font-size:12px;word-break:break-all}
.screens{display:flex;gap:16px;overflow:auto;margin:16px 0}.screens figure{margin:0;width:195px;min-width:195px}.screens img{width:100%;height:auto;border:1px solid #e2e8f0}.screens figcaption{font-size:12px}
.pass{color:#167445}.fail{color:#c32b29}.uncertain{color:#925d09}.not_applicable{color:#64748b}.check{padding:10px 0;border-top:1px solid #e5e7eb}.check strong,small{display:block}
details>summary{cursor:pointer;font-weight:600}button{padding:10px 22px;background:#245bc5;border:0;color:white;border-radius:7px;cursor:pointer}table{border-collapse:collapse;margin:16px 0;background:white}th,td{text-align:left;padding:8px 18px;border-bottom:1px solid #e2e8f0}.changed{background:#eef6ff;padding:4px 8px;border-radius:5px}
</style>
<link rel="stylesheet" href="check-evidence.css">
<header><h1 id="headline">官方会场审核</h1><p id="scope"></p><p class="muted" id="limits"></p>
<div id="summary"></div><div id="comparison"></div>
<details><summary>本轮规则及激活状态</summary><div id="rules"></div></details>
<div class="controls"><input id="search" type="search" placeholder="搜索会场名称、会场 ID、通天塔项目 ID">
<select id="filter"><option value="all">全部会场</option><option value="visible_issues">可见规范疑似问题</option><option value="has_uncertain">含待确认项的会场</option><option value="partial_inspection">未发现强制项问题</option><option value="page_error">截图未就绪</option><option value="pending">审核处理中</option></select>
<label><input id="changed-only" type="checkbox">仅显示结论变化的会场</label></div>
<p><a href="README.md">本轮结论与范围说明</a> · <a href="venues.csv">会场清单</a> · <a href="checks.csv">逐项结论</a><span id="comparison-link"> · <a href="comparison.csv">新旧结论对比</a></span> · <a href="measurements.csv">像素测量数据</a> · <a href="results.json">完整JSON</a><span id="source-pdf-link"> · <a href="specification/source.pdf">原规范PDF</a></span><span id="spacing-link"></span></p></header>
<main><p id="shown" class="muted"></p><div id="cards"></div><button id="more">显示更多</button></main>
<script id="report-data" type="application/json">__DATA__</script><script src="check-evidence.js"></script><script>
const data=JSON.parse(document.querySelector('#report-data').textContent);
const labels={visible_issues:'可见规范疑似问题',needs_confirmation:'待确认',partial_inspection:'未发现强制项问题',page_error:'截图未就绪',pending:'审核处理中'};
const checkLabels={pass:'通过（可见范围）',fail:'疑似问题',uncertain:'待确认',not_applicable:'不适用（可见范围）',disabled:'未激活（本轮忽略）'};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const activeChecks=a=>(a?.checks||[]).filter(c=>c.enabled!==false&&c.status!=='disabled');
const hasUncertain=r=>activeChecks(r.audit).some(c=>c.status==='uncertain');
const badge=(status,text)=>`<span class="badge ${status}">${esc(text)}</span>`;
document.title=data.title;
if(data.fresh){
 document.querySelector('#changed-only').closest('label').hidden=true;
 document.querySelector('#comparison-link').hidden=true;
}
if(data.has_source_pdf===false)document.querySelector('#source-pdf-link').hidden=true;
document.querySelector('#headline').textContent=data.title;
document.querySelector('#scope').textContent=`共 ${data.total_venues} 个会场，保留 ${data.rules.length} 项规则，本轮执行 ${data.rules.filter(r=>r.enabled).length} 项。结论针对本轮两屏可见范围。`;
document.querySelector('#limits').textContent=data.report_note;
document.querySelector('#rules').innerHTML='<table><thead><tr><th>规则</th><th>激活状态</th><th>本轮要求</th></tr></thead><tbody>'+data.rules.map(r=>`<tr><td>${esc(r.id)} ${esc(r.title)}</td><td>${r.enabled?'激活':'未激活'}</td><td>${esc(r.expected)}</td></tr>`).join('')+'</tbody></table>';
document.querySelector('#summary').innerHTML=badge('',`共 ${data.total_venues} 个会场`)+Object.entries(labels).map(([status,label])=>badge(status,`${label} ${data.status_counts[status]||0}`)).join('');
document.querySelector('#comparison').innerHTML=`<table><thead><tr><th>会场状态</th><th>会场数</th><th>占比</th></tr></thead><tbody>${Object.entries(labels).map(([status,label])=>{const count=data.status_counts[status]||0;return `<tr data-status="${status}"><td>${badge(status,label)}</td><td>${count}</td><td>${(100*count/data.total_venues).toFixed(0)}%</td></tr>`;}).join('')}<tr><th>合计</th><th>${data.total_venues}</th><th>100%</th></tr></tbody></table><p class="muted">每个会场只计一次：有强制项疑似问题优先归入疑似问题，其次归入待确认。</p>`;
if(data.has_spacing_review)document.querySelector('#spacing-link').innerHTML=' · <a href="spacing-report.html">分类Tab上方间距明细</a>';
let selected=data.results,limit=20;
function check(c,r){
 const pages=[...new Set(c.sources.map(s=>s.page))].sort((a,b)=>a-b).join('、');
 const changed=c.previous_status!=null&&c.previous_status!==c.status;
 const spacing=c.rule_id==='OV-009'&&c.facts?.dom_file?`<p><a href="${esc(c.facts.screenshot_file)}" target="_blank" rel="noopener">本轮间距截图</a> · <a href="${esc(c.facts.dom_file)}" target="_blank" rel="noopener">间距测量记录</a></p>`:'';
 return `<div class="check" data-rule-id="${esc(c.rule_id)}" data-status="${esc(c.status)}"><strong class="${c.status}">${esc(c.status==='fail'&&c.strength==='recommendation'?'建议优化':checkLabels[c.status])} · ${esc(c.rule_id)} ${esc(c.title)}</strong>${changed?`<span class="changed">原结论：${esc(checkLabels[c.previous_status])}</span>`:''}<p>${esc(c.observed)}</p><p>${esc(c.reason)}</p>${c.duplicate_of?`<small>与 ${esc(c.duplicate_of)} 共用证据，强制问题不重复计数。</small>`:''}<small>${c.rule_origin==='user_override'?'本轮用户口径；历史PDF依据：':'规范：'}第 ${pages} 页</small>${c.evidence.map(e=>`<a href="${esc(e.file)}" target="_blank" rel="noopener">截图 ${e.screen}，区域 [${e.bbox_px.join(', ')}]</a>`).join(' · ')}${spacing}${CheckEvidence.render(c,r.venue,r.check_evidence?.[c.rule_id])}${c.status==='fail'?`<p>建议：${esc(c.remediation)}</p>`:''}</div>`;
}
function card(r){
 const v=r.venue,c=r.capture,a=r.audit,checks=activeChecks(a),attention=checks.filter(c=>c.status==='fail'||c.status==='uncertain');
 return `<article class="card" data-venue-id="${esc(v.venue_id)}"><h2>${esc(v.venue_name)} ${badge(r.status,labels[r.status])}</h2><p class="ids">会场 ID：${esc(v.venue_id)}　通天塔项目 ID：${esc(v.project_id)}　来源第 ${v.source_page} 页第 ${v.source_row} 行</p><a href="${esc(v.preview_url)}" target="_blank" rel="noopener">原预览链接</a><div class="screens">${c.screens.map(s=>`<figure><a href="${esc(s.file)}" target="_blank" rel="noopener"><img loading="lazy" src="${esc(s.file)}" width="390" height="844" alt="${esc(v.venue_name)} 截图${s.number}"></a><figcaption>原截图 ${s.number} · 滚动 ${s.scroll_y}px</figcaption></figure>`).join('')}</div>${a?`${a.visual_measurements.length||a.structured_facts?`<p><a href="venues/${esc(v.record_id)}/visual-evidence.html" target="_blank" rel="noopener">查看测量与事实标注</a> · feeds背景：${esc({white:'白色',nonwhite:'非白色',mixed:'取样不一致',unknown:'待确认'}[a.measured_feeds_background])}</p>`:''}${attention.length?`<div class="attention"><h3>疑似问题与待确认</h3>${attention.map(c=>check(c,r)).join('')}</div>`:''}<details class="all-checks"><summary>全部激活检查（${checks.length}项）：通过 ${a.summary.pass||0}，疑似问题 ${a.summary.fail||0}，待确认 ${a.summary.uncertain||0}，不适用 ${a.summary.not_applicable||0}</summary>${checks.map(c=>check(c,r)).join('')}</details>`:'<p>审核处理中</p>'}</article>`;
}
function render(){
 document.querySelector('#cards').innerHTML=selected.slice(0,limit).map(card).join('')||'<p>没有匹配的会场</p>';
 document.querySelector('#shown').textContent=`匹配 ${selected.length} 条，已显示 ${Math.min(limit,selected.length)} 条。报告生成：${data.generated_at}`;
 document.querySelector('#more').hidden=limit>=selected.length;
}
function filter(){
 const q=document.querySelector('#search').value.trim().toLowerCase(),status=document.querySelector('#filter').value,changed=document.querySelector('#changed-only').checked;
 selected=data.results.filter(r=>(status==='all'||(status==='has_uncertain'?hasUncertain(r):r.status===status))&&(!changed||r.audit?.checks.some(c=>c.previous_status!=null&&c.previous_status!==c.status))&&[r.venue.venue_name,r.venue.venue_id,r.venue.project_id].some(x=>String(x||'').toLowerCase().includes(q)));
 limit=20;render();
}
document.querySelector('#search').addEventListener('input',filter);
document.querySelector('#filter').addEventListener('change',filter);
document.querySelector('#changed-only').addEventListener('change',filter);
document.querySelector('#more').onclick=()=>{limit+=20;render();};CheckEvidence.setup();render();
</script></html>'''


def build(root):
    catalog, baseline = read(root / "catalog.json"), read(root / "baseline.json")
    fresh = baseline.get("fresh", False)
    spec = read(root / "specification/walkthrough.json")
    run = read(root / "run.json") if (root / "run.json").exists() else {}
    original = {"results": []} if fresh else read(Path(baseline["source"]) / "results.json")
    old = {r["venue"]["record_id"]: r for r in original["results"]}
    evidence_builder = CheckEvidenceBuilder(root)
    results, changes, tool_rows = [], [], []
    new_counts, transitions, causes, background_counts = Counter(), Counter(), Counter(), Counter()
    measured_venues, pixel_resolved = 0, 0
    for venue in catalog["venues"]:
        folder = root / "venues" / venue["record_id"]
        capture = read(folder / "capture.json")
        audit = read(folder / "audit.json") if (folder / "audit.json").exists() else None
        status = venue_status(audit)
        results.append({"venue": venue, "capture": capture, "audit": audit, "status": status})
        if not audit:
            continue
        results[-1]["check_evidence"] = {c["rule_id"]: evidence_builder.prepare(c, capture, venue)
                                         for c in audit["checks"] if c.get("enabled", True)}
        previous_checks = {} if fresh else {c["rule_id"]: c for c in old[venue["record_id"]]["audit"]["checks"]}
        new_counts.update(c["status"] for c in audit["checks"])
        background_counts[audit["measured_feeds_background"]] += 1
        for check in audit["checks"]:
            if fresh:
                continue
            before = previous_checks[check["rule_id"]]
            if before["status"] != check["status"]:
                transition = before["status"] + "->" + check["status"]
                transitions[transition] += 1
                causes[check["change_source"]] += 1
                pixel_resolved += check["change_source"] == "pixel_verified_applicability" and before["status"] == "uncertain"
                changes.append({"venue": {k: venue[k] for k in ("venue_name", "venue_id", "project_id", "record_id")},
                                "rule_id": check["rule_id"], "previous_status": before["status"], "status": check["status"],
                                "previous_reason": before["reason"], "reason": check["reason"], "change_source": check["change_source"]})
        measured_venues += any(m["status"] == "measured" for m in audit["visual_measurements"])
        for m in audit["visual_measurements"]:
            result = m.get("result", {})
            tool_rows.append([venue["venue_name"], venue["venue_id"], venue["project_id"], m["id"], m["role"], m["screen"],
                              m["status"], json.dumps(m.get("bbox_px")), result.get("dominant_hex"), result.get("dominant_ratio"),
                              "/".join(str(b["length_px"]) for b in result.get("bands", [])),
                              m.get("edge_distance", {}).get("distance_px"),
                              json.dumps([b.get("length_comparison", {}) for b in result.get("bands", [])], ensure_ascii=False),
                              json.dumps(m.get("edge_length_comparison"), ensure_ascii=False), m["file"], m["sha256"]])
        if audit["visual_measurements"] or audit.get("structured_facts"):
            evidence_page(folder, audit, capture)
    counts = dict(Counter(r["status"] for r in results))
    comparison = {"baseline_venue_counts": baseline["venue_counts"], "new_venue_counts": counts,
                  "baseline_check_counts": baseline["check_counts"], "new_check_counts": dict(new_counts),
                  "transition_counts": dict(transitions), "change_source_counts": dict(causes), "pixel_resolved_uncertain": pixel_resolved,
                  "measured_venues": measured_venues, "measurement_requests": len(tool_rows), "background_counts": dict(background_counts), "changes": changes}
    packet = {"schema_version": 3, "generated_at": datetime.now(timezone.utc).isoformat(), "total_venues": len(results),
              "status_counts": counts, "source_sha256": read(root / "specification/walkthrough.json")["source"]["sha256"],
              "mode": "h5_user_policy_v2" if spec.get("audit_mode") == "h5_v2" else "frozen_capture_reaudit_with_pixel_tools",
              "title": spec["title"], "rule_version": spec["version"],
              "report_note": run.get("report_note", spec.get("report_note", "本轮复用原始两屏截图；会场尚有待确认项时不计为全部通过。")),
              "has_spacing_review": (root / "spacing-review.json").exists(),
              "rules": [{"id": r["id"], "title": r["title"], "expected": r["expected"], "enabled": r.get("enabled", True)} for r in spec["rules"]],
              "fresh": fresh, "has_source_pdf": (root / "specification/source.pdf").exists(),
              "comparison": None if fresh else comparison, "results": results}
    write(root / "results.json", packet)
    if not fresh:
        write(root / "comparison.json", comparison)
    data = json.dumps(packet, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    for source, target in (("venue_check_evidence.js", "check-evidence.js"), ("venue_check_evidence.css", "check-evidence.css")):
        (root / target).write_bytes(Path(__file__).with_name(source).read_bytes())
    (root / "report.html").write_text(TEMPLATE.replace("__DATA__", data), encoding="utf-8")
    csv_file(root / "venues.csv", ["会场名称", "会场ID", "通天塔项目ID", "来源页", "来源行", "审核状态", "强制项疑似问题数", "背景取样分类", "截图1", "截图2"],
             [[r["venue"]["venue_name"], r["venue"]["venue_id"], r["venue"]["project_id"], r["venue"]["source_page"], r["venue"]["source_row"], r["status"],
               r["audit"]["mandatory_fail_count"] if r["audit"] else None, r["audit"]["measured_feeds_background"] if r["audit"] else None,
               *[s["file"] for s in r["capture"]["screens"]]] for r in results])
    csv_file(root / "checks.csv", ["会场名称", "会场ID", "通天塔项目ID", "规则ID", "检查项", "激活状态", "共用规则", "原结论", "本轮结论", "观察及测量", "依据", "测量区域ID", "结论变化来源"],
             [[r["venue"]["venue_name"], r["venue"]["venue_id"], r["venue"]["project_id"], c["rule_id"], c["title"], c.get("enabled", True), c.get("duplicate_of"), c["previous_status"], c["status"], c["observed"], c["reason"],
               "/".join(c["measurement_ids"]), c["change_source"]] for r in results if r["audit"] for c in r["audit"]["checks"]])
    if not fresh:
        csv_file(root / "comparison.csv", ["会场名称", "会场ID", "通天塔项目ID", "规则ID", "原结论", "本轮结论", "原依据", "本轮依据", "变化来源"],
                 [[c["venue"]["venue_name"], c["venue"]["venue_id"], c["venue"]["project_id"], c["rule_id"], c["previous_status"], c["status"], c["previous_reason"], c["reason"], c["change_source"]] for c in changes])
    csv_file(root / "measurements.csv", ["会场名称", "会场ID", "通天塔项目ID", "区域ID", "测量对象", "截图序号", "测量状态", "区域坐标", "主色", "主色占比", "条带长度_截图像素", "模型边缘距离_截图像素", "条带换算与差值", "边缘换算与差值", "截图文件", "截图SHA256"], tool_rows)
    print(json.dumps({"stage": "report_built", "venues": len(results), "counts": counts, "pixel_resolved_uncertain": pixel_resolved, "measurements": len(tool_rows)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    build(Path(parser.parse_args().output).resolve())
