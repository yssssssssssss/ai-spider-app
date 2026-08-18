import { useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import AdminStatsCards from '../components/AdminStatsCards';
import AdminRequests from './AdminRequests';
import AdminTasks from './AdminTasks';

type TaskTab = 'requests' | 'tasks';

export default function AdminTaskManagement() {
  const location = useLocation();
  const initialTab = useMemo<TaskTab>(() => {
    const params = new URLSearchParams(location.search);
    return params.get('tab') === 'requests' ? 'requests' : 'tasks';
  }, [location.search]);
  const [tab, setTab] = useState<TaskTab>(initialTab);

  useEffect(() => {
    setTab(initialTab);
  }, [initialTab]);

  return (
    <div className="animate-fade-in task-management-page">
      <div className="page-header">
        <h1>任务管理</h1>
        <p>集中处理需求审核、任务执行和核心运营数据</p>
      </div>

      <AdminStatsCards />

      <div className="admin-tabbar" role="tablist" aria-label="任务管理类型">
        <button type="button" className={tab === 'requests' ? 'active' : ''} onClick={() => setTab('requests')}>
          审核管理
        </button>
        <button type="button" className={tab === 'tasks' ? 'active' : ''} onClick={() => setTab('tasks')}>
          任务管理
        </button>
      </div>

      {tab === 'requests' ? <AdminRequests embedded /> : <AdminTasks embedded />}
    </div>
  );
}
