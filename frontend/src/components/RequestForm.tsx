import { useState } from 'react';
import { createRequest } from '../api';

const examples = [
  {
    label: '搜索结果页',
    targetApp: '淘宝',
    targetScenario: '搜索结果页',
    keywords: '蓝牙耳机, 618, 国家补贴',
    description: '关注搜索结果页的商品卡片、促销标签、价格展示、筛选入口和转化引导。',
  },
  {
    label: '商品详情页',
    targetApp: '京东',
    targetScenario: '商品详情页',
    keywords: '智能手表, 新人价, 百亿补贴',
    description: '重点采集首屏商品信息、价格权益、评价入口、购买按钮和信任背书设计。',
  },
  {
    label: '大促弹窗',
    targetApp: '拼多多',
    targetScenario: '大促弹窗',
    keywords: '红包, 限时优惠, 新人券',
    description: '关注弹窗出现时机、利益点文案、关闭入口、按钮层级和用户领取路径。',
  },
];

export default function RequestForm() {
  const [targetApp, setTargetApp] = useState('');
  const [targetScenario, setTargetScenario] = useState('');
  const [keywords, setKeywords] = useState('');
  const [description, setDescription] = useState('');
  const [result, setResult] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      const { data } = await createRequest({
        target_app: targetApp,
        target_scenario: targetScenario,
        keywords: keywords.split(',').map(k => k.trim()).filter(Boolean),
        description
      });
      setResult(data);
      setTargetApp('');
      setTargetScenario('');
      setKeywords('');
      setDescription('');
    } finally {
      setLoading(false);
    }
  };

  const applyExample = (example: typeof examples[number]) => {
    setTargetApp(example.targetApp);
    setTargetScenario(example.targetScenario);
    setKeywords(example.keywords);
    setDescription(example.description);
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

      <div
        style={{
          marginBottom: 28,
          padding: 16,
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-md)',
          background: 'rgba(255, 255, 255, 0.03)',
        }}
      >
        <div style={{ fontSize: '0.8125rem', color: 'var(--text-tertiary)', marginBottom: 10 }}>
          推荐填写
        </div>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {examples.map(example => (
            <button
              key={example.label}
              type="button"
              className="btn-secondary btn-sm"
              onClick={() => applyExample(example)}
            >
              {example.label}
            </button>
          ))}
        </div>
      </div>

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
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

        <button type="submit" disabled={loading} style={{ marginTop: 8, width: 'fit-content' }}>
          {loading ? '提交中...' : '提交需求'}
        </button>
      </form>

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
