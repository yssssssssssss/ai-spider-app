import { FormEvent, useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth';
import { useToast } from '../components/Toast';

export default function RegisterPage() {
  const { user, register } = useAuth();
  const { showToast } = useToast();
  const navigate = useNavigate();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [inviteCode, setInviteCode] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (user) return <Navigate to="/admin" replace />;

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    try {
      await register(username.trim(), password, inviteCode.trim());
      showToast('注册成功', 'success');
      navigate('/admin', { replace: true });
    } catch {
      // API 拦截器会提示错误
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="login-shell animate-fade-in">
      <form className="login-panel" onSubmit={handleSubmit}>
        <h1>注册账号</h1>
        <label>
          <span>用户名</span>
          <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required />
        </label>
        <label>
          <span>密码</span>
          <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" autoComplete="new-password" required />
        </label>
        <label>
          <span>邀请码</span>
          <input
            name="invite_code"
            inputMode="numeric"
            maxLength={4}
            pattern="\d{4}"
            value={inviteCode}
            onChange={(event) => setInviteCode(event.target.value.replace(/\D/g, '').slice(0, 4))}
            placeholder="4 位数字"
            required
          />
        </label>
        <button type="submit" disabled={submitting || inviteCode.length !== 4}>
          {submitting ? '注册中...' : '注册'}
        </button>
        <Link className="btn-secondary link-button" to="/login">
          返回登录
        </Link>
      </form>
    </div>
  );
}
