import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { listWatchPlans, pauseWatchPlan, resumeWatchPlan, runWatchPlanNow } from '../api';
import { useToast } from '../components/Toast';
import { useAuth } from '../auth';

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    active: 'badge-running',
    paused: 'badge-pending',
    pending: 'badge-pending',
    running: 'badge-running',
    success: 'badge-completed',
    failed: 'badge-rejected',
  };
  const labels: Record<string, string> = {
    active: '观察中',
    paused: '已暂停',
    pending: '待运行',
    running: '运行中',
    success: '成功',
    failed: '失败',
  };
  return <span className={`badge ${map[status] || ''}`}>{labels[status] || status}</span>;
}

function formatDateTime(value?: string | null) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

function formatSchedule(value?: string) {
  if (!value) return '10:00';
  return value.slice(0, 5);
}

export default function AdminWatchPlans() {
  const { showToast } = useToast();
  const { hasRole } = useAuth();
  const [plans, setPlans] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await listWatchPlans();
      setPlans(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleRun = async (id: string) => {
    setBusyId(id);
    try {
      await runWatchPlanNow(id);
      showToast('观察运行已启动', 'success');
      await load();
    } catch {
      // API 拦截器会提示错误
    } finally {
      setBusyId(null);
    }
  };

  const handleToggle = async (plan: any) => {
    setBusyId(plan.id);
    try {
      if (plan.status === 'active') {
        await pauseWatchPlan(plan.id);
        showToast('观察计划已暂停', 'success');
      } else {
        await resumeWatchPlan(plan.id);
        showToast('观察计划已恢复', 'success');
      }
      await load();
    } catch {
      // API 拦截器会提示错误
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="animate-fade-in">
      <div className="page-header watch-header">
        <div>
          <h1>持续观察</h1>
          <p>按天跟踪固定页面首屏，沉淀跨天变化和周期报告</p>
        </div>
        <div className="watch-header-actions">
          <button className="btn-secondary btn-sm" onClick={load} disabled={loading}>
            {loading ? '刷新中...' : '刷新'}
          </button>
          {hasRole('operator') && (
            <Link className="link-button btn-sm" to="/admin/watch-plans/new">
              新建观察
            </Link>
          )}
        </div>
      </div>

      <div className="table-shell">
        {loading && plans.length === 0 ? (
          <div style={{ padding: 40 }}>
            {[1, 2, 3].map(i => <div key={i} className="skeleton" style={{ height: 18, marginBottom: 20 }} />)}
          </div>
        ) : plans.length === 0 ? (
          <div className="empty-state">
            <p>暂无持续观察计划</p>
          </div>
        ) : (
          <table className="admin-watch-table">
            <thead>
              <tr>
                <th>观察名称</th>
	                <th>目标页面</th>
	                <th>时间</th>
	                <th>创建人</th>
	                <th>运行记录</th>
	                <th>最近成功</th>
	                <th>状态</th>
	                <th style={{ textAlign: 'right' }}>操作</th>
	              </tr>
            </thead>
            <tbody>
              {plans.map(plan => (
                <tr key={plan.id}>
                  <td>
                    <div className="table-title-cell">
                      <span title={plan.name}>{plan.name}</span>
                      <small title={plan.focus_question || ''}>{plan.focus_question || '未设置关注问题'}</small>
                    </div>
	                  </td>
	                  <td>{plan.target_app} / {plan.target_page}</td>
	                  <td>{formatSchedule(plan.schedule_time)}</td>
	                  <td>{plan.created_by_name || '-'}</td>
	                  <td>
	                    <div className="table-title-cell">
	                      <span>{plan.run_count || 0} 次运行</span>
	                      <small>{plan.latest_run_status ? <StatusBadge status={plan.latest_run_status} /> : '暂无运行'}</small>
	                    </div>
	                  </td>
	                  <td title={plan.latest_success_run_at || ''}>{formatDateTime(plan.latest_success_run_at)}</td>
	                  <td><StatusBadge status={plan.status} /></td>
                  <td style={{ textAlign: 'right' }}>
                    <div className="table-actions">
                      <Link className="btn-sm task-result-button link-button" to={`/admin/watch-plans/${plan.id}`}>
                        详情
                      </Link>
                      {hasRole('operator') && (
                        <>
                          <button className="btn-secondary btn-sm" onClick={() => handleRun(plan.id)} disabled={busyId === plan.id}>
                            {busyId === plan.id ? '处理中...' : '立即运行'}
                          </button>
                          <button className="btn-secondary btn-sm" onClick={() => handleToggle(plan)} disabled={busyId === plan.id}>
                            {plan.status === 'active' ? '暂停' : '恢复'}
                          </button>
                        </>
                      )}
                    </div>
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
