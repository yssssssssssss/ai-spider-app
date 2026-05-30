import { useState } from 'react';
import RequestForm from '../components/RequestForm';
import WatchPlanForm from '../components/WatchPlanForm';

type HomeTab = 'collect' | 'watch';

export default function HomePage() {
  const [activeTab, setActiveTab] = useState<HomeTab>('collect');

  return (
    <div className="animate-fade-in">
      <div
        style={{
          textAlign: 'center',
          padding: '40px 0 60px',
          maxWidth: 720,
          margin: '0 auto',
        }}
      >
        <h1
          style={{
            fontSize: '3.5rem',
            fontWeight: 700,
            letterSpacing: '-0.04em',
            lineHeight: 1.1,
            marginBottom: 20,
            background: 'linear-gradient(135deg, #fff 0%, #a1a1a6 100%)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
          }}
        >
          竞品分析平台
        </h1>
        <p
          style={{
            fontSize: '1.25rem',
            color: '#a1a1a6',
            lineHeight: 1.6,
            maxWidth: 560,
            margin: '0 auto',
          }}
        >
          提交竞品搜集需求，或创建一个固定页面的持续观察计划
        </p>
      </div>

      <div className="home-tab-switch" role="tablist" aria-label="需求提交类型">
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'collect'}
          className={activeTab === 'collect' ? 'active' : ''}
          onClick={() => setActiveTab('collect')}
        >
          竞品搜集
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={activeTab === 'watch'}
          className={activeTab === 'watch' ? 'active' : ''}
          onClick={() => setActiveTab('watch')}
        >
          持续观察
        </button>
      </div>

      {activeTab === 'collect' ? (
        <RequestForm key="collect" />
      ) : (
        <WatchPlanForm key="watch" homePanel />
      )}
    </div>
  );
}
