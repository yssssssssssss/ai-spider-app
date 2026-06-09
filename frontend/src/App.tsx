import { BrowserRouter, Routes, Route, Link, Navigate, useLocation } from 'react-router-dom';
import { ToastProvider } from './components/Toast';
import { AuthProvider, RequireAuth, RequireRole, useAuth } from './auth';
import HomePage from './pages/HomePage';
import SearchPage from './pages/SearchPage';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import AdminRequests from './pages/AdminRequests';
import AdminTasks from './pages/AdminTasks';
import AdminTaskResults from './pages/AdminTaskResults';
import AdminDevices from './pages/AdminDevices';
import AdminUsers from './pages/AdminUsers';
import AdminWatchPlans from './pages/AdminWatchPlans';
import AdminWatchPlanNew from './pages/AdminWatchPlanNew';
import AdminWatchPlanDetail from './pages/AdminWatchPlanDetail';
import AdminDashboard from './pages/AdminDashboard';
import AnalysisSkillsPage from './pages/AnalysisSkillsPage';
import BlackboardPage from './pages/BlackboardPage';
import BlackboardTaskResults from './pages/BlackboardTaskResults';

function NavLink({ to, children }: { to: string; children: React.ReactNode }) {
  const { pathname } = useLocation();
  const active = to === '/' || to === '/admin'
    ? pathname === to
    : pathname === to || pathname.startsWith(to + '/');
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
  const { user, logout, hasRole } = useAuth();
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
          <NavLink to="/blackboard">黑板报</NavLink>
          {user ? (
            <>
              <NavLink to="/search">图片检索</NavLink>
              <NavLink to="/admin">数据看板</NavLink>
              <NavLink to="/admin/requests">{hasRole('operator') ? '审核管理' : '需求管理'}</NavLink>
              <NavLink to="/admin/tasks">任务管理</NavLink>
              <NavLink to="/admin/devices">设备管理</NavLink>
              <NavLink to="/admin/watch-plans">持续观察</NavLink>
              <NavLink to="/analysis-skills">分析 skill</NavLink>
              {hasRole('admin') && <NavLink to="/admin/users">用户管理</NavLink>}
              <button type="button" className="nav-user-button" onClick={logout}>
                {user.display_name || user.username} · 退出
              </button>
            </>
          ) : (
            <NavLink to="/login">登录</NavLink>
          )}
        </div>
      </div>
    </nav>
  );
}

function App() {
  return (
    <ToastProvider>
      <BrowserRouter>
        <AuthProvider>
          <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column' }}>
            <Navigation />
            <main style={{ flex: 1, padding: '48px 0' }}>
              <div className="container">
                <Routes>
                  <Route path="/" element={<HomePage />} />
                  <Route path="/blackboard" element={<BlackboardPage />} />
                  <Route path="/blackboard/tasks/:taskId" element={<BlackboardTaskResults />} />
                  <Route path="/login" element={<LoginPage />} />
                  <Route path="/register" element={<RegisterPage />} />
                  <Route path="/search" element={<RequireAuth><SearchPage /></RequireAuth>} />
                  <Route path="/analysis-skills" element={<RequireAuth><AnalysisSkillsPage /></RequireAuth>} />
                  <Route path="/admin" element={<RequireAuth><AdminDashboard /></RequireAuth>} />
                  <Route path="/admin/requests" element={<RequireAuth><AdminRequests /></RequireAuth>} />
                  <Route path="/admin/tasks" element={<RequireAuth><AdminTasks /></RequireAuth>} />
                  <Route path="/admin/tasks/:taskId/results" element={<RequireAuth><AdminTaskResults /></RequireAuth>} />
                  <Route path="/admin/images" element={<RequireAuth><Navigate to="/search" replace /></RequireAuth>} />
                  <Route path="/admin/devices" element={<RequireAuth><AdminDevices /></RequireAuth>} />
                  <Route path="/admin/users" element={<RequireAuth><RequireRole role="admin"><AdminUsers /></RequireRole></RequireAuth>} />
                  <Route path="/admin/watch-plans" element={<RequireAuth><AdminWatchPlans /></RequireAuth>} />
                  <Route path="/admin/watch-plans/new" element={<RequireAuth><RequireRole role="operator"><AdminWatchPlanNew /></RequireRole></RequireAuth>} />
                  <Route path="/admin/watch-plans/:planId" element={<RequireAuth><AdminWatchPlanDetail /></RequireAuth>} />
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
        </AuthProvider>
      </BrowserRouter>
    </ToastProvider>
  );
}

export default App;
