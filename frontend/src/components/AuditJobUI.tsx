import { FormEvent, useEffect, useState } from 'react';
import { isAxiosError } from 'axios';
import { Link } from 'react-router-dom';
import { AuditCarrier, AuditJob, AuditJobStatus, AuditPhase, AuditProjectDetail, AuditRun, AuditSpec, assignAuditRuns, cancelAuditJob, continueAuditJob, createAuditJob, getAuditExecutor, listAuditJobs, listAuditRuns, listAuditSpecs } from '../api';
import { useAuth } from '../auth';
import { AuditDialog, auditTime, LoadState } from './AuditWorkspaceUI';

const statusLabels: Record<AuditJobStatus, string> = {
  queued: '已排队', running: '执行中', needs_action: '需要人处理', ingesting: '正在收录',
  completed: '已完成', failed: '失败', cancelled: '已取消',
};
const isActive = (job: AuditJob) => !['completed', 'failed', 'cancelled'].includes(job.status);
function errorText(error: unknown) {
  return isAxiosError(error) && typeof error.response?.data?.detail === 'string'
    ? error.response.data.detail : '操作失败，请重试。';
}

export function AuditLaunchDialog({ project, initialCarrier = 'h5', onClose, onCreated }: {
  project?: AuditProjectDetail; initialCarrier?: AuditCarrier; onClose: () => void; onCreated: () => void;
}) {
  const [carrier, setCarrier] = useState<AuditCarrier>(initialCarrier);
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
    const recordIds = value('record_ids').split(/[\s,，]+/).filter(Boolean);
    const input = carrier === 'h5' ? (recordIds.length ? { record_ids: recordIds } : {}) : {
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
      </> : <label>会场 ID（可选）<textarea name="record_ids" rows={4} placeholder="每行一个会场 ID；留空使用最新目录中的全部会场" /></label>}
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
        if (current.size) timer = setTimeout(poll, 5000);
      } catch (err) {
        if (active) { setError(errorText(err)); timer = setTimeout(poll, 5000); }
      }
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [projectId, reload, retry, onTerminal]);
  async function act(job: AuditJob, action: 'continue' | 'cancel') {
    setBusy(job.id); setError('');
    try {
      const { data } = await (action === 'continue' ? continueAuditJob(job.id) : cancelAuditJob(job.id));
      setJobs(previous => previous.map(item => item.id === data.id ? data : item));
      if (!isActive(data)) onTerminal();
    } catch (err) { setError(errorText(err)); } finally { setBusy(null); }
  }
  const visible = jobs.filter(job => isActive(job) || job.status === 'failed');
  return <section className="aw-jobs" aria-label="进行中的审核任务">
    {visible.length ? <h2>进行中 <span className="aw-muted">{jobs.filter(isActive).length}</span></h2> : !projectId ? <h2>进行中 <span className="aw-muted">0</span></h2> : null}
    {error ? <p role="alert">{error} <button type="button" className="aw-secondary" onClick={() => setRetry(value => value + 1)}>重试</button></p> : null}
    {visible.map(job => <article className="aw-panel aw-job-card" key={job.id}><div className="aw-heading"><h3>{job.name}</h3><span className={`aw-chip ${job.status === 'failed' ? 'aw-warning' : 'aw-pre'}`}>{statusLabels[job.status]}</span></div><p className="aw-muted">{job.carrier === 'h5' ? 'H5' : 'App'} · {job.phase === 'pre' ? '上线前' : '上线后'} · {auditTime(job.created_at)}</p>{job.status_detail ? <p>{job.status_detail}</p> : null}{job.status === 'failed' && job.error ? <p role="alert">{job.error}</p> : null}{hasRole('operator') && isActive(job) ? <div className="aw-actions">{job.status === 'needs_action' ? <button type="button" disabled={busy !== null} onClick={() => act(job, 'continue')}>继续</button> : null}<button type="button" className="aw-secondary" disabled={busy !== null} onClick={() => act(job, 'cancel')}>{busy === job.id ? '处理中…' : '取消'}</button></div> : null}</article>)}
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
