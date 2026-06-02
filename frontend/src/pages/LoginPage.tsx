import { FormEvent, useState } from 'react';
import { Link } from 'react-router-dom';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth';
import { useToast } from '../components/Toast';

export default function LoginPage() {
  const { user, login } = useAuth();
  const { showToast } = useToast();
  const location = useLocation();
  const navigate = useNavigate();
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to={(location.state as any)?.from || '/admin'} replace />;

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      await login(username.trim(), password);
      showToast('登录成功', 'success');
      navigate((location.state as any)?.from || '/admin', { replace: true });
    } catch {
      // API 拦截器会提示错误
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-shell animate-fade-in">
      <form className="login-panel" onSubmit={handleSubmit}>
        <h1>登录后台</h1>
        <label>
          <span>用户名</span>
          <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required />
        </label>
        <label>
          <span>密码</span>
          <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="current-password" required />
        </label>
        <button type="submit" disabled={submitting}>
          {submitting ? '登录中...' : '登录'}
        </button>
        <Link className="btn-secondary link-button" to="/register">
          注册
        </Link>
      </form>
    </div>
  );
}
