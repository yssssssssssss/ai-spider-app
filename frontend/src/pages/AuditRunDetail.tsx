import { FormEvent, useEffect, useState } from 'react';
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { AuditOutcome, AuditRunDetail as RunDetail, AuditSort, AuditTargetBrief, AuditTargetList, AuditVersionDetail, deleteAuditRun, getAuditRun, getAuditSpecVersion, listAuditProjects, listAuditTargets, updateAuditRun } from '../api';
import { useAuth } from '../auth';
import { AuditDialog, auditTime, captureLabels, CompositionBar, DemoBadge, LoadState, OutcomeBadge, outcomeLabels, outcomeOrder } from '../components/AuditWorkspaceUI';
import { AuditBarcode, AuditParetoChart, AuditTriage, AuditWaffle } from '../components/AuditRunVisuals';

function TargetTable({ runId, outcome, page, search, sort, change }: {
  runId: string; outcome?: AuditOutcome; page: number; search: string; sort: AuditSort;
  change: (values: Record<string, string>) => void;
}) {
  const [result, setResult] = useState<AuditTargetList | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);
  const [draft, setDraft] = useState(search);
  useEffect(() => { setDraft(search); }, [search]);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(false);
    listAuditTargets(runId, { page, page_size: 20, search: search || undefined, outcome, sort }).then(({ data }) => { if (active) setResult(data); }).catch(() => { if (active) setError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [runId, outcome, page, search, sort, reload]);
  return <section className="aw-panel" id="audit-details" aria-labelledby="details-title"><div className="aw-heading"><h2 id="details-title">对象明细</h2><span className="aw-muted">每页 20 条 · {outcome ? outcomeLabels[outcome] : '全部结果'}</span></div>
    <form className="aw-table-filters" onSubmit={event => { event.preventDefault(); change({ search: draft.trim(), page: '1' }); }}>
      <label className="aw-search">搜索名称 / 业务键<input type="search" value={draft} onChange={event => setDraft(event.target.value)} placeholder="输入对象名称或业务键" /></label><button type="submit" className="aw-secondary">搜索</button>
      <label>结果<select value={outcome || ''} onChange={event => change({ outcome: event.target.value, page: '1' })}><option value="">全部结果</option>{outcomeOrder.map(key => <option key={key} value={key}>{outcomeLabels[key]}</option>)}</select></label>
      <label>排序<select value={sort} onChange={event => change({ sort: event.target.value, page: '1' })}><option value="fail">不符合数降序</option><option value="uncertain">待确认数降序</option><option value="name">名称升序</option></select></label>
    </form>
    {loading || error ? <LoadState loading={loading} error={error} retry={() => setReload(x => x + 1)} /> : result && <>
      <div className="aw-scroll" tabIndex={0} role="region" aria-label="对象明细表"><table className="aw-target-table"><thead><tr><th scope="col">对象名称 / 业务键</th><th scope="col">结果</th><th scope="col" className="aw-numbers">不符合</th><th scope="col" className="aw-numbers">待确认</th><th scope="col">采集原因</th></tr></thead><tbody>{result.items.map(target => <tr key={target.id}><td><Link to={`/audit-targets/${target.id}`}>{target.name}</Link><small className="aw-business-key">{target.business_key || '无业务键'}</small></td><td><OutcomeBadge outcome={target.outcome} /></td><td className="aw-numbers">{target.fail}</td><td className="aw-numbers">{target.uncertain}</td><td>{target.capture_reason ? captureLabels[target.capture_reason] : '—'}</td></tr>)}{!result.items.length && <tr><td colSpan={5} className="aw-empty">没有匹配对象。</td></tr>}</tbody></table></div>
      <div className="aw-heading aw-pagination"><span className="aw-muted">共 {result.total} 个对象 · 第 {result.page} / {Math.max(1, Math.ceil(result.total / 20))} 页</span><div className="aw-actions"><button type="button" className="aw-secondary" disabled={page <= 1} onClick={() => change({ page: String(page - 1) })}>上一页</button><button type="button" className="aw-secondary" disabled={page * 20 >= result.total} onClick={() => change({ page: String(page + 1) })}>下一页</button></div></div>
    </>}
  </section>;
}

export default function AuditRunDetail() {
  const { runId = '' } = useParams();
  const navigate = useNavigate();
  const { hasRole } = useAuth();
  const [params, setParams] = useSearchParams();
  const rawOutcome = params.get('outcome');
  const outcome = outcomeOrder.includes(rawOutcome as AuditOutcome) ? rawOutcome as AuditOutcome : undefined;
  const sort: AuditSort = params.get('sort') === 'uncertain' ? 'uncertain' : params.get('sort') === 'name' ? 'name' : 'fail';
  const rawPage = Number(params.get('page') || 1);
  const page = Number.isSafeInteger(rawPage) && rawPage > 0 ? rawPage : 1;
  const search = params.get('search') || '';
  const [data, setData] = useState<{ run: RunDetail; version: AuditVersionDetail; captures: AuditTargetBrief[]; projectName: string } | null>(null);
  const [filtered, setFiltered] = useState<{ runId: string; outcome: AuditOutcome; run: RunDetail } | null>(null);
  const [filterLoading, setFilterLoading] = useState(false);
  const [filterError, setFilterError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);
  const [dialog, setDialog] = useState<'rename' | 'delete' | null>(null);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState(false);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(false); setData(null);
    (async () => {
      const { data: run } = await getAuditRun(runId);
      const capturePages = Math.ceil(run.composition.outcomes.capture_failed / 100);
      const [versionResult, projectResult, captures] = await Promise.all([
        getAuditSpecVersion(run.spec_version_id),
        run.project_id ? listAuditProjects() : Promise.resolve({ data: [] }),
        Promise.all(Array.from({ length: capturePages }, (_, i) => listAuditTargets(runId, { page: i + 1, page_size: 100, outcome: 'capture_failed', sort: 'name' }))),
      ]);
      if (active) setData({ run, version: versionResult.data, captures: captures.flatMap(result => result.data.items), projectName: projectResult.data.find(project => project.id === run.project_id)?.name || '已归入项目' });
    })().catch(() => { if (active) setError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [runId, reload]);
  useEffect(() => {
    let active = true;
    setFilterError(false);
    if (!outcome) { setFilterLoading(false); return; }
    setFilterLoading(true);
    getAuditRun(runId, outcome).then(({ data: run }) => { if (active) setFiltered({ runId, outcome, run }); }).catch(() => { if (active) setFilterError(true); }).finally(() => { if (active) setFilterLoading(false); });
    return () => { active = false; };
  }, [runId, outcome, reload]);
  function change(values: Record<string, string>) {
    const next = new URLSearchParams(params);
    Object.entries(values).forEach(([key, value]) => { if (value) next.set(key, value); else next.delete(key); });
    setParams(next, { preventScrollReset: true });
  }
  async function mutate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    setBusy(true); setFormError(false);
    try {
      if (dialog === 'delete') { await deleteAuditRun(runId); navigate('/audits', { replace: true }); }
      else {
        const { data: updated } = await updateAuditRun(runId, { name: String(fields.get('name')).trim() });
        setData(current => current ? { ...current, run: { ...current.run, name: updated.name } } : current); setDialog(null);
      }
    } catch { setFormError(true); } finally { setBusy(false); }
  }
  const run = data?.run;
  const view = outcome ? filtered?.runId === runId && filtered.outcome === outcome ? filtered.run : null : run;
  return <div className="aw">
    <nav className="aw-breadcrumb" aria-label="面包屑"><Link to="/audits">审核</Link><span>/</span>{run && <><Link to={`/audits?carrier=${run.carrier}`}>{run.carrier === 'h5' ? 'H5 审核' : 'App 审核'}</Link><span>/</span></>}<span>{run?.name || '审核驾驶舱'}</span></nav>
    {loading || !data ? <LoadState loading={loading} error={error} retry={() => setReload(x => x + 1)} /> : <>
      <header className="aw-run-header"><div className="aw-heading"><div className="aw-chips"><span className={`aw-chip aw-${data.run.phase}`}>{data.run.carrier === 'h5' ? 'H5' : 'App'} · {data.run.phase === 'pre' ? '上线前' : '上线后'}</span><Link className="aw-chip" to={`/specs/${data.version.spec_id}?version=${data.version.id}`}>规范 {data.version.label} · {data.version.enabled_rules} 项启用</Link><span className="aw-chip">{data.run.project_id ? data.projectName : '独立审核'}</span><DemoBadge source={data.run.source_ref_json} /></div>{hasRole('operator') && <div className="aw-actions"><button className="aw-quiet" type="button" onClick={() => { setFormError(false); setDialog('rename'); }}>重命名</button><button className="aw-quiet aw-danger" type="button" onClick={() => { setFormError(false); setDialog('delete'); }}>删除</button></div>}</div>
        <h1>{data.run.name}</h1><p className="aw-summary">本次共 {data.run.composition.total} 个对象，{data.run.composition.outcomes.capture_failed} 个采集失败；可审核的 {data.run.composition.total - data.run.composition.outcomes.capture_failed} 个对象中，{data.run.composition.outcomes.issues} 个有不符合，{data.run.composition.outcomes.needs_confirmation} 个待确认，{data.run.composition.outcomes.partial} 个部分审核且可检项均符合，{data.run.composition.outcomes.clean} 个全部符合。其中 {data.run.triage.focus.length} 个对象至少有 3 项不符合，{data.run.triage.batches.reduce((sum, batch) => sum + batch.count, 0)} 个只差一项，可按规则批量处理。</p><time className="aw-muted" dateTime={data.run.created_at}>{auditTime(data.run.created_at)}</time>
      </header>
      <section className="aw-panel" aria-labelledby="composition-title"><div className="aw-heading"><h2 id="composition-title">结果构成 · {data.run.composition.total} 个对象</h2><span className="aw-muted">点击分段筛选全页 · 当前：{outcome ? outcomeLabels[outcome] : '全部'}{outcome && <button type="button" className="aw-quiet" onClick={() => change({ outcome: '', page: '1' })}>清除筛选</button>}</span></div>
        <CompositionBar composition={data.run.composition} selected={outcome} onSelect={next => change({ outcome: outcome === next ? '' : next, page: '1' })} />
        {data.run.composition.outcomes.capture_failed > 0 && <div className="aw-capture-reasons"><span>采集失败原因：</span>{Object.entries(data.run.composition.capture_reasons).map(([reason, count]) => <span key={reason}>{captureLabels[reason as keyof typeof captureLabels]} <strong>{count}</strong></span>)}<span className="aw-warning">这些不是设计问题：重新采集或移出批次</span></div>}
      </section>
      <div className="aw-cockpit-pair"><AuditWaffle run={data.run} captures={data.captures} selected={outcome} />{filterLoading || filterError || !view ? <div className="aw-panel"><LoadState loading={filterLoading} error={filterError} retry={() => setReload(x => x + 1)} /></div> : <AuditParetoChart run={view} />}</div>
      {view && !filterLoading && !filterError && <><AuditBarcode run={view} version={data.version} /><AuditTriage run={view} version={data.version} selected={outcome} /></>}
      <TargetTable runId={runId} outcome={outcome} page={page} search={search} sort={sort} change={change} />
    </>}
    {dialog && data && <AuditDialog title={dialog === 'delete' ? '删除审核' : '重命名审核'} onClose={() => setDialog(null)}><form className="aw-form" onSubmit={mutate}>
      {dialog === 'delete' ? <p>确认删除「{data.run.name}」？本次审核的 {data.run.composition.total} 个对象及其结果将一并删除，此操作无法撤销。</p> : <label>审核名称<input name="name" defaultValue={data.run.name} required pattern=".*\S.*" maxLength={200} /></label>}
      {formError && <p role="alert">操作失败，请重试。</p>}<div className="aw-actions"><button type="button" className="aw-secondary" onClick={() => setDialog(null)}>取消</button><button className={dialog === 'delete' ? 'aw-danger-confirm' : ''} disabled={busy}>{busy ? '处理中…' : dialog === 'delete' ? '确认删除' : '确认重命名'}</button></div>
    </form></AuditDialog>}
  </div>;
}
