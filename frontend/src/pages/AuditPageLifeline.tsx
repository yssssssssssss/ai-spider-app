import { FormEvent, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { AuditComparisonRule, AuditPageLifeline as Lifeline, AuditProjectDetail, AuditStatus, AuditTarget, getAuditPageLifeline, getAuditProject, getAuditTarget, updateAuditTargetBaseline } from '../api';
import { useAuth } from '../auth';
import { auditTime, DemoBadge, LoadState, OutcomeBadge, statusLabels } from '../components/AuditWorkspaceUI';
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

function LifelineEvidence({ preId, postId, ruleId, onReload }: { preId?: string; postId?: string; ruleId: string; onReload: () => void }) {
  const [targets, setTargets] = useState<(AuditTarget | null)[] | null>(null);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let active = true;
    setTargets(null); setError(false);
    Promise.all([preId, postId].map(targetId => targetId ? getAuditTarget(targetId).then(({ data }) => data) : Promise.resolve(null)))
      .then(data => { if (active) setTargets(data); }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [preId, postId, retry]);
  if (!preId && !postId) return null;
  if (!targets) return <LoadState loading={!error} error={error} retry={() => setRetry(value => value + 1)} />;
  return <div className="aw-evidence-comparison">{targets.map((target, index) => {
    if (!target) return null;
    const finding = target.findings_json.find(item => item.rule_id === ruleId);
    return <section className="aw-evidence-side" key={target.id}><h3>{index === 0 ? '上线前' : '上线后'}</h3>{finding ? <AuditEvidence key={ruleId} finding={finding} runId={target.run_id} onReload={onReload} /> : <p className="aw-muted">本次结果未覆盖该规则。</p>}</section>;
  })}</div>;
}

function BaselineControl({ lifeline, onChange }: { lifeline: Lifeline; onChange: () => void }) {
  const latestPost = [...lifeline.timeline].reverse().find(target => target.phase === 'post');
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
  return <section className="aw-panel ap-baseline" aria-labelledby="baseline-title"><h2 id="baseline-title">上线前基线</h2><p>为最新上线后巡检「{latestPost.run_name}」选择此页面的上线前记录。</p><form className="aw-form" onSubmit={save}><label>基线记录<select value={selected} onChange={event => setSelected(event.target.value)} disabled={busy}><option value="">不关联基线（独立检查）</option>{preTargets.map(target => <option key={target.id} value={target.id}>{auditTime(target.date)} · {target.run_name} · {target.spec_label}</option>)}</select></label><div className="aw-actions"><button disabled={busy || selected === (latestPost.baseline_target_id || '')}>{busy ? '保存中…' : selected ? '保存基线' : '清除基线'}</button><span className="aw-muted">{preTargets.length} 条可选上线前记录</span></div>{error && <p role="alert">基线保存失败，请重试。</p>}</form></section>;
}

export default function AuditPageLifeline() {
  const { id = '', pageKey = '' } = useParams();
  const { hasRole } = useAuth();
  const [data, setData] = useState<{ project: AuditProjectDetail; lifeline: Lifeline } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);
  const [selectedId, setSelectedId] = useState('');
  useEffect(() => {
    let active = true;
    setLoading(true); setError(false); setData(null); setSelectedId('');
    Promise.all([getAuditProject(id), getAuditPageLifeline(id, pageKey)]).then(([{ data: project }, { data: lifeline }]) => { if (active) setData({ project, lifeline }); }).catch(() => { if (active) setError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id, pageKey, reload]);
  const lifeline = data?.lifeline;
  const orderedRules = lifeline ? [...lifeline.groups.need_action, ...lifeline.groups.needs_confirmation, ...lifeline.groups.closed, ...(lifeline.comparison?.rules.filter(rule => rule.category === 'not_comparable') || [])] : [];
  const selected = orderedRules.find(rule => rule.rule_id === selectedId) || orderedRules[0];
  const latestPost = lifeline && [...lifeline.timeline].reverse().find(target => target.phase === 'post');
  const needsNext = !!latestPost && latestPost.fail > 0;
  const baseline = lifeline?.timeline.find(target => target.id === latestPost?.baseline_target_id);
  const uncompared = lifeline?.comparison?.rules.filter(rule => rule.category === 'not_comparable') || [];
  return <div className="aw"><div className="aw-heading"><nav className="aw-breadcrumb" aria-label="面包屑"><Link to="/audit-projects">项目走查</Link><span>/</span><Link to={`/audit-projects/${id}`}>{data?.project.name || '项目'}</Link><span>/</span><span>{lifeline?.name || '页面生命线'}</span></nav><ProjectViews id={id} view="lifeline" /></div>
    {loading || !data ? <LoadState loading={loading} error={error} retry={() => setReload(value => value + 1)} /> : <>
      <header className="aw-run-header"><div className="aw-chips"><StageBadge stage={data.lifeline.stage} /><span className={`aw-chip ${latestPost?.baseline_target_id ? 'ap-category-fixed' : ''}`}>{latestPost ? latestPost.baseline_target_id ? '已关联上线前基线' : '独立检查 · 未关联基线' : '暂无上线后巡检'}</span>{data.lifeline.timeline.some(target => target.demo) && <DemoBadge source={{ demo: true }} />}</div><h1>{data.lifeline.name}</h1><p className="aw-mono">{data.lifeline.id.startsWith('t:') ? '无业务键 · ' : '业务键 · '}{data.lifeline.id}</p></header>
      <section className="aw-panel" aria-labelledby="timeline-title"><h2 id="timeline-title">这个页面的审核轨迹</h2><div className="aw-scroll" tabIndex={0} role="region" aria-label="审核时间线，可横向滚动"><ol className="ap-audit-timeline">{data.lifeline.timeline.map(target => <li key={target.id} className={`ap-timeline-node aw-${target.phase}`}><span className="ap-timeline-marker" aria-hidden="true"><i /><b /></span><time className="aw-muted" dateTime={target.date}>{auditTime(target.date)}</time><h3><Link to={`/audits/${target.run_id}`}>{target.run_name}</Link></h3><div className="aw-chips"><span className={`aw-chip aw-${target.phase}`}>{target.phase === 'pre' ? '上线前' : '上线后'} · {target.carrier === 'h5' ? 'H5' : 'App'}</span>{target.demo && <DemoBadge source={{ demo: true }} />}</div><Link className="aw-muted" to={`/specs/${data.project.stage_specs[target.phase].find(version => version.id === target.spec_version_id)?.spec_id || ''}?version=${target.spec_version_id}`}>规范 {target.spec_label}</Link><OutcomeBadge outcome={target.outcome} /><p>不符合 {target.fail} · 待确认 {target.uncertain}</p><details><summary>审核摘要</summary><p>{Object.entries(target.summary).filter(([key, value]) => typeof value === 'number' && key in statusLabels).map(([key, value]) => `${statusLabels[key as AuditStatus]} ${value}`).join(' · ') || '暂无规则摘要'}</p></details><Link to={`/audit-targets/${target.id}`}>查看本次结果 →</Link>{target.id === latestPost?.baseline_target_id && <span className="aw-chip aw-pre">当前基线</span>}</li>)}{needsNext && <li className="ap-timeline-node ap-timeline-next"><span className="ap-timeline-marker" aria-hidden="true"><i /></span><span className="aw-muted">下一步</span><h3>整改复查</h3><p>最新巡检仍有 {latestPost?.fail} 项不符合，处理后补充复查记录。</p></li>}</ol></div></section>
      {hasRole('operator') && latestPost && <BaselineControl key={`${latestPost.id}-${latestPost.baseline_target_id || ''}`} lifeline={data.lifeline} onChange={() => setReload(value => value + 1)} />}
      {data.lifeline.independent_check && <aside className="aw-panel ap-independent-notice"><h2>独立检查</h2><p>最新上线后记录未关联基线，暂无规则变化轨迹。可从审核轨迹查看各次结果，或关联同一页面的上线前记录。</p></aside>}
      {data.lifeline.comparison?.spec_mismatch && <p className="aw-warning">两侧规范版本不同；变化类别已由接口按启用状态与载体适用性计算。</p>}
      <div className="ap-lifeline-layout"><section className="ap-rule-tracks" aria-labelledby="tracks-title"><div className="aw-heading"><h2 id="tracks-title">规则轨迹</h2><span className="aw-muted">左：上线前 · 右：上线后</span></div>{groups.map(group => <section key={group.key} className="ap-track-group"><div className="aw-heading"><h3 className={group.className}>{group.title} · {data.lifeline.groups[group.key].length}</h3><span className="aw-muted">{group.hint}</span></div>{data.lifeline.groups[group.key].map(rule => <RuleTrack key={rule.rule_id} rule={rule} selected={selected?.rule_id === rule.rule_id} onSelect={() => setSelectedId(rule.rule_id)} />)}{!data.lifeline.groups[group.key].length && <p className="aw-muted ap-track-empty">暂无此类比对记录。</p>}</section>)}{uncompared.length > 0 && <details className="ap-uncompared"><summary>另有 {uncompared.length} 条规则无法比对</summary>{uncompared.map(rule => <RuleTrack key={rule.rule_id} rule={rule} selected={selected?.rule_id === rule.rule_id} onSelect={() => setSelectedId(rule.rule_id)} />)}</details>}<p className="aw-muted">× 不符合 · ✓ 符合 · ? 待确认；虚线空心点表示不适用、未启用或未覆盖。</p></section>
        <aside className="aw-panel ap-rule-panel" aria-labelledby="observed-title">{selected ? <><CategoryBadge category={selected.category} /><h2 id="observed-title"><span className="aw-mono">{selected.rule_id}</span> {selected.title}</h2><div className="ap-observed"><h3 className="ap-pre-text">上线前观察 · {selected.pre_status ? statusLabels[selected.pre_status] : '未覆盖'}</h3>{baseline && <p className="aw-muted">{baseline.run_name} · {auditTime(baseline.date)}</p>}<p>{selected.pre_observed || '暂无观察文本'}</p></div><div className="ap-observed"><h3 className="ap-post-text">上线后观察 · {selected.post_status ? statusLabels[selected.post_status] : '未覆盖'}</h3>{latestPost && <p className="aw-muted">{latestPost.run_name} · {auditTime(latestPost.date)}</p>}<p>{selected.post_observed || '暂无观察文本'}</p></div><LifelineEvidence preId={baseline?.id} postId={latestPost?.id} ruleId={selected.rule_id} onReload={() => setReload(value => value + 1)} /><div className="ap-insight"><h3>建议下一步</h3><p>{nextSteps[selected.category]}</p></div></> : <><h2 id="observed-title">规则观察</h2><p>关联基线后，选择规则可查看两侧观察文本与下一步建议。</p></>}</aside>
      </div>
    </>}
  </div>;
}
