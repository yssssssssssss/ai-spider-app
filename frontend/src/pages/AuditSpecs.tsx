import { FormEvent, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AuditSpec, AuditVersionDetail, createAuditSpec, getAuditSpecVersion, listAuditSpecs } from '../api';
import { useAuth } from '../auth';
import { AuditDialog, LoadState, versionChipLabel } from '../components/AuditWorkspaceUI';

export default function AuditSpecs() {
  const { hasRole } = useAuth();
  const navigate = useNavigate();
  const [specs, setSpecs] = useState<AuditSpec[]>([]);
  const [versions, setVersions] = useState<Record<string, AuditVersionDetail>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState(false);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(false);
    (async () => {
      const { data } = await listAuditSpecs();
      const details = await Promise.all(data.flatMap(spec => spec.latest_version ? [getAuditSpecVersion(spec.latest_version.id)] : []));
      if (active) { setSpecs(data); setVersions(Object.fromEntries(details.map(({ data: version }) => [version.id, version]))); }
    })().catch(() => { if (active) setError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reload]);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true); setFormError(false);
    try {
      const { data } = await createAuditSpec({ key: String(form.get('key')).trim(), name: String(form.get('name')).trim(), description: String(form.get('description')).trim() || null });
      navigate(`/specs/${data.id}`);
    } catch { setFormError(true); } finally { setBusy(false); }
  }
  return <div className="aw">
    <header className="aw-heading"><div><div className="aw-eyebrow">审核工作台 / 规范库</div><h1>规范库</h1><p>独立管理规范与版本，每次审核固定使用一个版本。</p></div>{hasRole('operator') && <button type="button" onClick={() => { setFormError(false); setCreating(true); }}>新建规范</button>}</header>
    {loading || error ? <LoadState loading={loading} error={error} retry={() => setReload(x => x + 1)} /> : specs.length ? <div className="aw-spec-grid">{specs.map(spec => {
      const latest = spec.latest_version;
      return <article className="aw-panel aw-spec-card" key={spec.id}>
        <div className="aw-heading"><h2><Link to={`/specs/${spec.id}`}>{spec.name}</Link></h2><span className={`aw-chip aw-carrier-${latest?.carrier_scope}`}>{latest ? latest.carrier_scope === 'both' ? 'H5 / App' : latest.carrier_scope === 'h5' ? 'H5' : 'App' : '待导入'}</span></div>
        <p>{spec.description || spec.key}</p>
        {latest ? <><div className="aw-spec-stats"><span>当前版本 <strong>{latest.label}</strong></span><span>启用 <strong>{latest.enabled_rules} / {versions[latest.id].rules_json.length}</strong> 条规则</span></div><div className="aw-chips">{[...spec.versions].reverse().map(version => <Link className={`aw-version ${version.id === latest.id ? 'is-selected' : ''}`} key={version.id} to={`/specs/${spec.id}?version=${version.id}`} title={version.label}>{versionChipLabel(version.label)}</Link>)}</div></> : <p>尚无版本，打开规范后导入 JSON。</p>}
        <div className="aw-heading aw-spec-footer"><span className="aw-muted">被 {spec.versions.reduce((sum, version) => sum + version.run_count, 0)} 次审核引用</span><Link to={`/specs/${spec.id}`}>查看规范 →</Link></div>
      </article>;
    })}</div> : <LoadState />}
    {creating && <AuditDialog title="新建规范" onClose={() => setCreating(false)}><form className="aw-form" onSubmit={create}>
      <label>规范名称<input name="name" required maxLength={200} pattern=".*\S.*" /></label>
      <label>规范标识<input name="key" required pattern="[a-z0-9]+(-[a-z0-9]+)*" placeholder="official-venue-h5" aria-describedby="spec-key-help" /><small id="spec-key-help">小写字母、数字，以连字符分隔。</small></label>
      <label>描述（可选）<textarea name="description" rows={3} /></label>
      {formError && <p role="alert">创建失败，请检查规范标识是否重复后重试。</p>}
      <button disabled={busy}>{busy ? '创建中…' : '创建规范'}</button>
    </form></AuditDialog>}
  </div>;
}
