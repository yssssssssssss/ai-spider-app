import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import RequestForm from '../components/RequestForm';
import WatchPlanForm from '../components/WatchPlanForm';
import { useAuth } from '../auth';

type HomeTab = 'collect' | 'watch';

export default function HomePage() {
  const { user, loading } = useAuth();
  const location = useLocation();
  const [activeTab, setActiveTab] = useState<HomeTab>('collect');
  const [showLoginPrompt, setShowLoginPrompt] = useState(false);

  useEffect(() => {
    if (!loading && !user) {
      setShowLoginPrompt(true);
    }
  }, [loading, user]);

  useEffect(() => {
    if (!showLoginPrompt) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setShowLoginPrompt(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [showLoginPrompt]);

  const loginState = { from: location.pathname };

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

      {loading ? (
        <div className="skeleton home-auth-loading" aria-label="正在检查登录状态" />
      ) : !user ? (
        <div className="login-required-panel">
          <button type="button" onClick={() => setShowLoginPrompt(true)}>
            登录后使用
          </button>
        </div>
      ) : activeTab === 'collect' ? (
        <RequestForm key="collect" />
      ) : (
        <WatchPlanForm key="watch" homePanel />
      )}

      {showLoginPrompt && !loading && !user ? (
        <div
          className="login-prompt-layer"
          role="presentation"
          onClick={() => setShowLoginPrompt(false)}
        >
          <div
            className="login-prompt-dialog animate-fade-in-scale"
            role="dialog"
            aria-modal="true"
            aria-labelledby="login-prompt-title"
            aria-describedby="login-prompt-desc"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              className="login-prompt-close"
              aria-label="关闭登录提示"
              onClick={() => setShowLoginPrompt(false)}
            >
              ×
            </button>
            <p className="login-prompt-kicker">需要登录</p>
            <h2 id="login-prompt-title">先登录账号，再提交分析需求</h2>
            <p id="login-prompt-desc">
              登录后可以提交竞品搜集需求，也可以创建固定页面的持续观察计划。
            </p>
            <div className="login-prompt-actions">
              <Link className="link-button" to="/login" state={loginState}>
                去登录
              </Link>
              <button
                type="button"
                className="btn-secondary"
                onClick={() => setShowLoginPrompt(false)}
              >
                稍后再说
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
