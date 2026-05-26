import { useEffect, useState } from 'react';
import { listAdminRequests, listAdminTasks } from '../api';

export default function AdminDashboard() {
  const [stats, setStats] = useState({ requests: 0, tasks: 0, pendingRequests: 0, pendingTasks: 0 });

  useEffect(() => {
    const load = async () => {
      const [{ data: reqs }, { data: tasks }] = await Promise.all([
        listAdminRequests(),
        listAdminTasks()
      ]);
      setStats({
        requests: reqs.length,
        tasks: tasks.length,
        pendingRequests: reqs.filter((r: any) => r.status === 'pending').length,
        pendingTasks: tasks.filter((t: any) => t.status === 'pending').length
      });
    };
    load();
  }, []);

  return (
    <div>
      <h1>后台 - 数据看板</h1>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
        <div style={{ padding: 16, border: '1px solid #ccc', borderRadius: 8 }}>
          <h3>总需求数</h3><p>{stats.requests}</p>
        </div>
        <div style={{ padding: 16, border: '1px solid #ccc', borderRadius: 8 }}>
          <h3>总任务数</h3><p>{stats.tasks}</p>
        </div>
        <div style={{ padding: 16, border: '1px solid #ccc', borderRadius: 8 }}>
          <h3>待审核需求</h3><p>{stats.pendingRequests}</p>
        </div>
        <div style={{ padding: 16, border: '1px solid #ccc', borderRadius: 8 }}>
          <h3>待执行任务</h3><p>{stats.pendingTasks}</p>
        </div>
      </div>
    </div>
  );
}
