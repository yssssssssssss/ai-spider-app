import { useEffect, useState } from 'react';
import { getAdminStats } from '../api';

function StatCard({ label, value, color, icon }: { label: string; value: number; color: string; icon: React.ReactNode }) {
  return (
    <div className="card animate-fade-in-scale admin-stat-card">
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', fontWeight: 500 }}>
          {label}
        </span>
        <div
          style={{
            width: 36,
            height: 36,
            borderRadius: 'var(--radius-md)',
            background: `${color}15`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color,
          }}
        >
          {icon}
        </div>
      </div>
      <div className="admin-stat-value">{value}</div>
    </div>
  );
}

export default function AdminStatsCards() {
  const [stats, setStats] = useState({ requests: 0, tasks: 0, pendingRequests: 0, pendingTasks: 0 });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getAdminStats()
      .then(({ data }) => setStats({
        requests: data.requests,
        tasks: data.tasks,
        pendingRequests: data.pending_requests,
        pendingTasks: data.pending_tasks,
      }))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="admin-stats-grid">
        {[1, 2, 3, 4].map(i => (
          <div key={i} className="card" style={{ height: 120 }}>
            <div className="skeleton" style={{ height: 16, width: '40%', marginBottom: 20 }} />
            <div className="skeleton" style={{ height: 40, width: '30%' }} />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="admin-stats-grid">
      <StatCard
        label="总需求数"
        value={stats.requests}
        color="#a855f7"
        icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /><line x1="10" y1="9" x2="8" y2="9" /></svg>}
      />
      <StatCard
        label="总任务数"
        value={stats.tasks}
        color="#0a84ff"
        icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="4" width="18" height="18" rx="2" ry="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" /></svg>}
      />
      <StatCard
        label="待审核需求"
        value={stats.pendingRequests}
        color="#ffcc00"
        icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>}
      />
      <StatCard
        label="待执行任务"
        value={stats.pendingTasks}
        color="#bf5af2"
        icon={<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" /></svg>}
      />
    </div>
  );
}
