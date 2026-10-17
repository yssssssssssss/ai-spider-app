import { FormEvent, useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { AuditAppCandidate, AuditCarrier, AuditPhase, AuditProjectListItem, AuditRun, AuditSpec, collectAuditAppRun, importAuditH5Run, listAuditAppCandidates, listAuditProjects, listAuditRuns, listAuditSpecs } from '../api';
import { useAuth } from '../auth';
import { DashboardRing, outcomeSegments } from '../components/AuditDashboardUI';
import { AuditJobsSection, AuditLaunchDialog } from '../components/AuditJobUI';
import { AuditDialog, auditTime, CompositionBar, DemoBadge, LoadState } from '../components/AuditWorkspaceUI';

function RunImportDialog({ carrier, params, onClose }: { carrier: AuditCarrier; params: URLSearchParams; onClose: () => void }) {
  const navigate = useNavigate();
  const [specs, setSpecs] = useState<AuditSpec[]>([]);
  const [candidates, setCandidates] = useState<AuditAppCandidate[]>([]);
  const [candidateId, setCandidateId] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(false);
    Promise.all([listAuditSpecs(), carrier === 'app' ? listAuditAppCandidates() : Promise.resolve({ data: [] as AuditAppCandidate[] })]).then(([specResult, candidateResult]) => {
      if (!active) return;
      setSpecs(specResult.data); setCandidates(candidateResult.data); setCandidateId(candidateResult.data[0]?.task_run_id || '');
    }).catch(() => { if (active) setError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [carrier, reload]);
  const versions = specs.flatMap(spec => spec.versions.filter(v => v.carrier_scope === carrier || v.carrier_scope === 'both').map(v => ({ ...v, specName: spec.name })));
  const candidate = candidates.find(c => c.task_run_id === candidateId);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const name = String(data.get('name')).trim();
    const spec_version_id = String(data.get('spec_version_id'));
    const phase = data.get('phase') as AuditPhase;
    const project_id = params.get('project_id') || undefined;
    setBusy(true); setFormError(false);
    try {
      const result = carrier === 'h5' ? await importAuditH5Run({ file: data.get('file') as File, name, spec_version_id, phase, project_id, venue_ids: String(data.get('venue_ids') || '').trim().split(/[\s,，]+/).filter(Boolean).join(',') }) : await collectAuditAppRun({
        name, spec_version_id, phase, project_id, task_run_id: candidateId, skill_id: String(data.get('skill_id')),
        business_key: String(data.get('business_key')).trim() || null, target_name: String(data.get('target_name')).trim(),
      });
      navigate(`/audits/${result.data.id}`);
    } catch { setFormError(true); } finally { setBusy(false); }
  }
  return <AuditDialog title={carrier === 'h5' ? '导入 H5 结果' : '收录 App 结果'} onClose={onClose}>
    {loading || error ? <LoadState loading={loading} error={error} retry={() => setReload(x => x + 1)} /> : <form className="aw-form" onSubmit={submit}>
      {carrier === 'h5' ? <label>审核结果 JSON<input type="file" name="file" accept=".json,application/json" required /><small>上传 CLI 生成的 results.json。</small></label> : <>
        <label>已完成的 App 任务<select value={candidateId} onChange={event => setCandidateId(event.target.value)} required>{candidates.length ? candidates.map(c => <option key={c.task_run_id} value={c.task_run_id}>{c.task_name} · {auditTime(c.completed_at)} · {c.task_run_id.slice(0, 8)}</option>) : <option value="">暂无可收录任务</option>}</select></label>
        <label>执行 Skill<select key={candidateId} name="skill_id" required defaultValue={candidate?.skills[0]?.id || ''}>{candidate?.skills.map(skill => <option key={skill.id} value={skill.id}>{skill.name} · v{skill.version}</option>)}</select></label>
      </>}
      <label>规范版本<select name="spec_version_id" required defaultValue={versions.find(version => version.id === params.get('spec_version_id'))?.id || versions[0]?.id || ''}>{versions.length ? versions.map(v => <option key={v.id} value={v.id}>{v.specName} · {v.label} · {v.carrier_scope === 'both' ? 'H5 / App' : carrier === 'h5' ? 'H5' : 'App'}</option>) : <option value="">没有适用版本，请先在规范库导入</option>}</select></label>
      <label>审核名称<input name="name" required pattern=".*\S.*" maxLength={200} /></label>
      {carrier === 'h5' ? <label>会场 ID（可选）<textarea name="venue_ids" rows={2} placeholder="以逗号或换行分隔；留空导入全部对象" /></label> : <><label>对象名称<input name="target_name" required pattern=".*\S.*" maxLength={200} /></label><label>业务键（可选）<input name="business_key" placeholder="会场 ID 或页面业务标识" /></label></>}
      <label>阶段<select name="phase" defaultValue={params.get('phase') === 'pre' || params.get('phase') === 'post' ? params.get('phase')! : carrier === 'h5' ? 'pre' : 'post'}><option value="pre">上线前</option><option value="post">上线后</option></select></label>
      {formError && <p role="alert">收录失败，已保留填写内容，请检查后重试。</p>}
      <button disabled={busy || !versions.length || (carrier === 'app' && !candidate?.skills.length)}>{busy ? '正在收录，请稍候…' : carrier === 'h5' ? '导入结果' : '收录结果'}</button>
    </form>}
  </AuditDialog>;
}

export default function AuditRuns() {
  const { hasRole } = useAuth();
  const [params, setParams] = useSearchParams();
  const carrier: AuditCarrier = params.get('carrier') === 'app' ? 'app' : 'h5';
  const unassigned = params.get('unassigned') === 'true';
  const [runs, setRuns] = useState<AuditRun[]>([]);
  const [projects, setProjects] = useState<AuditProjectListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);
  const importing = params.get('import') === 'h5' || params.get('import') === 'app' ? params.get('import') as AuditCarrier : null;
  const [launching, setLaunching] = useState(false);
  const [jobsReload, setJobsReload] = useState(0);
  const refresh = useCallback(() => setReload(value => value + 1), []);
  function setImporting(value: AuditCarrier | null) {
    setParams(previous => {
      const next = new URLSearchParams(previous);
      if (value) next.set('import', value);
      else ['import', 'spec_version_id', 'phase', 'project_id'].forEach(key => next.delete(key));
      return next;
    });
  }
  useEffect(() => {
    let active = true;
    setLoading(true); setError(false);
    Promise.all([listAuditRuns({ carrier, unassigned }), listAuditProjects()]).then(([runResult, projectResult]) => { if (active) { setRuns(runResult.data); setProjects(projectResult.data); } }).catch(() => { if (active) setError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [carrier, unassigned, reload]);
  const projectNames = new Map(projects.map(p => [p.id, p.name]));
  const totals = runs.reduce((sum, run) => {
    sum.targets += run.summary_json.targets;
    for (const outcome of Object.keys(sum.outcomes) as (keyof typeof sum.outcomes)[]) sum.outcomes[outcome] += run.summary_json.outcomes[outcome];
    return sum;
  }, { targets: 0, outcomes: { issues: 0, needs_confirmation: 0, partial: 0, clean: 0, capture_failed: 0 } });
  const segments = outcomeSegments(totals.outcomes);
  function changeFilter(nextCarrier: AuditCarrier, nextUnassigned: boolean) {
    setParams({ carrier: nextCarrier, ...(nextUnassigned ? { unassigned: 'true' } : {}) });
  }
  return <div className="aw aw-runs-page">
    <header className="aw-heading"><div><div className="aw-eyebrow">审核工作台 / 审核</div><h1>审核</h1><p>收录 H5 与 App 结果，查看每一次审核的结论与处理顺序。</p></div>{hasRole('operator') && <div className="aw-actions"><button type="button" onClick={() => setLaunching(true)}>发起审核</button><button type="button" className="aw-secondary" onClick={() => setImporting('h5')}>导入 H5 结果</button><button type="button" onClick={() => setImporting('app')}>收录 App 结果</button></div>}</header>
    {!loading && !error && <section className="aw-kpi-band aw-run-kpis" aria-label="当前筛选范围的审核指标">
      <div className="aw-kpi"><span>审核次数</span><strong>{runs.length}</strong><small>当前筛选范围</small></div>
      <div className="aw-kpi"><span>审核对象总数</span><strong>{totals.targets}</strong><small>各次审核对象累计</small></div>
      <div className="aw-outcome-donut"><DashboardRing label={`审核结果分布：${segments.map(item => `${item.label} ${item.count}`).join('，')}`} value={totals.targets || '暂无'} caption="对象分布" segments={segments} /><div className="aw-donut-legend">{segments.map(item => <span key={item.tone}><i className={`aw-key aw-fill-${item.tone}`} />{item.tone === 'pass' ? '部分 / 全部符合' : item.label}<strong>{item.count}</strong></span>)}</div></div>
    </section>}
    <AuditJobsSection reload={jobsReload} onTerminal={refresh} />
    <div className="aw-heading"><div className="aw-tabs" role="group" aria-label="审核载体"><button type="button" className="aw-tab aw-pre" aria-pressed={carrier === 'h5'} onClick={() => changeFilter('h5', unassigned)}>H5 · 上线前</button><button type="button" className="aw-tab aw-post" aria-pressed={carrier === 'app'} onClick={() => changeFilter('app', unassigned)}>App · 上线后</button></div><label className="aw-check"><input type="checkbox" checked={unassigned} onChange={event => changeFilter(carrier, event.target.checked)} />仅未归入项目</label></div>
    {loading || error ? <LoadState loading={loading} error={error} retry={() => setReload(x => x + 1)} /> : runs.length ? <section className="aw-run-list" aria-label={carrier === 'h5' ? 'H5 审核列表' : 'App 审核列表'}>{runs.map(run => <article className="aw-panel aw-run-row" key={run.id}>
      <div><div className="aw-chips"><span className={`aw-chip aw-${run.phase}`}>{run.carrier === 'h5' ? 'H5' : 'App'} · {run.phase === 'pre' ? '上线前' : '上线后'}</span><DemoBadge source={run.source_ref_json} /></div><h2><Link to={`/audits/${run.id}`}>{run.name}</Link></h2><time className="aw-muted" dateTime={run.created_at}>{auditTime(run.created_at)}</time></div>
      <div className="aw-run-spec"><span className="aw-muted">规范版本</span><Link to={`/specs/${run.spec_version.spec_id}?version=${run.spec_version_id}`}>{run.spec_version.label}</Link><span className="aw-chip">{run.project_id ? projectNames.get(run.project_id) || '已归入项目' : '独立审核'}</span></div>
      <div className="aw-run-composition"><strong>{run.summary_json.targets} <small>个对象</small></strong><CompositionBar compact composition={{ total: run.summary_json.targets, outcomes: run.summary_json.outcomes }} /><span className="aw-muted">不符合 {run.summary_json.outcomes.issues} · 待确认 {run.summary_json.outcomes.needs_confirmation} · 采集失败 {run.summary_json.outcomes.capture_failed}</span></div>
      <Link className="aw-open-run" to={`/audits/${run.id}`} aria-label={`打开 ${run.name}`}>查看 →</Link>
    </article>)}</section> : <div className="aw-panel aw-empty">暂无{unassigned ? '独立' : ''}{carrier === 'h5' ? ' H5 ' : ' App '}审核。</div>}
    {hasRole('operator') && importing ? <RunImportDialog key={importing} carrier={importing} params={params} onClose={() => setImporting(null)} /> : null}
    {launching ? <AuditLaunchDialog initialCarrier={carrier} onClose={() => setLaunching(false)} onCreated={() => setJobsReload(value => value + 1)} /> : null}
  </div>;
}
