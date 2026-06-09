import { useState } from 'react';
import { createRequest, interpretRequest } from '../api';
import AnalysisSkillSelector from './AnalysisSkillSelector';
import { useToast } from './Toast';

type ComparisonSlot = {
  slot_key?: string;
  name: string;
  description: string;
  required: boolean;
};

const defaultSlot = (): ComparisonSlot => ({
  name: '会场首屏',
  description: '进入目标活动或频道后看到的首屏画面',
  required: true,
});

function splitApps(value: string) {
  return value.split(/[，,、;\n]/).map(item => item.trim()).filter(Boolean);
}

export default function RequestForm() {
  const { showToast } = useToast();
  const [naturalLanguage, setNaturalLanguage] = useState('');
  const [targetApp, setTargetApp] = useState('');
  const [targetScenario, setTargetScenario] = useState('');
  const [keywords, setKeywords] = useState('');
  const [description, setDescription] = useState('');
  const [analysisSkillIds, setAnalysisSkillIds] = useState<string[]>([]);
  const [compareJdEnabled, setCompareJdEnabled] = useState(false);
  const [aApps, setAApps] = useState('');
  const [jdInstruction, setJdInstruction] = useState('');
  const [comparisonSlots, setComparisonSlots] = useState<ComparisonSlot[]>([defaultSlot()]);
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [interpreting, setInterpreting] = useState(false);
  const [detailsVisible, setDetailsVisible] = useState(false);

  const handleInterpret = async () => {
    const text = naturalLanguage.trim();
    if (!text) {
      showToast('请先输入需求描述', 'warning');
      return;
    }
    setInterpreting(true);
    try {
      const { data } = await interpretRequest({ natural_language: text });
      setTargetApp(data.target_app || '');
      setTargetScenario(data.target_scenario || '');
      setKeywords(Array.isArray(data.keywords) ? data.keywords.join(', ') : '');
      setDescription(data.description || text);
      setAApps(Array.isArray(data.a_apps) ? data.a_apps.join('、') : (data.target_app || ''));
      setJdInstruction(data.jd_instruction || '');
      setComparisonSlots(Array.isArray(data.comparison_slots) && data.comparison_slots.length > 0
        ? data.comparison_slots.map((slot: any) => ({
            slot_key: slot.slot_key || '',
            name: slot.name || '',
            description: slot.description || '',
            required: slot.required !== false,
          })).slice(0, 5)
        : [defaultSlot()]);
      setDetailsVisible(true);
      showToast('已拆解为结构化字段', 'success');
    } catch {
      // api 拦截器已弹出错误 Toast
    } finally {
      setInterpreting(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (compareJdEnabled) {
      const apps = splitApps(aApps);
      if (apps.length === 0) {
        showToast('请填写 A 侧 App', 'warning');
        return;
      }
      if (apps.includes('京东')) {
        showToast('A 侧 App 不能包含京东', 'warning');
        return;
      }
      if (!jdInstruction.trim()) {
        showToast('请填写 JD 等价执行指令', 'warning');
        return;
      }
      if (!comparisonSlots.length || comparisonSlots.some(slot => !slot.name.trim() || !slot.description.trim())) {
        showToast('请完善对照槽位名称和描述', 'warning');
        return;
      }
    }
    setLoading(true);
    try {
      const apps = splitApps(aApps);
      const { data } = await createRequest({
        target_app: targetApp,
        target_scenario: targetScenario,
        keywords: keywords.split(',').map(k => k.trim()).filter(Boolean),
        description,
        analysis_skill_ids: analysisSkillIds,
        compare_jd_enabled: compareJdEnabled,
        comparison: compareJdEnabled ? {
          a_apps: apps,
          jd_instruction: jdInstruction,
          slots: comparisonSlots.map(slot => ({
            slot_key: slot.slot_key || undefined,
            name: slot.name.trim(),
            description: slot.description.trim(),
            required: slot.required,
          })),
        } : undefined,
      });
      setResult(data);
      setTargetApp('');
      setTargetScenario('');
      setKeywords('');
      setDescription('');
      setNaturalLanguage('');
      setAnalysisSkillIds([]);
      setCompareJdEnabled(false);
      setAApps('');
      setJdInstruction('');
      setComparisonSlots([defaultSlot()]);
      setDetailsVisible(false);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="animate-fade-in-scale"
      style={{
        maxWidth: 640,
        margin: '0 auto',
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-lg)',
        padding: 40,
      }}
    >
      <h2 style={{ marginBottom: 8 }}>提交需求</h2>
      <p style={{ marginBottom: 32, color: 'var(--text-secondary)' }}>
        填写以下信息，我们将为你启动自动化的竞品采集流程
      </p>

      <div className="request-interpret-panel">
        <textarea
          className="request-interpret-textarea"
          value={naturalLanguage}
          onChange={e => setNaturalLanguage(e.target.value)}
          placeholder="例如：打开淘宝和拼多多，然后进入百亿补贴会场，分别截取会场图片。"
        />
        <button
          type="button"
          className="request-interpret-button"
          onClick={handleInterpret}
          disabled={interpreting || !naturalLanguage.trim()}
        >
          {interpreting ? '拆解中...' : '智能拆解'}
        </button>
      </div>

      {detailsVisible && (
        <form className="request-details-form animate-fade-in" onSubmit={handleSubmit}>
          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.875rem',
                fontWeight: 500,
                color: 'var(--text-secondary)',
                marginBottom: 8,
              }}
            >
              目标 App
            </label>
            <input
              value={targetApp}
              onChange={e => setTargetApp(e.target.value)}
              placeholder="例如：淘宝、拼多多、京东"
              required
            />
          </div>

          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.875rem',
                fontWeight: 500,
                color: 'var(--text-secondary)',
                marginBottom: 8,
              }}
            >
              目标场景
            </label>
            <input
              value={targetScenario}
              onChange={e => setTargetScenario(e.target.value)}
              placeholder="例如：大促弹窗、新人引导页、商品详情页"
              required
            />
          </div>

          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.875rem',
                fontWeight: 500,
                color: 'var(--text-secondary)',
                marginBottom: 8,
              }}
            >
              关键词 / 关注点（逗号分隔）
            </label>
            <input
              value={keywords}
              onChange={e => setKeywords(e.target.value)}
              placeholder="搜索页填搜索词；非搜索场景填关注点，例如：限时优惠, 红包雨"
            />
          </div>

          <div>
            <label
              style={{
                display: 'block',
                fontSize: '0.875rem',
                fontWeight: 500,
                color: 'var(--text-secondary)',
                marginBottom: 8,
              }}
            >
              关注问题
            </label>
            <textarea
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="写下你希望大模型重点回答的问题，例如：优惠利益点是否突出、关闭入口是否明显..."
            />
          </div>

          <AnalysisSkillSelector value={analysisSkillIds} onChange={setAnalysisSkillIds} />

          <section className="jd-compare-panel">
            <label className="jd-compare-toggle">
              <input
                type="checkbox"
                checked={compareJdEnabled}
                onChange={e => setCompareJdEnabled(e.target.checked)}
              />
              <span>
                <strong>对比JD</strong>
                <small>在京东执行等价操作，按槽位生成逐张 AB 对照</small>
              </span>
            </label>

            {compareJdEnabled && (
              <div className="jd-compare-config">
                <label>
                  <span>A 侧 App（多个用顿号或逗号分隔）</span>
                  <input
                    value={aApps}
                    onChange={e => setAApps(e.target.value)}
                    placeholder="淘宝、拼多多"
                  />
                </label>

                <label>
                  <span>JD 等价执行指令</span>
                  <textarea
                    value={jdInstruction}
                    onChange={e => setJdInstruction(e.target.value)}
                    placeholder="打开京东App，进入等价活动页面，到达目标页面后停留并结束任务"
                  />
                </label>

                <div className="jd-compare-slots">
                  <div className="jd-compare-slots-head">
                    <span>对照槽位</span>
                    <button
                      type="button"
                      className="btn-secondary btn-sm"
                      disabled={comparisonSlots.length >= 5}
                      onClick={() => setComparisonSlots([...comparisonSlots, defaultSlot()])}
                    >
                      新增槽位
                    </button>
                  </div>
                  {comparisonSlots.map((slot, index) => (
                    <div key={index} className="jd-compare-slot-row">
                      <input
                        value={slot.name}
                        onChange={e => setComparisonSlots(comparisonSlots.map((item, itemIndex) => (
                          itemIndex === index ? { ...item, name: e.target.value } : item
                        )))}
                        placeholder="会场首屏"
                      />
                      <input
                        value={slot.description}
                        onChange={e => setComparisonSlots(comparisonSlots.map((item, itemIndex) => (
                          itemIndex === index ? { ...item, description: e.target.value } : item
                        )))}
                        placeholder="判断截图是否命中该目标画面"
                      />
                      <label className="jd-compare-required">
                        <input
                          type="checkbox"
                          checked={slot.required}
                          onChange={e => setComparisonSlots(comparisonSlots.map((item, itemIndex) => (
                            itemIndex === index ? { ...item, required: e.target.checked } : item
                          )))}
                        />
                        必需
                      </label>
                      <button
                        type="button"
                        className="btn-secondary btn-sm"
                        disabled={comparisonSlots.length <= 1}
                        onClick={() => setComparisonSlots(comparisonSlots.filter((_, itemIndex) => itemIndex !== index))}
                      >
                        删除
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </section>

          <button type="submit" disabled={loading} style={{ marginTop: 8, width: 'fit-content' }}>
            {loading ? '提交中...' : '提交需求'}
          </button>
        </form>
      )}

      {result && (
        <div
          className="animate-fade-in"
          style={{
            marginTop: 24,
            padding: 20,
            background: 'var(--accent-light)',
            borderRadius: 'var(--radius-md)',
            border: '1px solid rgba(168, 85, 247, 0.2)',
          }}
        >
          <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: 4 }}>
            需求已提交
          </div>
          <div style={{ fontSize: '0.9375rem', fontWeight: 500 }}>
            ID: {result.id?.slice(0, 8)} · 状态: {result.status}
          </div>
        </div>
      )}
    </div>
  );
}
