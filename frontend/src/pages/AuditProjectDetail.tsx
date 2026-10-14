import { FormEvent, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  AuditH5ImportResult, AuditProjectDetail as ProjectDetail, createAuditPage, deleteAuditProject,
  getAuditProject, importAuditH5, updateAuditProject,
} from '../api';
import { useAuth } from '../auth';
import { AuditDialog, AuditSummary, auditCategories } from '../components/AuditUI';
import { useToast } from '../components/Toast';

type Dialog = 'edit' | 'import' | 'page' | null;

export default function AuditProjectDetail() {
  const { projectId = '' } = useParams();
  const navigate = useNavigate();
  const { hasRole } = useAuth();
  const { showToast } = useToast();
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [reload, setReload] = useState(0);
  const [search, setSearch] = useState('');
  const [regressed, setRegressed] = useState(false);
  const [noBaseline, setNoBaseline] = useState(false);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [businessKey, setBusinessKey] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [venueIds, setVenueIds] = useState('');
  const [importResult, setImportResult] = useState<AuditH5ImportResult | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setFailed(false);
    getAuditProject(projectId).then(({ data }) => { if (active) setProject(data); })
      .catch(() => { if (active) setFailed(true); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [projectId, reload]);

  const remove = async () => {
    if (!project || !window.confirm(`删除项目“${project.name}”？该项目的全部页面和记录也会删除。`)) return;
    setBusy(true);
    try {
      await deleteAuditProject(projectId);
      showToast('项目已删除', 'success');
      navigate('/audit-projects');
    } catch { /* API 拦截器提示错误 */ }
    finally { setBusy(false); }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      if (dialog === 'edit') {
        await updateAuditProject(projectId, { name: name.trim(), description: description.trim() || null });
        showToast('项目已更新', 'success');
        setDialog(null);
      } else if (dialog === 'page') {
        const { data } = await createAuditPage(projectId, { name: name.trim(), business_key: businessKey.trim() || null });
        showToast('页面已创建', 'success');
        navigate(`/audit-pages/${data.id}`);
      } else if (dialog === 'import' && file) {
        const { data } = await importAuditH5(projectId, file, venueIds);
        setImportResult(data);
        showToast('H5 结果导入完成', 'success');
      }
      setReload(value => value + 1);
    } catch { /* API 拦截器提示错误 */ }
    finally { setBusy(false); }
  };

  if (!project || project.id !== projectId) return <div className="empty-state">
    <p>{loading ? '加载中…' : '无法加载项目'}</p>
    {!loading && <button type="button" onClick={() => setReload(value => value + 1)}>重试</button>}
    <Link to="/audit-projects">返回项目列表</Link>
  </div>;

  const query = search.trim().toLocaleLowerCase();
  const pages = project.pages.filter(page => (
    (!query || page.name.toLocaleLowerCase().includes(query) || page.business_key?.toLocaleLowerCase().includes(query))
    && (!regressed || (page.compare_counts?.regressed || 0) > 0)
    && (!noBaseline || (page.latest_post !== null && !page.has_baseline))
  ));
  const canWrite = hasRole('operator');

  return (
    <div className="audit-page">
      <div className="page-header watch-header">
        <div><Link to="/audit-projects">项目走查</Link><h1>{project.name}</h1><p>{project.description || '暂无项目描述'}</p></div>
        {canWrite && <div className="watch-header-actions">
          <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={() => { setName(project.name); setDescription(project.description || ''); setDialog('edit'); }}>编辑项目</button>
          <button type="button" className="btn-secondary btn-sm audit-delete" disabled={busy} onClick={remove}>删除项目</button>
          <button type="button" className="btn-secondary btn-sm" disabled={busy} onClick={() => { setName(''); setBusinessKey(''); setDialog('page'); }}>新建页面</button>
          <button type="button" className="btn-sm" disabled={busy} onClick={() => { setFile(null); setVenueIds(''); setImportResult(null); setDialog('import'); }}>导入 H5 结果</button>
        </div>}
      </div>
      <div className="audit-actions">
        <label>搜索页面或会场 ID<input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="页面名称 / 会场 ID" /></label>
        <label><input type="checkbox" checked={regressed} onChange={event => setRegressed(event.target.checked)} /> 有回归</label>
        <label><input type="checkbox" checked={noBaseline} onChange={event => setNoBaseline(event.target.checked)} /> 未设基线</label>
        <button type="button" className="btn-secondary btn-sm" disabled={loading} onClick={() => setReload(value => value + 1)}>刷新</button>
      </div>
      {failed && <p role="alert">刷新失败，当前显示上次加载的数据</p>}
      <div className="table-shell audit-table-scroll" tabIndex={0} role="region" aria-label="页面走查矩阵" aria-busy={loading}>
        <table>
          <thead><tr><th scope="col">页面名称</th><th scope="col">会场ID</th><th scope="col">上线前</th><th scope="col">上线后</th><th scope="col">比对</th></tr></thead>
          <tbody>
            {pages.map(page => <tr key={page.id} onClick={event => {
              if (!(event.target as HTMLElement).closest('a, button')) navigate(`/audit-pages/${page.id}`);
            }}>
              <td><Link to={`/audit-pages/${page.id}`}>{page.name}</Link></td>
              <td>{page.business_key || '—'}</td>
              <td>{page.latest_pre ? <AuditSummary compact counts={page.latest_pre.summary_json} /> : '—'}</td>
              <td>{page.latest_post ? <AuditSummary compact counts={page.latest_post.summary_json} /> : '—'}</td>
              <td>{page.latest_post && !page.has_baseline ? '未设基线' : page.compare_counts ? (
                <div className="audit-actions">{auditCategories.filter(category => ['regressed', 'still_open', 'new_issue', 'fixed'].includes(category.key) && (page.compare_counts?.[category.key] || 0) > 0)
                  .map(category => <span key={category.key}>{category.label} {page.compare_counts![category.key]}</span>)}
                  {!['regressed', 'still_open', 'new_issue', 'fixed'].some(key => (page.compare_counts?.[key] || 0) > 0) && '—'}
                </div>
              ) : '—'}</td>
            </tr>)}
            {pages.length === 0 && <tr><td colSpan={5} className="empty-state">{project.pages.length ? '没有符合条件的页面' : '暂无页面，可导入 H5 结果或新建页面'}</td></tr>}
          </tbody>
        </table>
      </div>
      {dialog && <AuditDialog title={dialog === 'edit' ? '编辑项目' : dialog === 'page' ? '新建页面' : '导入 H5 结果'} onClose={() => setDialog(null)}>
        <form className="audit-form" onSubmit={submit}>
          {dialog === 'import' ? <>
            <label>H5 results.json<input type="file" accept=".json,application/json" required disabled={busy} onChange={event => { setFile(event.target.files?.[0] || null); setImportResult(null); }} /></label>
            <label>会场ID（可选，逗号或换行分隔）<textarea value={venueIds} disabled={busy} onChange={event => { setVenueIds(event.target.value); setImportResult(null); }} placeholder="留空导入全部会场" /></label>
            {importResult && <p role="status">新增记录 {importResult.created} · 跳过记录 {importResult.skipped} · 新建页面 {importResult.pages_created}</p>}
          </> : <>
            <label>{dialog === 'edit' ? '项目名称' : '页面名称'}<input required value={name} onChange={event => setName(event.target.value)} /></label>
            {dialog === 'edit'
              ? <label>项目描述（可选）<textarea value={description} onChange={event => setDescription(event.target.value)} /></label>
              : <label>会场 ID（可选）<input value={businessKey} onChange={event => setBusinessKey(event.target.value)} /></label>}
          </>}
          <button disabled={busy || (dialog === 'import' ? !file || !!importResult : !name.trim())}>{busy ? '处理中…' : dialog === 'import' ? '导入' : '保存'}</button>
        </form>
      </AuditDialog>}
    </div>
  );
}
