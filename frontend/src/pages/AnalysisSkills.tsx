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
  spec_title: '', spec_version: '1', spec_source: '', spec_document: '',
  spec_rules: [{ id: '1', clause: '', expected: '' }],
  output_schema_json: '',
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
      spec_title: skill.specification_json?.title || '',
      spec_version: skill.specification_json?.version || '1',
      spec_source: skill.specification_json?.source || '',
      spec_document: skill.specification_json?.document || '',
      spec_rules: skill.specification_json?.rules || [{ id: '1', clause: '', expected: '' }],
      output_schema_json: skill.output_schema_json && Object.keys(skill.output_schema_json).length ? JSON.stringify(skill.output_schema_json, null, 2) : '',
    });
  };

  const resetForm = () => {
    setEditingId(null);
    setForm(emptyForm);
  };

  const saveSkill = async () => {
    if (!form.name.trim() || (form.skill_type !== 'inspection' && !form.prompt.trim())) {
      showToast('Skill 名称和 Prompt 必填', 'warning');
      return;
    }
    let outputSchema;
    try {
      outputSchema = form.output_schema_json.trim() ? JSON.parse(form.output_schema_json) : {};
    } catch {
      showToast('输出 Schema 不是有效的 JSON', 'warning');
      return;
    }
    setSaving(true);
    const payload = {
      name: form.name.trim(),
      description: form.description.trim(),
      scenario_tags_json: form.scenario_tags_json.split(/[、,，]/).map((item: string) => item.trim()).filter(Boolean),
      prompt: form.prompt || '根据规范逐项巡查',
      profile: form.profile,
      skill_type: form.skill_type,
      status: form.status,
      output_schema_json: outputSchema,
      specification_json: form.skill_type === 'inspection' ? {
        title: form.spec_title, version: form.spec_version, source: form.spec_source,
        document: form.spec_document, rules: form.spec_rules,
      } : null,
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
    if (form.skill_type === 'inspection') {
      const document = await file.text();
      setForm({ ...form, spec_source: file.name, spec_document: document,
        spec_title: form.spec_title || file.name.replace(/\.(md|txt)$/i, '') });
      showToast('规范原文已载入，请确认检查项后保存', 'info');
      return;
    }
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
            <span>类型</span>
            <select value={form.skill_type} disabled={skills.some(s => s.id === editingId && s.is_system)} onChange={(event) => setForm({ ...form, skill_type: event.target.value })}>
              <option value="analysis">截图分析</option>
              <option value="inspection">规范巡查</option>
            </select>
          </label>
          {form.skill_type === 'inspection' && <>
            <label><span>规范名称</span><input value={form.spec_title} onChange={e => setForm({ ...form, spec_title: e.target.value })} /></label>
            <label><span>规范版本</span><input value={form.spec_version} onChange={e => setForm({ ...form, spec_version: e.target.value })} /></label>
            <label><span>规范来源（文档名或地址）</span><input value={form.spec_source} onChange={e => setForm({ ...form, spec_source: e.target.value })} /></label>
            <label><span>规范原文</span><textarea value={form.spec_document} onChange={e => setForm({ ...form, spec_document: e.target.value })} /></label>
            <p>同一份规范可用于不同任务和场景。每条结论保留条款、版本和截图证据。</p>
            {form.spec_rules.map((rule, index) => <fieldset key={index}>
              <legend>检查项 {index + 1}</legend>
              <label><span>编号</span><input value={rule.id} onChange={e => setForm({ ...form, spec_rules: form.spec_rules.map((r, i) => i === index ? { ...r, id: e.target.value } : r) })} /></label>
              <label><span>规范条款位置</span><input value={rule.clause} placeholder="第 3.7 节" onChange={e => setForm({ ...form, spec_rules: form.spec_rules.map((r, i) => i === index ? { ...r, clause: e.target.value } : r) })} /></label>
              <label><span>判定标准</span><textarea value={rule.expected} onChange={e => setForm({ ...form, spec_rules: form.spec_rules.map((r, i) => i === index ? { ...r, expected: e.target.value } : r) })} /></label>
              <button type="button" className="btn-secondary btn-sm" onClick={() => setForm({ ...form, spec_rules: form.spec_rules.filter((_, i) => i !== index) })}>删除检查项</button>
            </fieldset>)}
            <button type="button" className="btn-secondary" onClick={() => setForm({ ...form, spec_rules: [...form.spec_rules, { id: String(form.spec_rules.length + 1), clause: '', expected: '' }] })}>增加检查项</button>
          </>}
          <label>
            <span>Prompt</span>
            <textarea className="skill-prompt-input analysis-skill-prompt" value={form.prompt} onChange={(event) => setForm({ ...form, prompt: event.target.value })} />
          </label>
          {form.skill_type !== 'inspection' && <label><span>输出 Schema（可选 JSON）</span><textarea value={form.output_schema_json} onChange={e => setForm({ ...form, output_schema_json: e.target.value })} /></label>}
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
                  {skill.skill_type === 'inspection' && <span>规范巡查 · {skill.specification_json?.version}</span>}
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
