import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  adminDeleteAnalysisSkill,
  adminUpdateAnalysisSkill,
  createAdminAnalysisSkill,
  createAnalysisSkill,
  deleteAnalysisSkill,
  listAdminAnalysisSkills,
  listAnalysisSkills,
  setAnalysisSkillOfficial,
  updateAnalysisSkill,
  uploadAnalysisSkillMd,
} from '../api';
import { useAuth } from '../auth';
import { useToast } from '../components/Toast';

type AnalysisSkill = {
  id: string;
  name: string;
  instruction_md: string;
  owner_id?: string | null;
  owner_name?: string | null;
  is_official: boolean;
  status: string;
};

const emptyForm = { id: '', name: '', instruction_md: '' };

export default function AnalysisSkillsPage() {
  const { hasRole, user } = useAuth();
  const { showToast } = useToast();
  const [skills, setSkills] = useState<AnalysisSkill[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [modalOpen, setModalOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const isAdmin = hasRole('admin');
  const visibleSkills = useMemo(() => (
    isAdmin ? skills : skills.filter(skill => skill.is_official || skill.owner_id === user?.id)
  ), [isAdmin, skills, user?.id]);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = isAdmin ? await listAdminAnalysisSkills() : await listAnalysisSkills();
      setSkills(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [isAdmin]);

  useEffect(() => {
    if (!modalOpen) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !saving) {
        setForm(emptyForm);
        setModalOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [modalOpen, saving]);

  const openCreateModal = () => {
    setForm(emptyForm);
    setModalOpen(true);
  };

  const closeModal = () => {
    if (saving) return;
    setForm(emptyForm);
    setModalOpen(false);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const name = form.name.trim();
    const instruction = form.instruction_md.trim();
    if (!name || !instruction) {
      showToast('名称和分析指令不能为空', 'warning');
      return;
    }
    if (instruction.length > 20000) {
      showToast('分析指令不能超过 20000 字符', 'warning');
      return;
    }
    setSaving(true);
    try {
      if (form.id) {
        const updater = isAdmin ? adminUpdateAnalysisSkill : updateAnalysisSkill;
        await updater(form.id, { name, instruction_md: instruction });
        showToast('分析 skill 已更新', 'success');
      } else {
        const creator = isAdmin ? createAdminAnalysisSkill : createAnalysisSkill;
        await creator({ name, instruction_md: instruction });
        showToast('分析 skill 已创建', 'success');
      }
      setForm(emptyForm);
      setModalOpen(false);
      await load();
    } catch {
      // API 拦截器会提示错误
    } finally {
      setSaving(false);
    }
  };

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const { data } = await uploadAnalysisSkillMd(file);
      setForm({ id: '', name: data.name, instruction_md: data.instruction_md });
      showToast('Markdown 已读取，请确认后创建', 'success');
    } catch {
      // API 拦截器会提示错误
    } finally {
      event.target.value = '';
    }
  };

  const edit = (skill: AnalysisSkill) => {
    setForm({ id: skill.id, name: skill.name, instruction_md: skill.instruction_md });
    setModalOpen(true);
  };

  const remove = async (skill: AnalysisSkill) => {
    try {
      if (isAdmin) await adminDeleteAnalysisSkill(skill.id);
      else await deleteAnalysisSkill(skill.id);
      showToast('分析 skill 已禁用', 'success');
      await load();
    } catch {
      // API 拦截器会提示错误
    }
  };

  const setStatus = async (skill: AnalysisSkill, status: 'active' | 'disabled') => {
    try {
      await adminUpdateAnalysisSkill(skill.id, { status });
      showToast(status === 'active' ? '分析 skill 已启用' : '分析 skill 已禁用', 'success');
      await load();
    } catch {
      // API 拦截器会提示错误
    }
  };

  const toggleOfficial = async (skill: AnalysisSkill) => {
    try {
      await setAnalysisSkillOfficial(skill.id, !skill.is_official);
      showToast(skill.is_official ? '已取消官方 skill' : '已设为官方 skill', 'success');
      await load();
    } catch {
      // API 拦截器会提示错误
    }
  };

  const modal = modalOpen ? createPortal(
    <div className="analysis-skill-modal-layer" role="presentation" onClick={closeModal}>
      <div
        className="analysis-skill-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="analysis-skill-modal-title"
        onClick={event => event.stopPropagation()}
      >
        <div className="analysis-skill-modal-head">
          <div>
            <h2 id="analysis-skill-modal-title">{form.id ? '编辑 skill' : '创建 skill'}</h2>
            <p>输入 Markdown 指令，后续选择该 skill 的新分析会按这里的规则执行</p>
          </div>
          <button type="button" className="btn-secondary btn-sm" onClick={closeModal} disabled={saving}>
            关闭
          </button>
        </div>

        <form className="analysis-skill-editor" onSubmit={submit}>
          <div className="form-grid">
            <label>
              <span>名称</span>
              <input
                value={form.name}
                onChange={event => setForm(prev => ({ ...prev, name: event.target.value }))}
                placeholder="价格策略"
                required
              />
            </label>
            <label>
              <span>上传 Markdown</span>
              <input type="file" accept=".md,text/markdown" onChange={handleUpload} />
            </label>
          </div>
          <label>
            <span>Markdown 分析指令</span>
            <textarea
              value={form.instruction_md}
              onChange={event => setForm(prev => ({ ...prev, instruction_md: event.target.value }))}
              placeholder="# 价格策略&#10;分析价格锚点、补贴、满减、会员价、限时优惠和转化路径。"
              required
            />
          </label>
          <div className="analysis-skill-actions">
            <button type="submit" disabled={saving}>{saving ? '保存中...' : form.id ? '保存修改' : '创建 skill'}</button>
            <button type="button" className="btn-secondary" onClick={closeModal} disabled={saving}>
              取消
            </button>
          </div>
        </form>
      </div>
    </div>,
    document.body,
  ) : null;

  return (
    <div className="animate-fade-in analysis-skills-page">
      <div className="page-header analysis-skills-header">
        <div>
          <h1>分析 skill</h1>
          <p>管理截图分析维度，新建任务和观察计划会按选择的 skill 生成后续分析</p>
        </div>
        <button type="button" onClick={openCreateModal}>
          创建 skill
        </button>
      </div>

      {loading ? (
        <div className="skeleton" style={{ height: 180 }} />
      ) : visibleSkills.length === 0 ? (
        <div className="empty-state">暂无分析 skill</div>
      ) : (
        <div className="analysis-skill-list">
          {visibleSkills.map(skill => {
            const canEdit = isAdmin || (!skill.is_official && skill.owner_id === user?.id);
            return (
              <article key={skill.id} className="analysis-skill-row">
                <div className="analysis-skill-main">
                  <div className="analysis-skill-title">
                    <strong>{skill.name}</strong>
                    {skill.is_official && <span>官方</span>}
                    {skill.status !== 'active' && <span>已禁用</span>}
                  </div>
                  {isAdmin && (
                    <small>{skill.owner_name || '系统'} · {skill.owner_id || 'system'}</small>
                  )}
                  <pre>{skill.instruction_md}</pre>
                </div>
                <div className="analysis-skill-row-actions">
                  {canEdit && (
                    <button type="button" className="btn-secondary btn-sm" onClick={() => edit(skill)}>
                      编辑
                    </button>
                  )}
                  {isAdmin && (
                    <>
                      <button type="button" className="btn-secondary btn-sm" onClick={() => toggleOfficial(skill)}>
                        {skill.is_official ? '取消官方' : '设为官方'}
                      </button>
                      <button
                        type="button"
                        className="btn-secondary btn-sm"
                        onClick={() => setStatus(skill, skill.status === 'active' ? 'disabled' : 'active')}
                      >
                        {skill.status === 'active' ? '禁用' : '启用'}
                      </button>
                    </>
                  )}
                  {!isAdmin && canEdit && (
                    <button type="button" className="btn-secondary btn-sm" onClick={() => remove(skill)}>
                      禁用
                    </button>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}

      {modal}
    </div>
  );
}
