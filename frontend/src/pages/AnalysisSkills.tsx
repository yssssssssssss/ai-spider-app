import { useEffect, useState } from 'react';
import {
  createAnalysisSkill,
  deleteAnalysisSkill,
  listAnalysisSkills,
  toggleAnalysisSkill,
  updateAnalysisSkill,
  uploadAnalysisSkill,
} from '../api';
import { useToast } from '../components/Toast';
import { useAuth } from '../auth';

const emptyForm = {
  name: '',
  description: '',
  scenario_tags_json: '',
  prompt: '',
  profile: 'default',
  skill_type: 'analysis',
  status: 'active',
};

export default function AnalysisSkills() {
  const { showToast } = useToast();
  const { hasRole } = useAuth();
  const [skills, setSkills] = useState<any[]>([]);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [saving, setSaving] = useState(false);
  const canManage = hasRole('operator');

  const load = async () => {
    const { data } = await listAnalysisSkills();
    setSkills(data);
  };

  useEffect(() => {
    load().catch(() => undefined);
  }, []);

  const editSkill = (skill: any) => {
    setEditingId(skill.id);
    setForm({
      name: skill.name || '',
      description: skill.description || '',
      scenario_tags_json: Array.isArray(skill.scenario_tags_json) ? skill.scenario_tags_json.join('、') : '',
      prompt: skill.prompt || '',
      profile: skill.profile || 'default',
      skill_type: skill.skill_type || 'analysis',
      status: skill.status || 'active',
    });
  };

  const resetForm = () => {
    setEditingId(null);
    setForm(emptyForm);
  };

  const saveSkill = async () => {
    if (!form.name.trim() || !form.prompt.trim()) {
      showToast('Skill 名称和 Prompt 必填', 'warning');
      return;
    }
    setSaving(true);
    const payload = {
      name: form.name.trim(),
      description: form.description.trim(),
      scenario_tags_json: form.scenario_tags_json.split(/[、,，]/).map((item: string) => item.trim()).filter(Boolean),
      prompt: form.prompt,
      profile: form.profile,
      skill_type: form.skill_type,
      status: form.status,
    };
    try {
      if (editingId) {
        await updateAnalysisSkill(editingId, payload);
      } else {
        await createAnalysisSkill(payload);
      }
      showToast('分析 Skill 已保存', 'success');
      resetForm();
      await load();
    } catch {
      // api 拦截器已弹出错误 Toast
    } finally {
      setSaving(false);
    }
  };

  const uploadSkill = async (file?: File | null) => {
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    formData.append('profile', form.profile || 'default');
    await uploadAnalysisSkill(formData);
    showToast('Skill 已上传', 'success');
    await load();
  };

  const removeSkill = async (id: string) => {
    await deleteAnalysisSkill(id);
    showToast('Skill 已删除', 'success');
    await load();
  };

  const handleToggle = async (id: string) => {
    await toggleAnalysisSkill(id);
    showToast('状态已切换', 'success');
    await load();
  };

  const systemSkills = skills.filter((s: any) => s.is_system);
  const userSkills = skills.filter((s: any) => !s.is_system);
  const allSkills = [...systemSkills, ...userSkills];

  return (
    <div className="animate-fade-in compare-page">
      <div className={`skill-layout${canManage ? '' : ' viewer'}`}>
        {canManage && <section className="compare-panel">
          <div className="compare-panel-head">
            <h2>{editingId ? '编辑 Skill' : '新建 Skill'}</h2>
            <label className="upload-inline-button">
              上传 Markdown
              <input type="file" accept=".md,.txt,text/markdown,text/plain" onChange={(event) => uploadSkill(event.target.files?.[0])} />
            </label>
          </div>
          <label>
            <span>名称</span>
            <input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
          </label>
          <label>
            <span>描述</span>
            <textarea value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} />
          </label>
          <label>
            <span>适用场景</span>
            <input value={form.scenario_tags_json} onChange={(event) => setForm({ ...form, scenario_tags_json: event.target.value })} placeholder="商品详情页、搜索结果页" />
          </label>
          <label>
            <span>Profile</span>
            <select value={form.profile} onChange={(event) => setForm({ ...form, profile: event.target.value })}>
              <option value="default">默认（普通截图）</option>
              <option value="watch">持续观察</option>
            </select>
          </label>
          <label>
            <span>Prompt</span>
            <textarea className="skill-prompt-input analysis-skill-prompt" value={form.prompt} onChange={(event) => setForm({ ...form, prompt: event.target.value })} />
          </label>
          <label>
            <span>状态</span>
            <select value={form.status} onChange={(event) => setForm({ ...form, status: event.target.value })}>
              <option value="active">启用</option>
              <option value="disabled">停用</option>
            </select>
          </label>
          <div className="compare-toolbar-actions">
            <button type="button" onClick={saveSkill} disabled={saving}>{saving ? '保存中...' : '保存'}</button>
            <button type="button" className="btn-secondary" onClick={resetForm}>取消</button>
          </div>
        </section>}

        <section className="skill-list">
          {allSkills.map((skill: any) => (
            <article key={skill.id} className="compare-panel skill-row">
              <div>
                <h2>{skill.name}</h2>
                <p>{skill.description || '暂无描述'}</p>
                <div className="skill-meta">
                  <span>{skill.status === 'active' ? '启用中' : '已停用'}</span>
                  <span>{skill.profile === 'watch' ? '持续观察' : '默认'}</span>
                  <span>v{skill.version}</span>
                  {skill.is_system && <span>系统 Skill</span>}
                </div>
              </div>
              {canManage && (
                <div className="compare-toolbar-actions">
                  <button type="button" className="btn-secondary btn-sm" onClick={() => editSkill(skill)}>编辑</button>
                  {!skill.is_system && (
                    <>
                      <button type="button" className="btn-secondary btn-sm" onClick={() => handleToggle(skill.id)}>
                        {skill.status === 'active' ? '停用' : '启用'}
                      </button>
                      <button type="button" className="btn-danger btn-sm" onClick={() => removeSkill(skill.id)}>删除</button>
                    </>
                  )}
                </div>
              )}
            </article>
          ))}

          {skills.length === 0 && <p className="empty-hint">暂无分析 Skill</p>}
        </section>
      </div>
    </div>
  );
}
