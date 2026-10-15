import { FormEvent, useEffect, useState } from 'react';
import { isAxiosError } from 'axios';
import { Link } from 'react-router-dom';
import { AuditCarrier, AuditJob, AuditJobStatus, AuditPhase, AuditProjectDetail, AuditRun, AuditSpec, H5AuditInput, H5AuditStep, assignAuditRuns, cancelAuditJob, continueAuditJob, createAuditJob, getAuditExecutor, listAuditJobs, listAuditRuns, listAuditSpecs, recaptureFailedAuditJob } from '../api';
import { useAuth } from '../auth';
import { AuditDialog, auditTime, LoadState } from './AuditWorkspaceUI';

const statusLabels: Record<AuditJobStatus, string> = {
  queued: '已排队', running: '执行中', needs_action: '需要人处理', ingesting: '正在收录',
  completed: '已完成', failed: '失败', cancelled: '已取消',
};
const isActive = (job: AuditJob) => !['completed', 'failed', 'cancelled'].includes(job.status);
const gateLabels: Record<string, string> = { venue_lost: '活动迷路', login_required: '需要登录', expired: '活动过期', not_ready: '加载未就绪', capture_failed: '采集失败' };
const canRecapture = (job: AuditJob) => job.carrier === 'h5' && ['completed', 'failed'].includes(job.status) && !!job.executor_ref_json.summary?.blocked_venue_ids.length;
const stepLabels: Record<H5AuditStep, string> = {
  preflight: '检查登录', catalog: '读取目录', capture: '采集会场', profile: '准备规范',
  audit: '模型审核', report: '生成报告', ingest: '收录结果',
};
const dismissedKey = 'audit-jobs:dismissed:v1';
function failureExpiry(job: AuditJob): number {
  if (job.status !== 'failed' || !job.finished_at) return 0;
  const timestamp = /(?:Z|[+-]\d{2}:\d{2})$/i.test(job.finished_at) ? job.finished_at : `${job.finished_at}Z`;
  return Date.parse(timestamp) + 24 * 60 * 60 * 1000;
}
const recentFailure = (job: AuditJob) => failureExpiry(job) > Date.now();
function readDismissed(): Set<string> {
  try {
    const stored: unknown = JSON.parse(localStorage.getItem(dismissedKey) || '[]');
    return new Set(Array.isArray(stored) ? stored.filter((id): id is string => typeof id === 'string') : []);
  } catch { return new Set(); }
}
function errorText(error: unknown) {
  return isAxiosError(error) && typeof error.response?.data?.detail === 'string'
    ? error.response.data.detail : '操作失败，请重试。';
}

export function AuditLaunchDialog({ project, initialCarrier = 'h5', onClose, onCreated }: {
  project?: AuditProjectDetail; initialCarrier?: AuditCarrier; onClose: () => void; onCreated: () => void;
}) {
  const [carrier, setCarrier] = useState<AuditCarrier>(initialCarrier);
  const [h5Source, setH5Source] = useState<'catalog_url' | 'catalog_dir'>('catalog_url');
  const [phase, setPhase] = useState<AuditPhase>('pre');
  const [specs, setSpecs] = useState<AuditSpec[]>([]);
  const [selectedVersion, setSelectedVersion] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [reload, setReload] = useState(0);
  const [availability, setAvailability] = useState<{ versionId: string; carrier: AuditCarrier; available: boolean; reason: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const versions = specs.flatMap(spec => spec.versions.filter(version => version.carrier_scope === carrier || version.carrier_scope === 'both').map(version => ({ ...version, specName: spec.name })));
  const preferred = project ? [...project.stage_specs[phase], ...project.stage_specs[phase === 'pre' ? 'post' : 'pre']].find(bound => versions.some(version => version.id === bound.id)) : undefined;
  const versionId = versions.find(version => version.id === selectedVersion)?.id || preferred?.id || versions[0]?.id || '';
  const checked = availability?.versionId === versionId && availability.carrier === carrier ? availability : null;
  useEffect(() => {
    let active = true;
    setLoading(true); setLoadError(false);
    listAuditSpecs().then(({ data }) => { if (active) setSpecs(data); })
      .catch(() => { if (active) setLoadError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reload]);
  useEffect(() => {
    if (!versionId) return;
    let active = true;
    setAvailability(null);
    getAuditExecutor(versionId, carrier).then(({ data }) => {
      if (active) setAvailability({ versionId, carrier, ...data });
    }).catch(() => {
      if (active) setAvailability({ versionId, carrier, available: false, reason: '无法检查执行器，请重新选择版本或稍后重试。' });
    });
    return () => { active = false; };
  }, [versionId, carrier]);
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!checked?.available || busy) return;
    const fields = new FormData(event.currentTarget);
    const value = (name: string) => String(fields.get(name) || '').trim();
    const venueIds = [...new Set(value('venue_ids').split(/\r?\n/).map(id => id.trim()).filter(Boolean))];
    if (carrier === 'h5' && venueIds.some(id => !/^RA\d+$/.test(id))) {
      setError('会场 ID 请按 RA 编号逐行填写，例如 RA092915121822266376。');
      return;
    }
    const h5Input: H5AuditInput = {
      ...(h5Source === 'catalog_url' ? { catalog_url: value('catalog_url') } : { catalog_dir: value('catalog_dir') }),
      ...(venueIds.length ? { venue_ids: venueIds } : {}),
    };
    const input = carrier === 'h5' ? h5Input : {
      target_name: value('target_name'), business_key: value('business_key') || undefined,
      target_app: value('target_app'), scenario: value('scenario'), description: value('description') || undefined,
    };
    setBusy(true); setError('');
    try {
      await createAuditJob({ name: value('name'), carrier, phase, spec_version_id: versionId, project_id: project?.id, input });
      onCreated(); onClose();
    } catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  }
  const importParams = new URLSearchParams({ carrier, import: carrier, phase, ...(versionId ? { spec_version_id: versionId } : {}), ...(project ? { project_id: project.id } : {}) });
  return <AuditDialog title="发起审核" onClose={onClose}>
    {loading || loadError ? <LoadState loading={loading} error={loadError} retry={() => setReload(value => value + 1)} /> : <form className="aw-form" onSubmit={submit}>
      <label>载体<select value={carrier} onChange={event => { setCarrier(event.target.value as AuditCarrier); setSelectedVersion(''); }}><option value="h5">H5</option><option value="app">App</option></select></label>
      <label>阶段<select value={phase} onChange={event => { setPhase(event.target.value as AuditPhase); setSelectedVersion(''); }}><option value="pre">上线前</option><option value="post">上线后</option></select></label>
      <label>规范版本<select required value={versionId} onChange={event => setSelectedVersion(event.target.value)}>{versions.length ? versions.map(version => <option key={version.id} value={version.id}>{version.specName} · {version.label}</option>) : <option value="">没有适用版本，请先在规范库导入</option>}</select></label>
      {versionId && !checked ? <p role="status">正在检查执行器…</p> : null}
      {checked && !checked.available ? <div className="aw-job-notice"><p role="status">{checked.reason}</p><Link to={`/audits?${importParams}`} onClick={onClose}>改为导入结果 →</Link></div> : null}
      <label>审核名称<input name="name" required pattern=".*\S.*" maxLength={200} defaultValue={project ? `${project.name}审核` : ''} /></label>
      {carrier === 'app' ? <>
        <label>对象名称<input name="target_name" required pattern=".*\S.*" maxLength={200} /></label>
        <label>业务键（可选）<input name="business_key" placeholder="会场 ID 或页面业务标识" /></label>
        <label>目标 App<input name="target_app" required pattern=".*\S.*" /></label>
        <label>场景<input name="scenario" required pattern=".*\S.*" /></label>
        <label>补充描述（可选）<textarea name="description" rows={3} /></label>
      </> : <>
        <fieldset className="aw-job-source"><legend>会场来源</legend>
          <label className="aw-check"><input type="radio" name="h5_source" value="catalog_url" checked={h5Source === 'catalog_url'} onChange={() => setH5Source('catalog_url')} />提报列表链接</label>
          <label className="aw-check"><input type="radio" name="h5_source" value="catalog_dir" checked={h5Source === 'catalog_dir'} onChange={() => setH5Source('catalog_dir')} />复用已有目录</label>
        </fieldset>
        {h5Source === 'catalog_url'
          ? <label>提报列表链接<input name="catalog_url" type="url" required pattern="https://yx\.jd\.com/.*" placeholder="https://yx.jd.com/…" /></label>
          : <label>已有目录<input name="catalog_dir" required pattern=".*\S.*" placeholder="data/ 下的相对路径，如 tasks/venue-capture" /></label>}
        <label>会场 ID（可选）<textarea name="venue_ids" rows={4} placeholder={'每行一个 RA 编号，例如：\nRA092915121822266376'} aria-describedby="aw-venue-hint" /></label>
        <p className="aw-muted" id="aw-venue-hint">留空表示全部会场；会场多时模型审核耗时和费用较高，建议先选少量会场试跑。</p>
      </>}
      {error ? <p role="alert">{error}</p> : null}
      <div className="aw-actions"><button type="button" className="aw-secondary" onClick={onClose}>取消</button><button disabled={busy || !checked?.available}>{busy ? '正在发起…' : '发起审核'}</button></div>
    </form>}
  </AuditDialog>;
}

export function AuditJobsSection({ projectId, reload, onTerminal }: { projectId?: string; reload: number; onTerminal: () => void }) {
  const { hasRole } = useAuth();
  const [jobs, setJobs] = useState<AuditJob[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [dismissed, setDismissed] = useState(readDismissed);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    let previous = new Set<string>();
    let firstRead = true;
    async function poll() {
      try {
        const { data } = await listAuditJobs({ project_id: projectId, status: 'all' });
        if (!active) return;
        const current = new Set(data.filter(isActive).map(job => job.id));
        // A first read may itself complete a job; refresh dependent cockpit data too.
        if ((firstRead && data.some(job => job.status === 'completed')) || [...previous].some(id => !current.has(id))) onTerminal();
        firstRead = false; previous = current;
        setJobs(data); setError('');
        const nextExpiry = Math.min(...data.filter(recentFailure).map(failureExpiry));
        if (current.size || Number.isFinite(nextExpiry)) timer = setTimeout(poll, current.size ? 5000 : Math.max(1, nextExpiry - Date.now() + 1));
      } catch (err) {
        if (active) { setError(errorText(err)); timer = setTimeout(poll, 5000); }
      }
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [projectId, reload, retry, onTerminal]);
  async function act(job: AuditJob, action: 'continue' | 'cancel' | 'recapture') {
    setBusy(job.id); setError('');
    try {
      const { data } = await (action === 'recapture' ? recaptureFailedAuditJob(job.id) : action === 'continue' ? continueAuditJob(job.id) : cancelAuditJob(job.id));
      setJobs(previous => action === 'recapture' ? [data, ...previous] : previous.map(item => item.id === data.id ? data : item));
      if (action === 'recapture') setRetry(value => value + 1);
      if (!isActive(data)) onTerminal();
    } catch (err) { setError(errorText(err)); } finally { setBusy(null); }
  }
  function dismiss(jobId: string) {
    const next = new Set([...dismissed, jobId]);
    setDismissed(next);
    try { localStorage.setItem(dismissedKey, JSON.stringify([...next])); } catch { /* Hiding still works for this visit. */ }
  }
  const visible = jobs.filter(job => isActive(job) || ((recentFailure(job) || canRecapture(job)) && !dismissed.has(job.id)));
  return <section className="aw-jobs" aria-label="进行中的审核任务">
    {visible.length ? <h2>进行中 <span className="aw-muted">{jobs.filter(isActive).length}</span></h2> : !projectId ? <h2>进行中 <span className="aw-muted">0</span></h2> : null}
    {error ? <p role="alert">{error} <button type="button" className="aw-secondary" onClick={() => setRetry(value => value + 1)}>重试</button></p> : null}
    {visible.map(job => <article className={`aw-panel aw-job-card${job.status === 'needs_action' ? ' aw-job-needs-action' : ''}`} key={job.id}>
      <div className="aw-heading"><h3>{job.name}</h3><span className={`aw-chip ${job.status === 'failed' || job.status === 'needs_action' ? 'aw-warning' : 'aw-pre'}`}>{statusLabels[job.status]}</span></div>
      <p className="aw-muted">{job.carrier === 'h5' ? 'H5' : 'App'} · {job.phase === 'pre' ? '上线前' : '上线后'} · {auditTime(job.created_at)}</p>
      {job.status === 'running' && job.executor_ref_json.step ? <p className="aw-job-step">当前步骤：{stepLabels[job.executor_ref_json.step as H5AuditStep] || job.executor_ref_json.step}</p> : null}
      {job.status_detail ? <p className="aw-job-detail" role={job.status === 'needs_action' ? 'status' : undefined}>{job.status_detail}</p> : null}
      {job.status === 'failed' && job.error ? <p role="alert">{job.error}</p> : null}
      {job.carrier === 'h5' && job.executor_ref_json.summary ? <div className="aw-job-notice">
        <p>已拦截 {job.executor_ref_json.summary.gate.blocked} 个无效页面{job.executor_ref_json.summary.gate.blocked ? `：${Object.entries(job.executor_ref_json.summary.gate.by_reason).map(([reason, count]) => `${gateLabels[reason] || reason} ${count}`).join('，')}` : ''}；降级审核 {job.executor_ref_json.summary.gate.degraded} 个</p>
        {job.executor_ref_json.summary.hint ? <p>{job.executor_ref_json.summary.hint}</p> : null}
      </div> : null}
      {hasRole('operator') && canRecapture(job) ? <div className="aw-actions"><button type="button" className="aw-secondary" disabled={busy !== null} onClick={() => act(job, 'recapture')}>{busy === job.id ? '处理中…' : '仅重采失败会场'}</button></div> : null}
      {job.status === 'failed' || canRecapture(job) ? <div className="aw-actions"><button type="button" className="aw-secondary" onClick={() => dismiss(job.id)}>知道了</button></div> : null}
      {hasRole('operator') && isActive(job) ? <div className="aw-actions">
        {job.status === 'needs_action' ? <button type="button" disabled={busy !== null} onClick={() => act(job, 'continue')}>继续</button> : null}
        <button type="button" className="aw-secondary" disabled={busy !== null} onClick={() => act(job, 'cancel')}>{busy === job.id ? '处理中…' : '取消'}</button>
      </div> : null}
    </article>)}
  </section>;
}

export function AssignAuditRunsDialog({ projectId, onClose, onAssigned }: { projectId: string; onClose: () => void; onAssigned: () => void }) {
  const [runs, setRuns] = useState<AuditRun[]>([]);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    setLoading(true); setLoadError(false);
    listAuditRuns({ unassigned: true }).then(({ data }) => { if (active) setRuns(data); })
      .catch(() => { if (active) setLoadError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reload]);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true); setError('');
    try { await assignAuditRuns(projectId, [...selected]); onAssigned(); onClose(); }
    catch (err) { setError(errorText(err)); } finally { setBusy(false); }
  }
  return <AuditDialog title="归入已有审核" onClose={onClose}>{loading || loadError ? <LoadState loading={loading} error={loadError} retry={() => setReload(value => value + 1)} /> : <form className="aw-form" onSubmit={submit}>
    <p className="aw-muted">选择尚未归入项目的 H5 或 App 审核。</p><div className="aw-assign-list">{runs.map(run => <label className="aw-check aw-assign-option" key={run.id}><input type="checkbox" checked={selected.has(run.id)} onChange={event => setSelected(previous => { const next = new Set(previous); if (event.target.checked) next.add(run.id); else next.delete(run.id); return next; })} /><span><strong>{run.name}</strong><small>{run.carrier === 'h5' ? 'H5' : 'App'} · {run.phase === 'pre' ? '上线前' : '上线后'} · {run.spec_version.label} · {auditTime(run.created_at)}</small></span></label>)}</div>
    {!runs.length ? <p>暂无未归入项目的审核。</p> : null}{error ? <p role="alert">{error}</p> : null}<div className="aw-actions"><button type="button" className="aw-secondary" onClick={onClose}>取消</button><button disabled={busy || !selected.size}>{busy ? '正在归入…' : `归入所选审核（${selected.size}）`}</button></div>
  </form>}</AuditDialog>;
}
