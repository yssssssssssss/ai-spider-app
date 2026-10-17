import { FormEvent, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AuditProjectListItem, createAuditProject, listAuditProjects } from '../api';
import { useAuth } from '../auth';
import { AuditDialog, auditTime, LoadState } from '../components/AuditWorkspaceUI';
import { StageBar } from '../components/AuditProjectUI';

export default function AuditProjects() {
  const { hasRole } = useAuth();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<AuditProjectListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState(false);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(false);
    listAuditProjects().then(({ data }) => { if (active) setProjects(data); }).catch(() => { if (active) setError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reload]);
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    setBusy(true); setFormError(false);
    try {
      const { data } = await createAuditProject({ name: String(fields.get('name')).trim(), description: String(fields.get('description')).trim() || null });
      navigate(`/audit-projects/${data.id}`);
    } catch { setFormError(true); } finally { setBusy(false); }
  }
  return <div className="aw ap-projects-page"><header className="aw-heading"><div><div className="aw-eyebrow">审核工作台 / 项目</div><h1>项目走查</h1><p>把同一项目的审核串起来，查看页面从上线前到上线后的变化。</p></div>{hasRole('operator') && <button type="button" onClick={() => { setFormError(false); setCreating(true); }}>新建项目</button>}</header>
    {loading || error ? <LoadState loading={loading} error={error} retry={() => setReload(value => value + 1)} /> : projects.length ? <section className="ap-project-list" aria-label="项目列表">{projects.map(project => <article key={project.id} className="aw-panel ap-project-row"><div><h2><Link to={`/audit-projects/${project.id}`}>{project.name}</Link></h2><p className="ap-project-description" title={project.description || undefined}>{project.description}</p><time className="aw-muted" dateTime={project.updated_at}>最近更新 · {auditTime(project.updated_at)}</time></div><div className="ap-project-counts"><div><span>页面</span><strong>{project.page_count}</strong></div><div><span>次审核</span><strong>{project.run_count}</strong></div></div><StageBar project={project} /><Link to={`/audit-projects/${project.id}`} className="ap-open-link" aria-label={`查看项目 ${project.name}`}>查看项目 →</Link></article>)}</section> : <div className="aw-panel aw-empty">暂无项目。创建项目后，可在审核驾驶舱中将审核归入项目。</div>}
    {creating && <AuditDialog title="新建项目" onClose={() => setCreating(false)}><form className="aw-form" onSubmit={create}><label>项目名称<input name="name" required pattern=".*\S.*" maxLength={200} /></label><label>说明<textarea name="description" rows={3} /></label>{formError && <p role="alert">创建失败，请检查名称后重试。</p>}<div className="aw-actions"><button type="button" className="aw-secondary" onClick={() => setCreating(false)}>取消</button><button disabled={busy}>{busy ? '创建中…' : '创建项目'}</button></div></form></AuditDialog>}
  </div>;
}
