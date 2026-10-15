import { FormEvent, useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { AuditCarrierScope, AuditSpec, AuditVersionDetail, getAuditSpec, getAuditSpecVersion, importAuditSpecVersion } from '../api';
import { useAuth } from '../auth';
import { AuditDialog, auditTime, LoadState, versionChipLabel } from '../components/AuditWorkspaceUI';

const strengthLabels = { mandatory: '强制', conditional: '条件强制', recommended: '建议' };
export default function AuditSpecDetail() {
  const { specId = '' } = useParams();
  const [params, setParams] = useSearchParams();
  const selectedId = params.get('version');
  const { hasRole } = useAuth();
  const [spec, setSpec] = useState<AuditSpec | null>(null);
  const [version, setVersion] = useState<AuditVersionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [versionLoading, setVersionLoading] = useState(false);
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);
  const [importing, setImporting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState(false);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(false); setSpec(null);
    getAuditSpec(specId).then(({ data }) => { if (active) setSpec(data); }).catch(() => { if (active) setError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [specId, reload]);
  const versionId = spec?.versions.find(v => v.id === selectedId)?.id || spec?.latest_version?.id;
  useEffect(() => {
    let active = true;
    setVersion(null);
    if (!versionId) return;
    setVersionLoading(true); setError(false);
    getAuditSpecVersion(versionId).then(({ data }) => { if (active) setVersion(data); }).catch(() => { if (active) setError(true); }).finally(() => { if (active) setVersionLoading(false); });
    return () => { active = false; };
  }, [versionId, reload]);
  async function importVersion(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    setBusy(true); setFormError(false);
    try {
      const result = await importAuditSpecVersion(specId, data.get('file') as File, data.get('carrier_scope') as AuditCarrierScope);
      setParams({ version: result.data.id }); setImporting(false); setReload(x => x + 1);
    } catch { setFormError(true); } finally { setBusy(false); }
  }
  return <div className="aw">
    <nav className="aw-breadcrumb" aria-label="面包屑"><Link to="/specs">规范库</Link><span>/</span><span>{spec?.name || '规范详情'}</span></nav>
    {loading || !spec ? <LoadState loading={loading} error={error} retry={() => setReload(x => x + 1)} /> : <>
      <header className="aw-heading"><div><div className="aw-eyebrow">{spec.key}</div><h1>{spec.name}</h1><p>{spec.description || '选择一个版本查看规则。已发布版本不可修改。'}</p></div>{hasRole('operator') && <button type="button" onClick={() => { setFormError(false); setImporting(true); }}>导入新版本</button>}</header>
      <section className="aw-panel"><div className="aw-heading"><h2>版本时间线</h2><span className="aw-muted">发布即不可变 · 共 {spec.versions.length} 个版本</span></div><div className="aw-versions" role="group" aria-label="选择规范版本">{[...spec.versions].reverse().map(v => <button type="button" key={v.id} className={`aw-version ${v.id === versionId ? 'is-selected' : ''}`} aria-pressed={v.id === versionId} onClick={() => setParams({ version: v.id })}><strong>{versionChipLabel(v.label)}</strong>{versionChipLabel(v.label) !== v.label && <span>{v.label}</span>}<small>{v.enabled_rules} 条启用 · {v.run_count} 次引用</small></button>)}</div>{!spec.versions.length && <p>暂无版本，请导入规范 JSON。</p>}</section>
      {versionLoading ? <LoadState loading /> : version ? <section className="aw-panel">
        <div className="aw-heading"><div><h2>{version.label} <span className="aw-chip">{version.carrier_scope === 'both' ? 'H5 / App' : version.carrier_scope === 'h5' ? 'H5' : 'App'}</span></h2><p>启用 {version.enabled_rules} / {version.rules_json.length} 条 · 被 {version.run_count} 次审核引用</p></div><time className="aw-muted" dateTime={version.created_at}>{auditTime(version.created_at)}</time></div>
        <div className="aw-scroll" tabIndex={0} role="region" aria-label="规范规则表"><table className="aw-rule-table"><thead><tr>{['ID', '标题', '条款', '强度', '载体', '启用', '测量方式', '共享证据'].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{version.rules_json.map(rule => <tr key={rule.rule_id} className={!rule.enabled ? 'aw-rule-disabled' : ''}>
          <td className="aw-mono">{rule.rule_id}</td><td title={rule.expected}>{rule.title}</td><td>{rule.clause || '—'}</td><td>{strengthLabels[rule.strength]}</td><td>{rule.carriers.map(c => c === 'h5' ? 'H5' : 'App').join(' / ') || '无'}</td><td>{rule.enabled ? '✓ 启用' : '− 未启用'}</td><td>{rule.method || '未指定'}</td><td>{rule.duplicate_of ? `与 ${rule.duplicate_of} 共享证据，不重复计数` : '—'}</td>
        </tr>)}</tbody></table></div>
      </section> : error ? <LoadState error retry={() => setReload(x => x + 1)} /> : null}
    </>}
    {importing && <AuditDialog title="导入新版本" onClose={() => setImporting(false)}><form className="aw-form" onSubmit={importVersion}>
      <p>支持官方会场与公共规范 JSON。相同文件会返回已有版本。</p><label>规范 JSON 文件<input type="file" name="file" accept=".json,application/json" required /></label><label>适用载体<select name="carrier_scope" defaultValue="h5"><option value="h5">H5</option><option value="app">App</option><option value="both">H5 / App</option></select></label>
      {formError && <p role="alert">导入失败，请检查 JSON 格式与载体后重试。</p>}<button disabled={busy}>{busy ? '导入中…' : '导入版本'}</button>
    </form></AuditDialog>}
  </div>;
}
