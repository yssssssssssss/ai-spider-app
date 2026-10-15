import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { AuditFinding, AuditRunDetail, AuditStatus, AuditTarget, AuditVersionDetail, getAuditRun, getAuditSpecVersion, getAuditTarget } from '../api';
import { captureLabels, DemoBadge, LoadState, OutcomeBadge, statusLabels } from '../components/AuditWorkspaceUI';

export default function AuditTargetDetail() {
  const { id = '' } = useParams();
  const [data, setData] = useState<{ target: AuditTarget; run: AuditRunDetail; version: AuditVersionDetail } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(false); setData(null);
    (async () => {
      const { data: target } = await getAuditTarget(id);
      const { data: run } = await getAuditRun(target.run_id);
      const { data: version } = await getAuditSpecVersion(run.spec_version_id);
      if (active) setData({ target, run, version });
    })().catch(() => { if (active) setError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id, reload]);
  const groups = useMemo(() => {
    if (!data) return [];
    const findings = new Map(data.target.findings_json.map(finding => [finding.rule_id, finding]));
    const rows = data.version.rules_json.map(rule => {
      const finding = findings.get(rule.rule_id);
      const status: AuditStatus = !rule.enabled ? 'disabled' : !rule.carriers.includes(data.run.carrier) ? 'not_applicable' : finding?.status || 'not_applicable';
      return { rule, finding, status, uncovered: !finding && rule.enabled && rule.carriers.includes(data.run.carrier) };
    });
    const known = new Set(rows.map(row => row.rule.rule_id));
    // Preserve source findings even when their ID is absent from the selected specification.
    const extra: AuditFinding[] = data.target.findings_json.filter(finding => !known.has(finding.rule_id));
    return [
      { title: '需要处理', statuses: ['fail'], className: 'aw-text-issues' },
      { title: '待确认', statuses: ['uncertain'], className: 'aw-text-needs_confirmation' },
      { title: '符合', statuses: ['pass'], className: 'aw-text-clean' },
      { title: '不适用 · 未启用', statuses: ['not_applicable', 'disabled'], className: 'aw-muted' },
    ].map(group => ({ ...group, rows: rows.filter(row => group.statuses.includes(row.status)), extra: extra.filter(finding => group.statuses.includes(finding.status)) }));
  }, [data]);
  return <div className="aw">
    <nav className="aw-breadcrumb" aria-label="面包屑"><Link to="/audits">审核</Link><span>/</span>{data && <><Link to={`/audits/${data.run.id}`}>{data.run.name}</Link><span>/</span></>}<span>{data?.target.name || '对象结果'}</span></nav>
    {loading || !data ? <LoadState loading={loading} error={error} retry={() => setReload(x => x + 1)} /> : <>
      <header className="aw-run-header"><div className="aw-chips"><OutcomeBadge outcome={data.target.outcome} /><span className={`aw-chip aw-${data.run.phase}`}>{data.run.carrier === 'h5' ? 'H5' : 'App'} · {data.run.phase === 'pre' ? '上线前' : '上线后'}</span><DemoBadge source={data.run.source_ref_json} /></div><h1>{data.target.name}</h1><p>业务键：<span className="aw-mono">{data.target.business_key || '未设置'}</span></p><div className="aw-chips"><Link to={`/audits/${data.run.id}`}>所属审核：{data.run.name} →</Link><Link to={`/specs/${data.version.spec_id}?version=${data.version.id}`}>规范：{data.version.label} →</Link></div></header>
      {data.target.capture_reason && <aside className="aw-panel aw-capture-notice"><h2>采集失败 · {captureLabels[data.target.capture_reason]}</h2><p>这些不是设计问题。本对象没有形成有效的审核结论。</p>{data.target.summary_json.capture_detail && <details><summary>查看采集原文</summary><pre>{JSON.stringify(data.target.summary_json.capture_detail, null, 2)}</pre></details>}</aside>}
      <div className="aw-target-groups">{groups.map(group => <section className="aw-panel" key={group.title}><div className="aw-heading"><h2 className={group.className}>{group.title}</h2><span className="aw-muted">{group.rows.length + group.extra.length} 条规则</span></div>
        {group.rows.map(({ rule, finding, status, uncovered }) => <details className="aw-finding" key={rule.rule_id}><summary><span className="aw-mono">{rule.rule_id}</span><strong>{rule.title}{rule.duplicate_of && <small className="aw-shared-label">与 {rule.duplicate_of} 共享证据，不重复计数</small>}</strong><span className={`aw-status aw-status-${status}`}>{uncovered ? '未覆盖' : statusLabels[status]}</span></summary>
          <div className="aw-observations"><div><h3>观察</h3><p>{finding?.observed || '暂无观察记录'}</p></div><div><h3>判定原因</h3><p>{finding?.reason || (uncovered ? '本次结果未覆盖该规则。' : status === 'disabled' ? '此版本未启用该规则。' : !rule.carriers.includes(data.run.carrier) ? '该规则不适用于本次审核载体。' : '暂无原因记录')}</p></div></div><div className="aw-rule-context"><span>条款：{rule.clause || '未指定'}</span><p>预期：{rule.expected}</p></div>
        </details>)}
        {group.extra.map(finding => <details className="aw-finding" key={finding.rule_id}><summary><span className="aw-mono">{finding.rule_id}</span><strong>{finding.title}</strong><span>{statusLabels[finding.status]}</span></summary><p className="aw-warning">此规则不在本次规范版本中。</p><div className="aw-observations"><div><h3>观察</h3><p>{finding.observed || '暂无观察记录'}</p></div><div><h3>判定原因</h3><p>{finding.reason || '暂无原因记录'}</p></div></div></details>)}
        {!group.rows.length && !group.extra.length && <p>无此类规则。</p>}
      </section>)}</div>
    </>}
  </div>;
}
