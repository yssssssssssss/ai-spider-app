import { FormEvent, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AuditProjectListItem, createAuditProject, listAuditProjects } from '../api';
import { useAuth } from '../auth';
import { AuditDialog, auditTime } from '../components/AuditUI';
import { useToast } from '../components/Toast';

export default function AuditProjects() {
  const { hasRole } = useAuth();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const [projects, setProjects] = useState<AuditProjectListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [reload, setReload] = useState(0);
  const [creating, setCreating] = useState(false);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');

  useEffect(() => {
    let active = true;
    setLoading(true);
    setFailed(false);
    listAuditProjects().then(({ data }) => { if (active) setProjects(data); })
      .catch(() => { if (active) setFailed(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reload]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      const { data } = await createAuditProject({ name: name.trim(), description: description.trim() || null });
      showToast('项目已创建', 'success');
      navigate(`/audit-projects/${data.id}`);
    } catch { /* API 拦截器提示错误 */ }
    finally { setBusy(false); }
  };

  return (
    <div className="audit-page">
      <div className="page-header watch-header">
        <div><h1>项目走查</h1><p>按项目收录上线前后记录，跟踪页面问题与变化</p></div>
        <div className="watch-header-actions">
          <button type="button" className="btn-secondary btn-sm" disabled={loading} onClick={() => setReload(value => value + 1)}>刷新</button>
          {hasRole('operator') && <button type="button" className="btn-sm" onClick={() => { setName(''); setDescription(''); setCreating(true); }}>新建项目</button>}
        </div>
      </div>
      <div className="table-shell audit-table-scroll" tabIndex={0} role="region" aria-label="项目列表" aria-busy={loading}>
        <table>
          <thead><tr><th scope="col">项目名称</th><th scope="col">页面数</th><th scope="col">上线前记录</th><th scope="col">上线后记录</th><th scope="col">更新时间</th></tr></thead>
          <tbody>
            {projects.map(project => <tr key={project.id}>
              <td><Link to={`/audit-projects/${project.id}`}>{project.name}</Link></td>
              <td>{project.page_count}</td><td>{project.record_counts.pre || 0}</td><td>{project.record_counts.post || 0}</td>
              <td><time dateTime={project.updated_at}>{auditTime(project.updated_at)}</time></td>
            </tr>)}
            {!projects.length && <tr><td colSpan={5} className="empty-state">{loading ? '加载中…' : failed ? '加载失败，请刷新重试' : '暂无项目'}</td></tr>}
          </tbody>
        </table>
      </div>
      {failed && projects.length > 0 && <p role="alert">刷新失败，当前显示上次加载的数据</p>}
      {creating && <AuditDialog title="新建项目" onClose={() => setCreating(false)}>
        <form className="audit-form" onSubmit={create}>
          <label>项目名称<input required value={name} onChange={event => setName(event.target.value)} /></label>
          <label>项目描述（可选）<textarea value={description} onChange={event => setDescription(event.target.value)} /></label>
          <button disabled={busy || !name.trim()}>{busy ? '创建中…' : '创建项目'}</button>
        </form>
      </AuditDialog>}
    </div>
  );
}
