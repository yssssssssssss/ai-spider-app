import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import { ToastProvider } from './components/Toast';
import HomePage from './pages/HomePage';
import SearchPage from './pages/SearchPage';
import AdminRequests from './pages/AdminRequests';
import AdminTasks from './pages/AdminTasks';
import AdminTaskResults from './pages/AdminTaskResults';
import AdminDashboard from './pages/AdminDashboard';

function NavLink({ to, children }: { to: string; children: React.ReactNode }) {
  const { pathname } = useLocation();
  const active = pathname === to || pathname.startsWith(to + '/');
  return (
    <Link
      to={to}
      style={{
        padding: '8px 14px',
        borderRadius: 8,
        fontSize: '0.875rem',
        fontWeight: 500,
        color: active ? '#fff' : '#a1a1a6',
        background: active ? 'rgba(255,255,255,0.08)' : 'transparent',
        transition: 'all 0.2s ease',
        whiteSpace: 'nowrap',
      }}
      onMouseEnter={(e) => {
        if (!active) (e.target as HTMLElement).style.color = '#fff';
      }}
      onMouseLeave={(e) => {
        if (!active) (e.target as HTMLElement).style.color = '#a1a1a6';
      }}
    >
      {children}
    </Link>
  );
}

function Navigation() {
  return (
    <nav
      style={{
        position: 'sticky',
        top: 0,
        zIndex: 100,
        backdropFilter: 'blur(20px) saturate(180%)',
        WebkitBackdropFilter: 'blur(20px) saturate(180%)',
        background: 'rgba(0, 0, 0, 0.65)',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}
    >
      <div
        className="container"
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          height: 64,
          gap: 16,
        }}
      >
        <Link
          to="/"
          style={{
            fontSize: '1.25rem',
            fontWeight: 700,
            letterSpacing: '-0.03em',
            color: '#fff',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            flexShrink: 0,
          }}
        >
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <rect x="2" y="2" width="9" height="9" rx="2" fill="#a855f7" opacity="0.9"/>
            <rect x="13" y="2" width="9" height="9" rx="2" fill="#a855f7" opacity="0.6"/>
            <rect x="2" y="13" width="9" height="9" rx="2" fill="#a855f7" opacity="0.6"/>
            <rect x="13" y="13" width="9" height="9" rx="2" fill="#a855f7" opacity="0.3"/>
          </svg>
          竞品分析
        </Link>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4, overflow: 'auto' }}>
          <NavLink to="/">需求提交</NavLink>
          <NavLink to="/search">图片检索</NavLink>
          <NavLink to="/admin">数据看板</NavLink>
          <NavLink to="/admin/requests">需求管理</NavLink>
          <NavLink to="/admin/tasks">任务管理</NavLink>
        </div>
      </div>
    </nav>
  );
}

function App() {
  return (
    <ToastProvider>
      <BrowserRouter>
        <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
          <Navigation />
          <main style={{ flex: 1, padding: '48px 0' }}>
            <div className="container">
              <Routes>
                <Route path="/" element={<HomePage />} />
                <Route path="/search" element={<SearchPage />} />
                <Route path="/admin" element={<AdminDashboard />} />
                <Route path="/admin/requests" element={<AdminRequests />} />
                <Route path="/admin/tasks" element={<AdminTasks />} />
                <Route path="/admin/tasks/:taskId/results" element={<AdminTaskResults />} />
              </Routes>
            </div>
          </main>
          <footer
            style={{
              borderTop: '1px solid rgba(255,255,255,0.06)',
              padding: '24px 0',
              textAlign: 'center',
              color: '#6e6e73',
              fontSize: '0.8125rem',
            }}
          >
            <div className="container">竞品分析平台 · AI 驱动</div>
          </footer>
        </div>
      </BrowserRouter>
    </ToastProvider>
  );
}

export default App;
