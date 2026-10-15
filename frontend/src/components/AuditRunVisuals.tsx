import { Fragment, memo, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { AuditOutcome, AuditRunDetail, AuditStrip, AuditTargetBrief, AuditVersionDetail } from '../api';
import { captureLabels, outcomeLabels, outcomeOrder, StatusLegend, stripGradient } from './AuditWorkspaceUI';

function counts(s: string) {
  let fail = 0, uncertain = 0;
  for (const code of s) { if (code === 'F') fail++; else if (code === 'U') uncertain++; }
  return { fail, uncertain };
}
function groupStrips(strips: AuditStrip[]) {
  const rank = new Map(outcomeOrder.map((key, index) => [key, index]));
  return [...strips].sort((a, b) => (rank.get(a.outcome)! - rank.get(b.outcome)!));
}

export const AuditWaffle = memo(function AuditWaffle({ run, captures, selected }: { run: AuditRunDetail; captures: AuditTargetBrief[]; selected?: AuditOutcome }) {
  const targets = useMemo(() => {
    const rows = [...run.strips.map(strip => ({ ...strip, ...counts(strip.s), capture_reason: null })), ...captures];
    const rank = new Map(outcomeOrder.map((key, index) => [key, index]));
    return rows.sort((a, b) => rank.get(a.outcome)! - rank.get(b.outcome)! || b.fail - a.fail || b.uncertain - a.uncertain || a.name.localeCompare(b.name));
  }, [run.strips, captures]);
  return <section className="aw-panel" aria-labelledby="waffle-title"><h2 id="waffle-title">每格一个对象</h2><p>按结果分组、按不符合项数排序；颜色越深问题越多。悬停或聚焦查看，点击进入对象。</p>
    <div className="aw-waffle-grid" aria-label={`${targets.length} 个对象的结果分布`}>{targets.map(target => {
      const title = `${target.name} · ${outcomeLabels[target.outcome]} · ${target.fail} 项不符合 · ${target.uncertain} 项待确认${target.capture_reason ? ` · ${captureLabels[target.capture_reason]}` : ''}`;
      return <Link key={target.id} to={`/audit-targets/${target.id}`} title={title} aria-label={title} className={`aw-square aw-outcome-${target.outcome} aw-depth-${Math.min(target.fail, 3)} ${selected && selected !== target.outcome ? 'is-dim' : ''}`} />;
    })}</div>
    <div className="aw-legend"><span><i className="aw-key aw-depth-3" />3+ 项不符合</span><span><i className="aw-key aw-depth-2" />2 项</span><span><i className="aw-key aw-depth-1" />1 项</span><span><i className="aw-key aw-uncertain" />待确认</span><span><i className="aw-key aw-pass" />部分审核 / 全部符合</span><span><i className="aw-key aw-hatched" />采集失败</span></div>
  </section>;
});

export function AuditParetoChart({ run }: { run: AuditRunDetail }) {
  const max = Math.max(1, run.strips.length);
  return <section className="aw-panel" aria-labelledby="pareto-title"><h2 id="pareto-title">规则帕累托</h2><p>实色为不符合对象数，浅色为待确认；按不符合降序。</p>
    <div className="aw-pareto">{run.pareto.map(rule => <div className="aw-pareto-row" key={rule.rule_id}>
      <span className="aw-chart-label"><span className="aw-mono">{rule.rule_id}</span><span>{rule.title}</span></span><span className="aw-bar" role="img" aria-label={`${rule.title}：${rule.fail} 个不符合，${rule.uncertain} 个待确认`}><i className="aw-fail" style={{ width: `${rule.fail / max * 100}%` }} /><i className="aw-uncertain-soft" style={{ width: `${rule.uncertain / max * 100}%` }} /></span><span className="aw-numbers"><strong>{rule.fail}</strong><span> / {rule.uncertain}</span></span>
    </div>)}</div>
    <div className="aw-notes">{run.cooccurrence.shared_evidence.map(pair => <p key={pair.rules.join('/')}><strong>{pair.rules.join(' 与 ')}</strong> 同时出现 {pair.count} 次，{run.cooccurrence.note}，不重复计数。</p>)}{run.cooccurrence.pairs.map(pair => <p key={pair.rules.join('/')}><strong>{pair.rules.join(' 与 ')}</strong> 在 {pair.count} 个对象上共现，可结合规则一起处理。</p>)}{!run.cooccurrence.shared_evidence.length && !run.cooccurrence.pairs.length && <p>当前范围没有不符合规则共现。</p>}</div>
  </section>;
}

export const AuditBarcode = memo(function AuditBarcode({ run, version }: { run: AuditRunDetail; version: AuditVersionDetail }) {
  const { strips, rows, bands } = useMemo(() => {
    const strips = groupStrips(run.strips);
    const ruleMap = new Map(version.rules_json.map(rule => [rule.rule_id, rule]));
    const rows = run.rule_order.flatMap((id, index) => {
      const rule = ruleMap.get(id);
      if (!rule?.enabled) return [];
      const codes = strips.map(strip => strip.s[index] || '-').join('');
      return [{ ...rule, codes, fail: counts(codes).fail, uncertain: counts(codes).uncertain, background: stripGradient(codes) }];
    });
    const bands = outcomeOrder.flatMap(outcome => {
      const count = strips.filter(strip => strip.outcome === outcome).length;
      return count ? [{ outcome, count }] : [];
    });
    return { strips, rows, bands };
  }, [run.strips, run.rule_order, version.rules_json]);
  return <section className="aw-panel" aria-labelledby="barcode-title"><div className="aw-heading"><h2 id="barcode-title">规则 × 对象 热力条码</h2><span className="aw-muted">{strips.length} 个可审核对象 · {rows.length} 条启用规则</span></div><p>每根竖线是一个对象，每行是一条规则。竖向成片表示对象问题集中，横向成片表示规则普遍问题。</p>
    <StatusLegend />{!strips.length && <p className="aw-warning">当前范围没有可审核画面。</p>}
    <div className="aw-scroll" tabIndex={0} role="region" aria-label="规则与对象热力条码"><div className="aw-barcode-grid"><span /><div className="aw-bands">{bands.map(band => <span key={band.outcome} className={`aw-band aw-text-${band.outcome}`} style={{ flex: `${band.count} 1 0` }}>{outcomeLabels[band.outcome]} {band.count}</span>)}</div><span className="aw-muted aw-numbers">不符合</span>
      {rows.map(rule => <Fragment key={rule.rule_id}><span className="aw-chart-label" title={`${rule.rule_id} ${rule.title}${rule.duplicate_of ? `，与 ${rule.duplicate_of} 共享证据，不重复计数` : ''}`}><span className="aw-mono">{rule.rule_id}</span><span>{rule.title}{rule.duplicate_of ? ' · 共享证据' : ''}</span></span><span className="aw-barcode-strip" role="img" aria-label={`${rule.rule_id} ${rule.title}：${rule.fail} 个不符合，${rule.uncertain} 个待确认，共 ${strips.length} 个对象${rule.duplicate_of ? '；共享证据不重复计数' : ''}`} style={{ backgroundImage: rule.background }} /><strong className="aw-numbers">{rule.fail}</strong></Fragment>)}
    </div></div>
  </section>;
});

export function AuditTriage({ run, version, selected }: { run: AuditRunDetail; version: AuditVersionDetail; selected?: AuditOutcome }) {
  const rules = new Map(version.rules_json.map(rule => [rule.rule_id, rule]));
  const strips = new Map(run.strips.map(strip => [strip.id, strip.s]));
  const enabledIndices = run.rule_order.flatMap((id, i) => rules.get(id)?.enabled ? [i] : []);
  const { focus, batches, evidence_gaps: gaps, recapture } = run.triage;
  const singleTotal = batches.reduce((sum, batch) => sum + batch.count, 0);
  const batchMax = Math.max(1, ...batches.map(b => b.count));
  return <section aria-labelledby="triage-title"><div className="aw-heading"><h2 id="triage-title">处理顺序</h2><a href="#audit-details">查看对象明细 ↓</a></div>
    <div className="aw-triage-grid">
      <article className={`aw-triage aw-triage-focus ${selected && selected !== 'issues' ? 'is-subdued' : ''}`}><span className="aw-chip aw-outcome-issues">逐个整改 · {focus.length}</span><h3>问题集中的对象</h3><p>至少 3 项不符合，逐个核对。</p><div className="aw-triage-list">{focus.map(target => {
        const full = strips.get(target.id) || '';
        const mini = enabledIndices.map(i => full[i] || '-').join('');
        return <Link className="aw-focus-row" key={target.id} to={`/audit-targets/${target.id}`}><span>{target.name}</span><span className="aw-mini-strip" role="img" aria-label={`${target.fail} 项不符合，${target.uncertain} 项待确认`} style={{ backgroundImage: stripGradient(mini), maskImage: mini.length ? `repeating-linear-gradient(90deg,#000 0 calc(${100 / mini.length}% - 1px),transparent calc(${100 / mini.length}% - 1px) ${100 / mini.length}%)` : undefined }} /><strong>{target.fail}</strong></Link>;
      })}{!focus.length && <p>当前范围无集中问题对象。</p>}</div></article>
      <article className={`aw-triage ${selected && selected !== 'issues' ? 'is-subdued' : ''}`}><span className="aw-chip aw-batch-chip">按规则批量 · {singleTotal}</span><h3>只差一项的对象</h3><p>按规则聚合，适合批量处理。</p><div className="aw-triage-list">{batches.map(batch => <div className="aw-triage-rule" key={batch.rule_id}><span className="aw-mono">{batch.rule_id}</span><span>{rules.get(batch.rule_id)?.title || batch.rule_id}<span className="aw-batch-bar"><i style={{ width: `${batch.count / batchMax * 100}%` }} /></span></span><strong>{batch.count}</strong></div>)}{!batches.length && <p>当前范围无单项问题对象。</p>}</div></article>
      <article className={`aw-triage aw-triage-gaps ${selected && selected !== 'needs_confirmation' ? 'is-subdued' : ''}`}><span className="aw-chip aw-outcome-needs_confirmation">补证据 · {run.strips.filter(s => s.outcome === 'needs_confirmation').length}</span><h3>待确认集中规则</h3><p>无不符合但仍需补充证据的对象。</p><div className="aw-triage-list">{gaps.map(gap => <div className="aw-triage-rule" key={gap.rule_id}><span className="aw-mono">{gap.rule_id}</span><span>{rules.get(gap.rule_id)?.title || gap.rule_id}</span><strong>{gap.count}</strong></div>)}{!gaps.length && <p>当前范围无待补证据。</p>}</div><small className="aw-muted">待确认不计入不符合数。</small></article>
      <article className={`aw-triage ${selected && selected !== 'capture_failed' ? 'is-subdued' : ''}`}><span className="aw-chip aw-outcome-capture_failed">重新采集 · {recapture.total}</span><h3>采集失败原因</h3><p>这些不是设计问题，先处理可审核性。</p><div className="aw-offline"><span>活动已下线</span><strong>{recapture.offline}</strong></div><div className="aw-triage-list">{Object.entries(recapture.by_reason).map(([reason, count]) => <div className="aw-heading" key={reason}><span>{captureLabels[reason as keyof typeof captureLabels]}</span><strong>{count}</strong></div>)}</div><small className="aw-muted">已下线对象单列，其余对象按原因补采。</small></article>
    </div>
  </section>;
}
