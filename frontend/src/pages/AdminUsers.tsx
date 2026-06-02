import { FormEvent, useEffect, useState } from 'react';
import {
  createUser,
  getRegistrationInviteCode,
  listUsers,
  updateRegistrationInviteCode,
  updateUser,
} from '../api';
import { useToast } from '../components/Toast';

const roleLabels: Record<string, string> = {
  admin: '管理员',
  operator: '操作员',
  viewer: '观察者',
};

export default function AdminUsers() {
  const { showToast } = useToast();
  const [users, setUsers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ username: '', display_name: '', password: '', role: 'viewer' });
  const [inviteCode, setInviteCode] = useState('');
  const [inviteLoading, setInviteLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await listUsers();
      setUsers(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);
  useEffect(() => {
    getRegistrationInviteCode()
      .then(({ data }) => setInviteCode(data.invite_code || ''))
      .finally(() => setInviteLoading(false));
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    await createUser({ ...form, username: form.username.trim(), display_name: form.display_name.trim() || null });
    showToast('用户已创建', 'success');
    setForm({ username: '', display_name: '', password: '', role: 'viewer' });
    load();
  };

  const toggle = async (user: any) => {
    await updateUser(user.id, { status: user.status === 'active' ? 'disabled' : 'active' });
    showToast(user.status === 'active' ? '用户已禁用' : '用户已启用', 'success');
    load();
  };

  const saveInviteCode = async (event: FormEvent) => {
    event.preventDefault();
    await updateRegistrationInviteCode({ invite_code: inviteCode.trim() });
    showToast('注册邀请码已更新', 'success');
  };

  return (
    <div className="animate-fade-in">
      <div className="page-header">
        <h1>用户管理</h1>
        <p>管理后台用户、角色和启用状态</p>
      </div>

      <form className="inline-form-panel" onSubmit={submit}>
        <input placeholder="用户名" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required />
        <input placeholder="显示名" value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
        <input placeholder="初始密码" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
        <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
          <option value="viewer">观察者</option>
          <option value="operator">操作员</option>
          <option value="admin">管理员</option>
        </select>
        <button type="submit" className="btn-sm">创建</button>
      </form>

      <form className="inline-form-panel" onSubmit={saveInviteCode}>
        <label>
          <span>注册邀请码</span>
          <input
            inputMode="numeric"
            maxLength={4}
            pattern="\d{4}"
            placeholder="4 位数字"
            value={inviteCode}
            onChange={(e) => setInviteCode(e.target.value.replace(/\D/g, '').slice(0, 4))}
            required
            disabled={inviteLoading}
          />
        </label>
        <button type="submit" className="btn-sm" disabled={inviteLoading || inviteCode.length !== 4}>
          保存邀请码
        </button>
      </form>

      <div className="table-shell">
        {loading ? (
          <div style={{ padding: 24 }}><div className="skeleton" style={{ height: 120 }} /></div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>用户名</th>
                <th>显示名</th>
                <th>角色</th>
                <th>状态</th>
                <th>最近登录</th>
                <th style={{ textAlign: 'right' }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map(user => (
                <tr key={user.id}>
                  <td>{user.username}</td>
                  <td>{user.display_name || '-'}</td>
                  <td>{roleLabels[user.role] || user.role}</td>
                  <td>{user.status === 'active' ? '启用' : '禁用'}</td>
                  <td>{user.last_login_at ? new Date(user.last_login_at).toLocaleString('zh-CN') : '-'}</td>
                  <td style={{ textAlign: 'right' }}>
                    <button className="btn-secondary btn-sm" onClick={() => toggle(user)}>
                      {user.status === 'active' ? '禁用' : '启用'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
