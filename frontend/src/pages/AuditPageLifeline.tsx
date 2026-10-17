import { FormEvent, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { AuditComparisonRule, AuditPageLifeline as Lifeline, AuditFinding, AuditProjectDetail, AuditStatus, AuditTarget, AuditVersionDetail, getAuditPageLifeline, getAuditProject, getAuditSpecVersion, getAuditTarget, updateAuditTargetBaseline } from '../api';
import { useAuth } from '../auth';
import { auditTime, captureLabels, DemoBadge, LoadState, OutcomeBadge, statusLabels } from '../components/AuditWorkspaceUI';
import { CategoryBadge, categoryColors, ProjectViews, StageBadge, statusGlyphs } from '../components/AuditProjectUI';
import AuditEvidence from '../components/AuditEvidence';

const nextSteps = {
  regressed: '对照基线排查发布变更，修复后重新检查此规则。',
  still_open: '按规范预期处理仍未修复的问题，并补充整改后的检查记录。',
  new_issue: '核对此次新增检查面，按当前规范处理并复查。',
  needs_confirmation: '补充可判定的观察或测量证据，再确认是否需要整改。',
  fixed: '本次比对已修复，后续检查继续关注该规则。',
  kept: '本次比对保持符合，后续检查继续验证。',
  not_comparable: '核对两次检查的规范范围、启用状态和载体适用性。',
};
const groups = [
  { key: 'need_action', title: '需要处理', hint: '回归、未修与新增', className: 'aw-text-issues' },
  { key: 'needs_confirmation', title: '待确认', hint: '缺证据，先补证再判定', className: 'aw-warning' },
  { key: 'closed', title: '已闭环', hint: '已修复或保持符合', className: 'aw-text-clean' },
] as const;

function TrackDot({ status }: { status: AuditStatus | null }) {
  return <span className={`ap-track-dot ap-track-${status || 'uncovered'}`} title={status ? statusLabels[status] : '未覆盖'}>{status ? statusGlyphs[status] : '·'}</span>;
}
function RuleTrack({ rule, selected, onSelect }: { rule: AuditComparisonRule; selected: boolean; onSelect: () => void }) {
  const label = `上线前${rule.pre_status ? statusLabels[rule.pre_status] : '未覆盖'}，上线后${rule.post_status ? statusLabels[rule.post_status] : '未覆盖'}`;
  return <button type="button" className="ap-rule-track" aria-pressed={selected} onClick={onSelect}><span className="ap-track-rule"><span className="aw-mono">{rule.rule_id}</span><strong>{rule.title}</strong></span><span className="ap-dot-track" role="img" aria-label={label}><i style={{ background: categoryColors[rule.category] }} /><TrackDot status={rule.pre_status} /><TrackDot status={rule.post_status} /></span><CategoryBadge category={rule.category} /></button>;
}

type TimelineItem = Lifeline['timeline'][number];
const auditedAt = (item: TimelineItem) => item.audited_at || item.date;
// Comparison and baseline changes retain the backend's import-time semantics.
const latestImportedPost = (timeline: TimelineItem[]) => [...timeline].filter(item => item.phase === 'post')
  .sort((a, b) => a.date.localeCompare(b.date) || a.run_id.localeCompare(b.run_id) || a.id.localeCompare(b.id)).pop();
const findingStatus = (finding: AuditFinding) => finding.effective_status || finding.status;
const statusRank = (status?: AuditStatus | null) => status === 'fail' ? 0 : status === 'uncertain' ? 1 : 2;

function findingsFor(target: AuditTarget, version: AuditVersionDetail, carrier: TimelineItem['carrier']) {
  if (target.outcome === 'capture_failed') return [];
  const rules = new Map(version.rules_json.map(rule => [rule.rule_id, rule]));
  return target.findings_json.filter(finding => {
    const rule = rules.get(finding.rule_id);
    return !rule || (rule.enabled && rule.carriers.includes(carrier) && !rule.duplicate_of);
  });
}

function LifelineEvidence({ pre, post, ruleId, onReload }: { pre?: AuditTarget; post?: AuditTarget; ruleId: string; onReload: () => void }) {
  return <div className="aw-evidence-comparison">{([pre, post] as const).map((target, index) => {
    if (!target) return null;
    const finding = target.findings_json.find(item => item.rule_id === ruleId);
    return <section className="aw-evidence-side" key={`${index}-${target.id}`}><h3>{index === 0 ? '上线前' : '上线后'}</h3>{finding ? <AuditEvidence key={ruleId} finding={finding} runId={target.run_id} onReload={onReload} /> : <p className="aw-muted">本次结果未覆盖该规则。</p>}</section>;
  })}</div>;
}

function AuditHistory({ lifeline, onReload }: { lifeline: Lifeline; onReload: () => void }) {
  const timeline = lifeline.timeline;
  const [selectedId, setSelectedId] = useState(timeline[timeline.length - 1]?.id || '');
  const selected = timeline.find(item => item.id === selectedId) || timeline[timeline.length - 1];
  const [targets, setTargets] = useState<Record<string, AuditTarget>>({});
  const [versions, setVersions] = useState<Record<string, AuditVersionDetail>>({});
  const [errors, setErrors] = useState<Set<string>>(new Set());
  const [retry, setRetry] = useState(0);
  const timelineScroll = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const scroll = timelineScroll.current;
    const card = scroll?.querySelector<HTMLElement>('[aria-pressed="true"]');
    if (scroll && card && scroll.scrollWidth > scroll.clientWidth) {
      // Limit scrolling to the timeline, including when it is below the fold.
      const options = { inline: 'nearest', block: 'nearest', container: 'nearest' } as const;
      card.scrollIntoView(options);
    }
  }, [selectedId]);
  const targetCache = useRef(new Map<string, Promise<AuditTarget>>());
  const versionCache = useRef(new Map<string, Promise<AuditVersionDetail>>());
  useEffect(() => {
    let active = true;
    setErrors(new Set());
    const failed = (key: string) => { if (active) setErrors(previous => new Set([...previous, key])); };
    for (const item of timeline) {
      let request = targetCache.current.get(item.id);
      if (!request) {
        request = getAuditTarget(item.id).then(({ data }) => data);
        targetCache.current.set(item.id, request);
      }
      request.then(target => { if (active) setTargets(previous => ({ ...previous, [item.id]: target })); })
        .catch(() => { targetCache.current.delete(item.id); failed(item.id); });
    }
    for (const id of new Set(timeline.map(item => item.spec_version_id))) {
      let request = versionCache.current.get(id);
      if (!request) {
        request = getAuditSpecVersion(id).then(({ data }) => data);
        versionCache.current.set(id, request);
      }
      request.then(version => { if (active) setVersions(previous => ({ ...previous, [id]: version })); })
        .catch(() => { versionCache.current.delete(id); failed(id); });
    }
    return () => { active = false; };
  }, [timeline, retry]);
  const target = selected && targets[selected.id];
  const version = selected && versions[selected.spec_version_id];
  const selectedFindings = target && version ? findingsFor(target, version, selected.carrier) : [];
  const issues = selectedFindings.filter(finding => statusRank(findingStatus(finding)) < 2)
    .sort((a, b) => statusRank(findingStatus(a)) - statusRank(findingStatus(b)) || a.rule_id.localeCompare(b.rule_id));
  const allLoaded = timeline.every(item => targets[item.id] && versions[item.spec_version_id]);
  const rows = new Map<string, { id: string; title: string; statuses: Map<string, AuditStatus> }>();
  if (allLoaded) for (const item of timeline) {
    for (const finding of findingsFor(targets[item.id], versions[item.spec_version_id], item.carrier)) {
      let row = rows.get(finding.rule_id);
      if (!row) {
        row = { id: finding.rule_id, title: finding.title || finding.rule_id, statuses: new Map() };
        rows.set(row.id, row);
      }
      row.title = versions[item.spec_version_id].rules_json.find(rule => rule.rule_id === row.id)?.title || finding.title || row.title;
      row.statuses.set(item.id, findingStatus(finding));
    }
  }
  const latestId = timeline[timeline.length - 1]?.id;
  const problemRows = [...rows.values()].filter(row => [...row.statuses.values()].some(status => statusRank(status) < 2))
    .sort((a, b) => statusRank(a.statuses.get(latestId)) - statusRank(b.statuses.get(latestId)) || a.id.localeCompare(b.id));
  const firstPost = timeline.findIndex(item => item.phase === 'post');
  const launch = <li className="ap-audit-launch" key="launch"><span className="ap-audit-band" aria-hidden="true">阶段分界</span><span className="ap-audit-axis" aria-hidden="true"><i>◆</i></span><strong>上线</strong></li>;
  return <>
    <section className="aw-panel ap-history" aria-labelledby="timeline-title"><div className="aw-heading"><h2 id="timeline-title">这个页面的审核轨迹</h2><span className="aw-muted">按审核时间排序 · 点击查看问题</span></div>
      <div ref={timelineScroll} className="aw-scroll ap-history-scroll" tabIndex={0} role="region" aria-label="审核时间线，可横向滚动"><ol className="ap-history-axis">{timeline.flatMap((item, index) => {
        const card = <li className={`ap-audit-step aw-${item.phase}`} key={`audit-${item.id}`}>
          <span className={`ap-audit-band ap-band-${item.phase}`}>{index === 0 || timeline[index - 1].phase !== item.phase ? item.phase === 'pre' ? '上线前' : '上线后' : <span className="aw-sr-only">{item.phase === 'pre' ? '上线前' : '上线后'}</span>}</span>
          <span className="ap-audit-axis" aria-hidden="true"><i /></span>
          <button type="button" className="ap-audit-card" aria-pressed={selected?.id === item.id} onClick={() => setSelectedId(item.id)}>
            <span className="ap-audit-date"><small>审核时间</small><time dateTime={auditedAt(item)}>{auditTime(auditedAt(item))}</time></span>
            <strong>{item.run_name}</strong><span className="aw-muted">规范 {item.spec_label}</span>
            <span className="aw-chips"><span className={`aw-chip aw-${item.phase}`}>{item.phase === 'pre' ? '上线前' : '上线后'} · {item.carrier === 'h5' ? 'H5' : 'App'}</span>{item.demo && <DemoBadge source={{ demo: true }} />}</span>
            <OutcomeBadge outcome={item.outcome} /><span className="ap-audit-counts">不符合 <b>{item.fail}</b> · 待确认 <b>{item.uncertain}</b></span>
          </button>
          <Link className="ap-audit-detail-link" to={`/audit-targets/${item.id}`}>在审核中查看 →</Link>
        </li>;
        return index === firstPost ? [launch, card] : [card];
      })}{firstPost < 0 && <>{launch}<li className="ap-audit-empty"><span className="ap-audit-band" aria-hidden="true" /><span className="ap-audit-axis" aria-hidden="true" /><p className="aw-muted">暂无上线后巡检</p></li></>}</ol></div>
    </section>
    <section className="aw-panel ap-audit-findings" aria-labelledby="findings-title"><div className="aw-heading"><div><h2 id="findings-title">本次审核发现的问题</h2>{selected && <p className="aw-muted">{selected.run_name} · {auditTime(auditedAt(selected))}</p>}</div>{selected && <Link to={`/audit-targets/${selected.id}`}>在审核中查看 →</Link>}</div>
      {!selected ? <p className="aw-muted">暂无审核记录。</p> : !target || !version ? <LoadState loading={!errors.has(selected.id) && !errors.has(selected.spec_version_id)} error={errors.has(selected.id) || errors.has(selected.spec_version_id)} retry={() => setRetry(value => value + 1)} /> : target.outcome === 'capture_failed' ? <div className="ap-capture-failed"><h3>采集失败 · {target.capture_reason ? captureLabels[target.capture_reason] : '未提供原因'}</h3><p className="aw-muted">未形成有效审核结论，需重新采集后审核。</p>{target.summary_json.capture_detail && <details><summary>查看采集原因原文</summary><pre>{JSON.stringify(target.summary_json.capture_detail, null, 2)}</pre></details>}</div> : <>
        <div className="ap-finding-list">{issues.map(finding => <article className="ap-history-finding" key={`${target.id}-${finding.rule_id}`}>
          <div className="aw-heading"><h3><span className="aw-mono">{finding.rule_id}</span> {version.rules_json.find(rule => rule.rule_id === finding.rule_id)?.title || finding.title}</h3><span className={`aw-status aw-status-${findingStatus(finding)}`}>{statusLabels[findingStatus(finding)]}</span></div>
          <div className="aw-observations"><div><h4>观察</h4><p>{finding.observed || '暂无观察记录'}</p></div><div><h4>判定原因</h4><p>{finding.reason || '暂无原因记录'}</p></div></div>
          {finding.evidence?.items?.length ? <AuditEvidence finding={finding} runId={target.run_id} onReload={onReload} /> : <p className="aw-muted">无截图证据</p>}
        </article>)}</div>
        {!issues.length && <p className="aw-muted">本次审核无不符合或待确认的问题。</p>}
        <p className="aw-muted ap-passed-summary">符合 {selectedFindings.filter(finding => findingStatus(finding) === 'pass').length} · 不适用 {selectedFindings.filter(finding => findingStatus(finding) === 'not_applicable').length}</p>
      </>}
    </section>
    <section className="aw-panel ap-rule-history" aria-labelledby="rule-history-title"><div className="aw-heading"><h2 id="rule-history-title">规则在各次审核中的变化</h2><span className="aw-muted">× 不符合 · ? 待确认 · ✓ 符合 · – 未覆盖 / 不适用</span></div>
      {!allLoaded ? <LoadState loading={!errors.size} error={!!errors.size} retry={() => setRetry(value => value + 1)} /> : problemRows.length ? <div className="aw-scroll ap-rule-history-scroll" tabIndex={0} role="region" aria-label="规则与审核变化表，可横向滚动"><table className="ap-history-grid"><caption className="aw-sr-only">曾出现不符合或待确认的规则，点击单元格查看对应审核</caption><thead><tr><th scope="col">规则</th>{timeline.map((item, index) => <th key={item.id} scope="col" title={`${item.run_name} · ${auditTime(auditedAt(item))}`}>{auditTime(auditedAt(item)).split(' ')[0].replace(/^\d{4}\//, '')}<small>第 {index + 1} 次</small></th>)}</tr></thead><tbody>{problemRows.map(row => <tr key={row.id}><th scope="row"><span className="aw-mono">{row.id}</span><strong>{row.title}</strong></th>{timeline.map(item => {
        const status = row.statuses.get(item.id);
        const glyph = status === 'fail' ? '×' : status === 'uncertain' ? '?' : status === 'pass' ? '✓' : '–';
        return <td key={item.id}><button type="button" className={`ap-history-cell ap-cell-${status || 'absent'}`} aria-pressed={selected?.id === item.id} aria-label={`${row.id} ${row.title}，${item.run_name}，审核时间 ${auditTime(auditedAt(item))}，${status ? statusLabels[status] : item.outcome === 'capture_failed' ? '采集失败，无审核结论' : '未覆盖'}`} onClick={() => setSelectedId(item.id)}>{glyph}</button></td>;
      })}</tr>)}</tbody></table></div> : <p className="aw-muted">各次审核尚无不符合或待确认的规则。</p>}
    </section>
    {lifeline.comparison && <ComparisonTracks lifeline={lifeline} targets={targets} onReload={onReload} />}
  </>;
}

function ComparisonTracks({ lifeline, targets, onReload }: { lifeline: Lifeline; targets: Record<string, AuditTarget>; onReload: () => void }) {
  const [selectedId, setSelectedId] = useState('');
  const orderedRules = [...lifeline.groups.need_action, ...lifeline.groups.needs_confirmation, ...lifeline.groups.closed, ...(lifeline.comparison?.rules.filter(rule => rule.category === 'not_comparable') || [])];
  const selected = orderedRules.find(rule => rule.rule_id === selectedId) || orderedRules[0];
  const latestPost = latestImportedPost(lifeline.timeline);
  const baseline = lifeline.timeline.find(item => item.id === latestPost?.baseline_target_id);
  const uncompared = lifeline.comparison?.rules.filter(rule => rule.category === 'not_comparable') || [];
  return <div className="ap-lifeline-layout"><section className="ap-rule-tracks" aria-labelledby="tracks-title"><div className="aw-heading"><h2 id="tracks-title">上线前后规则比对</h2><span className="aw-muted">左：上线前 · 右：上线后</span></div>{groups.map(group => <section key={group.key} className="ap-track-group"><div className="aw-heading"><h3 className={group.className}>{group.title} · {lifeline.groups[group.key].length}</h3><span className="aw-muted">{group.hint}</span></div>{lifeline.groups[group.key].map(rule => <RuleTrack key={rule.rule_id} rule={rule} selected={selected?.rule_id === rule.rule_id} onSelect={() => setSelectedId(rule.rule_id)} />)}{!lifeline.groups[group.key].length && <p className="aw-muted ap-track-empty">暂无此类比对记录。</p>}</section>)}{uncompared.length > 0 && <details className="ap-uncompared"><summary>另有 {uncompared.length} 条规则无法比对</summary>{uncompared.map(rule => <RuleTrack key={rule.rule_id} rule={rule} selected={selected?.rule_id === rule.rule_id} onSelect={() => setSelectedId(rule.rule_id)} />)}</details>}</section>
    {selected && <aside className="aw-panel ap-rule-panel" aria-labelledby="observed-title"><CategoryBadge category={selected.category} /><h2 id="observed-title"><span className="aw-mono">{selected.rule_id}</span> {selected.title}</h2><div className="ap-observed"><h3 className="ap-pre-text">上线前观察 · {selected.pre_status ? statusLabels[selected.pre_status] : '未覆盖'}</h3>{baseline && <p className="aw-muted">{baseline.run_name} · {auditTime(auditedAt(baseline))}</p>}<p>{selected.pre_observed || '暂无观察文本'}</p></div><div className="ap-observed"><h3 className="ap-post-text">上线后观察 · {selected.post_status ? statusLabels[selected.post_status] : '未覆盖'}</h3>{latestPost && <p className="aw-muted">{latestPost.run_name} · {auditTime(auditedAt(latestPost))}</p>}<p>{selected.post_observed || '暂无观察文本'}</p></div><LifelineEvidence pre={baseline ? targets[baseline.id] : undefined} post={latestPost ? targets[latestPost.id] : undefined} ruleId={selected.rule_id} onReload={onReload} /><div className="ap-insight"><h3>建议下一步</h3><p>{nextSteps[selected.category]}</p></div></aside>}
  </div>;
}

function BaselineControl({ lifeline, onChange }: { lifeline: Lifeline; onChange: () => void }) {
  const latestPost = latestImportedPost(lifeline.timeline);
  const preTargets = lifeline.timeline.filter(target => target.phase === 'pre' && target.business_key && target.business_key === latestPost?.business_key);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [selected, setSelected] = useState(latestPost?.baseline_target_id || '');
  if (!latestPost) return null;
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!latestPost) return;
    setBusy(true); setError(false);
    try { await updateAuditTargetBaseline(latestPost.id, selected || null); onChange(); }
    catch { setError(true); }
    finally { setBusy(false); }
  }
  return <section className="aw-panel ap-baseline" aria-labelledby="baseline-title"><h2 id="baseline-title">上线前基线</h2><p>为最新上线后巡检「{latestPost.run_name}」选择此页面的上线前记录。</p><form className="aw-form" onSubmit={save}><label>基线记录<select value={selected} onChange={event => setSelected(event.target.value)} disabled={busy}><option value="">不关联基线（独立检查）</option>{preTargets.map(target => <option key={target.id} value={target.id}>{auditTime(auditedAt(target))} · {target.run_name} · {target.spec_label}</option>)}</select></label><div className="aw-actions"><button disabled={busy || selected === (latestPost.baseline_target_id || '')}>{busy ? '保存中…' : selected ? '保存基线' : '清除基线'}</button><span className="aw-muted">{preTargets.length} 条可选上线前记录</span></div>{error && <p role="alert">基线保存失败，请重试。</p>}</form></section>;
}

export default function AuditPageLifeline() {
  const { id = '', pageKey = '' } = useParams();
  const { hasRole } = useAuth();
  const [data, setData] = useState<{ project: AuditProjectDetail; lifeline: Lifeline } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(false); setData(null);
    Promise.all([getAuditProject(id), getAuditPageLifeline(id, pageKey)]).then(([{ data: project }, { data: lifeline }]) => { if (active) setData({ project, lifeline }); }).catch(() => { if (active) setError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id, pageKey, reload]);
  const lifeline = data?.lifeline;
  const latest = lifeline?.timeline[lifeline.timeline.length - 1];
  const latestPost = lifeline && latestImportedPost(lifeline.timeline);
  const refresh = () => setReload(value => value + 1);
  return <div className="aw ap-lifeline"><div className="aw-heading"><nav className="aw-breadcrumb" aria-label="面包屑"><Link to="/audit-projects">项目走查</Link><span>/</span><Link to={`/audit-projects/${id}`}>{data?.project.name || '项目'}</Link><span>/</span><span>{lifeline?.name || '页面生命线'}</span></nav><ProjectViews id={id} view="lifeline" /></div>
    {loading || !data ? <LoadState loading={loading} error={error} retry={refresh} /> : <>
      <header className="ap-project-header"><div className="aw-chips"><StageBadge stage={data.lifeline.stage} /><span className={`aw-chip ${latestPost?.baseline_target_id ? 'ap-category-fixed' : ''}`}>{latestPost ? latestPost.baseline_target_id ? '已关联上线前基线' : '独立检查 · 未关联基线' : '暂无上线后巡检'}</span>{data.lifeline.timeline.some(target => target.demo) && <DemoBadge source={{ demo: true }} />}</div><h1>{data.lifeline.name}</h1><p className="aw-mono">{data.lifeline.id.startsWith('t:') ? '无业务键 · ' : '业务键 · '}{data.lifeline.id}</p>
        <section className="aw-kpi-band ap-lifeline-kpis" aria-label="页面审核关键指标"><div className="aw-kpi"><span>审核次数</span><strong>{data.lifeline.timeline.length}</strong></div><div className="aw-kpi"><span>当前不符合</span><strong className="aw-kpi-fail">{latest?.outcome === 'capture_failed' ? '–' : latest?.fail ?? 0}</strong></div><div className="aw-kpi"><span>当前待确认</span><strong className="aw-warning">{latest?.outcome === 'capture_failed' ? '–' : latest?.uncertain ?? 0}</strong></div><div className="aw-kpi ap-time-kpi"><span>最近审核时间</span><time dateTime={latest && auditedAt(latest)}>{latest ? auditTime(auditedAt(latest)) : '暂无审核'}</time></div></section>
      </header>
      <AuditHistory key={`history-${id}-${pageKey}`} lifeline={data.lifeline} onReload={refresh} />
      {hasRole('operator') && latestPost && <BaselineControl key={`baseline-${latestPost.id}-${latestPost.baseline_target_id || ''}`} lifeline={data.lifeline} onChange={refresh} />}
      {!data.lifeline.comparison && <p className="aw-muted">尚无已关联基线的上线后巡检，暂无上线前后比对。</p>}
      {data.lifeline.comparison?.spec_mismatch && <p className="aw-warning">两侧规范版本不同；变化类别已由接口按启用状态与载体适用性计算。</p>}
    </>}
  </div>;
}
