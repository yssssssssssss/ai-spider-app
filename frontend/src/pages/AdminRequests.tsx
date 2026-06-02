import { useEffect, useState } from 'react';
import { useToast } from '../components/Toast';
import { listAdminRequests, approveRequest, rejectRequest } from '../api';
import { useAuth } from '../auth';

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    pending: 'badge-pending',
    approved: 'badge-approved',
    rejected: 'badge-rejected',
  };
  const labels: Record<string, string> = {
    pending: '待审核',
    approved: '已通过',
    rejected: '已拒绝',
  };
  return <span className={`badge ${map[status] || ''}`}>{labels[status] || status}</span>;
}

export default function AdminRequests() {
  const { showToast } = useToast();
  const { user, hasRole } = useAuth();
  const canReview = hasRole('operator');
  const [requests, setRequests] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [actingId, setActingId] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await listAdminRequests();
      setRequests(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleApprove = async (id: string, mode: string) => {
    setActingId(id);
    try {
      await approveRequest(id, { admin_id: user?.username, mode });
      showToast(mode === 'autoglm' ? '已创建 AI 采集任务' : '已创建规则采集任务', 'success');
      load();
    } catch {
      // api 拦截器已弹出错误 Toast
    } finally {
      setActingId(null);
    }
  };

  const handleReject = async (id: string) => {
    setActingId(id);
    try {
      await rejectRequest(id, { admin_id: user?.username });
      showToast('需求已拒绝', 'warning');
      load();
    } catch {
      // api 拦截器已弹出错误 Toast
    } finally {
      setActingId(null);
    }
  };

  return (
    <div className="animate-fade-in">
      <div className="page-header" style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between' }}>
        <div>
          <h1>{canReview ? '审核管理' : '需求管理'}</h1>
          <p>{canReview ? '审核用户提交的竞品分析需求' : '查看自己提交的竞品分析需求'}</p>
        </div>
        <button className="btn-secondary btn-sm" onClick={load} disabled={loading}>
          {loading ? '刷新中...' : '刷新'}
        </button>
      </div>

      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-lg)',
          overflow: 'hidden',
        }}
      >
        {loading && requests.length === 0 ? (
          <div style={{ padding: 40 }}>
            {[1, 2, 3].map(i => (
              <div key={i} style={{ display: 'flex', gap: 16, marginBottom: 20, alignItems: 'center' }}>
                <div className="skeleton" style={{ width: 60, height: 16 }} />
                <div className="skeleton" style={{ width: 100, height: 16 }} />
                <div className="skeleton" style={{ width: 120, height: 16 }} />
                <div className="skeleton" style={{ width: 80, height: 16 }} />
                <div className="skeleton" style={{ width: 60, height: 16 }} />
              </div>
            ))}
          </div>
        ) : requests.length === 0 ? (
          <div
            style={{
              textAlign: 'center',
              padding: '80px 0',
              color: 'var(--text-tertiary)',
            }}
          >
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ marginBottom: 16, opacity: 0.5 }}>
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
            </svg>
            <p>暂无需求记录</p>
          </div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>目标 App</th>
                <th>场景</th>
                <th>关键词</th>
                <th>提交人</th>
                <th>状态</th>
                <th style={{ textAlign: 'right' }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {requests.map(r => (
                <tr key={r.id}>
                  <td>
                    <code
                      style={{
                        fontFamily: 'SF Mono, Monaco, monospace',
                        fontSize: '0.8125rem',
                        color: 'var(--text-secondary)',
                        background: 'var(--bg-tertiary)',
                        padding: '2px 8px',
                        borderRadius: 'var(--radius-sm)',
                      }}
                    >
                      {r.id?.slice(0, 8)}
                    </code>
                  </td>
                  <td style={{ fontWeight: 500 }}>{r.target_app}</td>
                  <td>{r.target_scenario}</td>
                  <td style={{ maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {r.keywords?.join(', ')}
                  </td>
                  <td>{r.user_display_name || r.user_id || '-'}</td>
                  <td><StatusBadge status={r.status} /></td>
                  <td style={{ textAlign: 'right' }}>
                    {r.status === 'pending' && canReview && (
                      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                        <button
                          className="btn-sm"
                          onClick={() => handleApprove(r.id, 'uiautomator2')}
                          disabled={actingId === r.id}
                        >
                          {actingId === r.id ? '处理中...' : '规则采集'}
                        </button>
                        <button
                          className="btn-sm"
                          style={{ background: '#a855f7' }}
                          onClick={() => handleApprove(r.id, 'autoglm')}
                          disabled={actingId === r.id}
                        >
                          {actingId === r.id ? '处理中...' : 'AI 采集'}
                        </button>
                        <button
                          className="btn-sm btn-danger"
                          onClick={() => handleReject(r.id)}
                          disabled={actingId === r.id}
                        >
                          拒绝
                        </button>
                      </div>
                    )}
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
