import { FormEvent, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  AuditAppCandidate, AuditComparison, AuditPageDetail as PageDetail, AuditPhase, AuditRecord,
  addAuditAppRecord, compareAuditRecords, deleteAuditRecord, getAuditPage, listAuditAppCandidates, updateAuditRecord,
} from '../api';
import { useAuth } from '../auth';
import { AuditDialog, AuditStatusBadge, AuditSummary, auditCategories, auditTime } from '../components/AuditUI';
import { useToast } from '../components/Toast';

function recordLabel(record: AuditRecord) {
  return `${auditTime(record.created_at)} · ${record.spec_key} v${record.spec_version}`;
}

function Comparison({ comparison }: { comparison: AuditComparison }) {
  return <>
    {comparison.spec_mismatch && <p className="watch-warning" role="note">两条记录使用的规范版本不同，仅比对共同规则</p>}
    {auditCategories.map(({ key, label }) => {
      const rules = comparison.rules.filter(rule => rule.category === key);
      return <details className="audit-group" key={key} open={key === 'regressed' || key === 'still_open'}>
        <summary>{label} · {comparison.counts[key] || 0}</summary>
        {rules.length === 0 ? <p>暂无规则</p> : rules.map(rule => <details className="audit-rule" key={rule.rule_id}>
          <summary>
            <strong>{rule.rule_id}</strong> {rule.title}{' '}
            <span className="audit-actions"><AuditStatusBadge status={rule.pre_status} /><span aria-label="变为">→</span><AuditStatusBadge status={rule.post_status} /></span>
          </summary>
          <div className="audit-observed">
            <div><h4>上线前观察</h4><p>{rule.pre_observed || '暂无观察文本'}</p></div>
            <div><h4>上线后观察</h4><p>{rule.post_observed || '暂无观察文本'}</p></div>
          </div>
        </details>)}
      </details>;
    })}
  </>;
}

function AppRecordDialog({ pageId, preRecords, onClose, onAdded }: {
  pageId: string; preRecords: AuditRecord[]; onClose: () => void; onAdded: () => void;
}) {
  const [candidates, setCandidates] = useState<AuditAppCandidate[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [reload, setReload] = useState(0);
  const [runId, setRunId] = useState('');
  const [skillId, setSkillId] = useState('');
  const [phase, setPhase] = useState<AuditPhase>('post');
  const [baselineId, setBaselineId] = useState('');
  const [busy, setBusy] = useState(false);
  const { showToast } = useToast();
  const run = candidates.find(candidate => candidate.task_run_id === runId);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setFailed(false);
    listAuditAppCandidates().then(({ data }) => {
      if (!active) return;
      setCandidates(data);
      setRunId(data[0]?.task_run_id || '');
      setSkillId(data[0]?.skills[0]?.id || '');
    }).catch(() => { if (active) setFailed(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reload]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      await addAuditAppRecord(pageId, { task_run_id: runId, skill_id: skillId, phase, baseline_record_id: phase === 'post' ? baselineId || null : null });
      showToast('App 结果已收录', 'success');
      onAdded();
    } catch { /* API 拦截器提示错误 */ }
    finally { setBusy(false); }
  };

  return <AuditDialog title="收录 App 结果" onClose={onClose}>
    {loading ? <p role="status">加载可收录的运行…</p> : failed ? <>
      <p>加载失败</p><button type="button" onClick={() => setReload(value => value + 1)}>重试</button>
    </> : !candidates.length ? <p>暂无已完成且包含规范巡查结果的运行</p> : <form className="audit-form" onSubmit={submit}>
      <p>所选运行中，该 Skill 的全部图片检查项将合并为一条记录。</p>
      <label>已完成运行<select value={runId} disabled={busy} required onChange={event => {
        setRunId(event.target.value);
        setSkillId(candidates.find(candidate => candidate.task_run_id === event.target.value)?.skills[0]?.id || '');
      }}>
        {candidates.map(candidate => <option key={candidate.task_run_id} value={candidate.task_run_id}>{candidate.task_name || '未命名任务'} · {auditTime(candidate.completed_at)} · {candidate.task_run_id.slice(0, 8)}</option>)}
      </select></label>
      <label>规范 Skill<select value={skillId} disabled={busy} required onChange={event => setSkillId(event.target.value)}>
        {run?.skills.map(skill => <option key={skill.id} value={skill.id}>{skill.name} v{skill.version}</option>)}
      </select></label>
      <label>检查阶段<select value={phase} disabled={busy} onChange={event => { setPhase(event.target.value as AuditPhase); setBaselineId(''); }}>
        <option value="post">上线后</option><option value="pre">上线前</option>
      </select></label>
      {phase === 'post' && <label>上线前基线（可选）<select value={baselineId} disabled={busy} onChange={event => setBaselineId(event.target.value)}>
        <option value="">不关联基线</option>
        {preRecords.map(record => <option key={record.id} value={record.id}>{recordLabel(record)}</option>)}
      </select></label>}
      <button disabled={busy || !runId || !skillId}>{busy ? '收录中…' : '收录'}</button>
    </form>}
  </AuditDialog>;
}

export default function AuditPageDetail() {
  const { pageId = '' } = useParams();
  const { hasRole } = useAuth();
  const { showToast } = useToast();
  const [page, setPage] = useState<PageDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(false);
  const [appDialog, setAppDialog] = useState(false);
  const [postId, setPostId] = useState('');
  const [preId, setPreId] = useState('');
  const [customComparison, setCustomComparison] = useState<AuditComparison | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setFailed(false);
    getAuditPage(pageId).then(({ data }) => {
      if (!active) return;
      setPage(data);
      const latestPost = data.records.filter(record => record.phase === 'post').slice(-1)[0];
      setPostId(latestPost?.id || '');
      setPreId(latestPost?.baseline_record_id || '');
      setCustomComparison(null);
    }).catch(() => { if (active) setFailed(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [pageId, reload]);

  const setBaseline = async (recordId: string, baselineId: string) => {
    setBusy(true);
    try {
      await updateAuditRecord(recordId, { baseline_record_id: baselineId || null });
      showToast('基线已更新', 'success');
      setReload(value => value + 1);
    } catch { /* API 拦截器提示错误 */ }
    finally { setBusy(false); }
  };

  const remove = async (record: AuditRecord) => {
    if (!window.confirm(`删除 ${recordLabel(record)}？${record.phase === 'pre' ? '引用它的上线后记录将清除基线。' : ''}`)) return;
    setBusy(true);
    try {
      await deleteAuditRecord(record.id);
      showToast('记录已删除', 'success');
      setReload(value => value + 1);
    } catch { /* API 拦截器提示错误 */ }
    finally { setBusy(false); }
  };

  const compare = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      const { data } = await compareAuditRecords(postId, preId);
      setCustomComparison(data);
    } catch { /* API 拦截器提示错误 */ }
    finally { setBusy(false); }
  };

  if (!page || page.id !== pageId) return <div className="empty-state">
    <p>{loading ? '加载中…' : '无法加载页面'}</p>
    {!loading && <button type="button" onClick={() => setReload(value => value + 1)}>重试</button>}
    <Link to="/audit-projects">返回项目列表</Link>
  </div>;

  const preRecords = page.records.filter(record => record.phase === 'pre');
  const postRecords = page.records.filter(record => record.phase === 'post');
  const latestPost = postRecords[postRecords.length - 1];
  const comparison = customComparison || (postId === latestPost?.id && preId === latestPost?.baseline_record_id ? page.comparison : null);
  const recordsById = new Map(page.records.map(record => [record.id, record]));
  const canWrite = hasRole('operator');

  return <div className="audit-page">
    <div className="page-header watch-header">
      <div><Link to={`/audit-projects/${page.project_id}`}>返回所属项目</Link><h1>{page.name}</h1><p>会场 ID：{page.business_key || '未设置'}</p></div>
      <div className="watch-header-actions">
        <button type="button" className="btn-secondary btn-sm" disabled={loading || busy} onClick={() => setReload(value => value + 1)}>刷新</button>
        {canWrite && <button type="button" className="btn-sm" disabled={busy || loading} onClick={() => setAppDialog(true)}>收录 App 结果</button>}
      </div>
    </div>
    {failed && <p role="alert">刷新失败，当前显示上次加载的数据</p>}
    <section aria-labelledby="audit-timeline-title" aria-busy={loading}>
      <div className="section-title-row"><h2 id="audit-timeline-title">记录时间线</h2></div>
      {page.records.length === 0 ? <p className="empty-state">暂无记录</p> : <ol className="audit-timeline">
        {page.records.map(record => {
          const baseline = record.baseline_record_id ? recordsById.get(record.baseline_record_id) : undefined;
          const source = record.source_ref_json;
          return <li className="watch-meta-panel" key={record.id}>
            <div className="section-title-row">
              <h3>{record.phase === 'pre' ? '上线前' : '上线后'} · {record.carrier === 'h5' ? 'H5' : 'App'}</h3>
              {canWrite && <button type="button" className="btn-secondary btn-sm audit-delete" disabled={busy || loading} onClick={() => remove(record)}>删除记录</button>}
            </div>
            <p>{record.spec_key} v{record.spec_version} · <time dateTime={record.created_at}>{auditTime(record.created_at)}</time></p>
            <AuditSummary counts={record.summary_json} />
            <p>来源：{record.source_kind === 'h5_import' ? String(source.file_name || 'H5 文件') : <>
              任务运行 <code>{String(source.task_run_id || '')}</code>
            </>}</p>
            {record.note && <p>备注：{record.note}</p>}
            {record.phase === 'post' && <>
              <p>{baseline ? `基线：${recordLabel(baseline)}` : '未关联上线前记录，本轮为独立检查'}</p>
              {canWrite && <label>更改基线<select aria-label={`更改 ${recordLabel(record)} 的基线`} value={record.baseline_record_id || ''} disabled={busy || loading} onChange={event => setBaseline(record.id, event.target.value)}>
                <option value="">清除基线（独立检查）</option>
                {preRecords.map(pre => <option key={pre.id} value={pre.id}>{recordLabel(pre)}</option>)}
              </select></label>}
            </>}
          </li>;
        })}
      </ol>}
    </section>
    <section className="watch-section" aria-labelledby="audit-comparison-title">
      <div className="section-title-row"><h2 id="audit-comparison-title">规则比对</h2></div>
      <form className="audit-actions" onSubmit={compare}>
        <label>上线后记录<select value={postId} disabled={busy || loading} required onChange={event => { setPostId(event.target.value); setCustomComparison(null); }}>
          <option value="">选择上线后记录</option>
          {postRecords.map(record => <option key={record.id} value={record.id}>{recordLabel(record)}</option>)}
        </select></label>
        <label>上线前记录<select value={preId} disabled={busy || loading} required onChange={event => { setPreId(event.target.value); setCustomComparison(null); }}>
          <option value="">选择上线前记录</option>
          {preRecords.map(record => <option key={record.id} value={record.id}>{recordLabel(record)}</option>)}
        </select></label>
        <button className="btn-sm" disabled={busy || loading || !postId || !preId}>{busy ? '处理中…' : '比对'}</button>
      </form>
      <p>默认展示最新上线后记录与其基线；手动选择仅用于本次比对，不修改基线。</p>
      {comparison ? <Comparison key={`${postId}:${preId}`} comparison={comparison} /> : <p className="empty-state">
        {!latestPost ? '暂无上线后记录' : !latestPost.baseline_record_id && !preId ? '未关联上线前记录，本轮为独立检查' : '选择同一页面的两条记录后点击“比对”'}
      </p>}
    </section>
    {appDialog && canWrite && <AppRecordDialog pageId={pageId} preRecords={preRecords} onClose={() => setAppDialog(false)} onAdded={() => { setAppDialog(false); setReload(value => value + 1); }} />}
  </div>;
}
