import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useToast } from '../components/Toast';
import { listAdminTasks, listDevices, retryTask, runTask, taskEventsUrl, updateTask } from '../api';
import { useAuth } from '../auth';

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    pending: 'badge-pending',
    queued: 'badge-pending',
    running: 'badge-running',
    completed: 'badge-completed',
    failed: 'badge-rejected',
  };
  const labels: Record<string, string> = {
    pending: '待执行',
    queued: '排队中',
    running: '执行中',
    completed: '已完成',
    failed: '失败',
  };
  return <span className={`badge ${map[status] || ''}`}>{labels[status] || status}</span>;
}

function formatCompletedAt(value?: string | null) {
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

export default function AdminTasks() {
  const { showToast } = useToast();
  const { hasRole } = useAuth();
  const [tasks, setTasks] = useState<any[]>([]);
  const [devices, setDevices] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [runningId, setRunningId] = useState<string | null>(null);
  const [deviceId, setDeviceId] = useState('');
  const [selectedTaskIds, setSelectedTaskIds] = useState<string[]>([]);
  const [bulkStarting, setBulkStarting] = useState(false);
  const [editingTaskId, setEditingTaskId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState('');
  const [savingTaskId, setSavingTaskId] = useState<string | null>(null);
  const eventSourcesRef = useRef<Record<string, EventSource>>({});
  const pendingTaskIds = useMemo(() => tasks.filter(task => task.status === 'pending').map(task => task.id), [tasks]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await listAdminTasks();
      setTasks(data);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    listDevices().then(({ data }) => setDevices(data)).catch(() => setDevices([]));
  }, []);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    const pendingIds = new Set(pendingTaskIds);
    setSelectedTaskIds(ids => ids.filter(id => pendingIds.has(id)));
  }, [pendingTaskIds]);

  useEffect(() => {
    return () => {
      Object.values(eventSourcesRef.current).forEach(source => source.close());
      eventSourcesRef.current = {};
    };
  }, []);

  const watchTaskEvents = (id: string) => {
    if (eventSourcesRef.current[id]) return;
    const source = new EventSource(taskEventsUrl(id));
    eventSourcesRef.current[id] = source;

    const closeSource = () => {
      source.close();
      delete eventSourcesRef.current[id];
    };

    source.onmessage = (event) => {
      let payload: { type?: string; count?: number; message?: string; status?: string };
      try {
        payload = JSON.parse(event.data);
      } catch {
        return;
      }

      if (payload.type === 'queued') {
        load();
        return;
      }
      if (payload.type === 'started') {
        showToast('排队任务已开始执行', 'info');
        load();
        return;
      }
      if (payload.type === 'new_image') {
        showToast(`已采集 ${payload.count || 1} 张截图`, 'info');
        load();
        return;
      }
      if (payload.type === 'error') {
        showToast(payload.message || '任务执行失败', 'error');
        return;
      }
      if (payload.type === 'done') {
        closeSource();
        showToast(payload.status === 'failed' ? '任务已失败' : '任务已完成', payload.status === 'failed' ? 'error' : 'success');
        load();
      }
    };

    source.onerror = () => {
      closeSource();
    };
  };

  const handleRun = async (id: string, retry = false) => {
    setRunningId(id);
    try {
      const payload = deviceId ? { device_id: deviceId } : {};
      const response = retry ? await retryTask(id, payload) : await runTask(id, payload);
      const status = response.data?.status;
      if (retry) {
        showToast(status === 'queued' ? '重试已加入队列，等待当前任务完成' : '重试已启动，后台正在采集截图', 'success');
      } else {
        showToast(status === 'queued' ? '任务已加入队列，等待当前任务完成' : '任务已启动，后台正在采集截图', 'success');
      }
      watchTaskEvents(id);
      load();
    } catch {
      // api 拦截器已弹出错误 Toast
    } finally {
      setRunningId(null);
    }
  };

  const toggleTaskSelection = (id: string, checked: boolean) => {
    setSelectedTaskIds(ids => {
      if (checked) return ids.includes(id) ? ids : [...ids, id];
      return ids.filter(item => item !== id);
    });
  };

  const toggleAllPending = (checked: boolean) => {
    setSelectedTaskIds(checked ? pendingTaskIds : []);
  };

  const handleRunSelected = async () => {
    const ids = selectedTaskIds.filter(id => pendingTaskIds.includes(id));
    if (ids.length === 0) return;

    setBulkStarting(true);
    try {
      const payload = deviceId ? { device_id: deviceId } : {};
      const results = await Promise.allSettled(
        ids.map(id => runTask(id, payload).then(response => {
          watchTaskEvents(id);
          return response;
        }))
      );
      const successCount = results.filter(result => result.status === 'fulfilled').length;
      if (successCount > 0) {
        showToast(`${successCount} 个任务已提交，系统会按队列逐个执行`, 'success');
      }
      setSelectedTaskIds([]);
      load();
    } finally {
      setBulkStarting(false);
    }
  };

  const beginEditName = (task: any) => {
    setEditingTaskId(task.id);
    setEditingName(task.name || '');
  };

  const cancelEditName = () => {
    setEditingTaskId(null);
    setEditingName('');
  };

  const saveTaskName = async (id: string) => {
    const name = editingName.trim();
    if (!name) {
      showToast('任务名称不能为空', 'warning');
      return;
    }
    setSavingTaskId(id);
    try {
      await updateTask(id, { name });
      showToast('任务名称已更新', 'success');
      cancelEditName();
      load();
    } finally {
      setSavingTaskId(null);
    }
  };

  return (
    <div className="animate-fade-in">
      <div className="page-header" style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between' }}>
        <div>
          <h1>任务管理</h1>
          <p>管理并执行竞品截图采集任务</p>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {hasRole('operator') && (
            <button
              className="btn-secondary btn-sm"
              onClick={handleRunSelected}
              disabled={bulkStarting || selectedTaskIds.length === 0}
            >
              {bulkStarting ? '提交中...' : `启动选中${selectedTaskIds.length ? ` (${selectedTaskIds.length})` : ''}`}
            </button>
          )}
          <button className="btn-secondary btn-sm" onClick={load} disabled={loading}>
            {loading ? '刷新中...' : '刷新'}
          </button>
        </div>
      </div>

      {hasRole('operator') && (
        <div className="task-device-toolbar">
          <label>
            <span>采集设备</span>
            <select value={deviceId} onChange={(event) => setDeviceId(event.target.value)}>
              <option value="">自动分配</option>
              {devices.map(device => (
                <option key={device.id} value={device.id} disabled={device.status !== 'online'}>
                  {device.name || device.serial} · {device.status}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}

      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-lg)',
          overflow: 'hidden',
        }}
      >
        {loading && tasks.length === 0 ? (
          <div style={{ padding: 40 }}>
            {[1, 2, 3].map(i => (
              <div key={i} style={{ display: 'flex', gap: 16, marginBottom: 20, alignItems: 'center' }}>
                <div className="skeleton" style={{ width: 60, height: 16 }} />
                <div className="skeleton" style={{ width: 120, height: 16 }} />
                <div className="skeleton" style={{ width: 100, height: 16 }} />
                <div className="skeleton" style={{ width: 80, height: 16 }} />
                <div className="skeleton" style={{ width: 60, height: 16 }} />
              </div>
            ))}
          </div>
        ) : tasks.length === 0 ? (
          <div
            style={{
              textAlign: 'center',
              padding: '80px 0',
              color: 'var(--text-tertiary)',
            }}
          >
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" style={{ marginBottom: 16, opacity: 0.5 }}>
              <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
              <line x1="16" y1="2" x2="16" y2="6" />
              <line x1="8" y1="2" x2="8" y2="6" />
              <line x1="3" y1="10" x2="21" y2="10" />
            </svg>
            <p>暂无任务记录</p>
          </div>
        ) : (
          <table className="admin-tasks-table">
            <colgroup>
              <col style={{ width: 44 }} />
              <col className="task-col-id" />
              <col className="task-col-name" />
              <col className="task-col-keyword" />
              <col className="task-col-owner" />
              <col className="task-col-run" />
              <col className="task-col-completed" />
              <col className="task-col-status" />
              <col className="task-col-actions" />
            </colgroup>
            <thead>
              <tr>
                <th>
                  {hasRole('operator') && (
                    <input
                      aria-label="选择全部待执行任务"
                      type="checkbox"
                      checked={pendingTaskIds.length > 0 && selectedTaskIds.length === pendingTaskIds.length}
                      onChange={event => toggleAllPending(event.target.checked)}
                      style={{ width: 16, height: 16 }}
                    />
                  )}
                </th>
                <th>ID</th>
                <th>任务名称</th>
                <th>关键词</th>
                <th>归属</th>
                <th>运行</th>
                <th>完成时间</th>
                <th>状态</th>
                <th style={{ textAlign: 'right' }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {tasks.map(t => (
                <tr key={t.id}>
                  <td>
                    {hasRole('operator') && t.status === 'pending' && (
                      <input
                        aria-label={`选择任务 ${t.name || t.id}`}
                        type="checkbox"
                        checked={selectedTaskIds.includes(t.id)}
                        onChange={event => toggleTaskSelection(t.id, event.target.checked)}
                        style={{ width: 16, height: 16 }}
                      />
                    )}
                  </td>
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
                      {t.id?.slice(0, 8)}
                    </code>
                  </td>
                  <td className="task-name-cell" title={t.name}>
                    {editingTaskId === t.id ? (
                      <input
                        aria-label="任务名称"
                        value={editingName}
                        onChange={event => setEditingName(event.target.value)}
                        onKeyDown={event => {
                          if (event.key === 'Enter') saveTaskName(t.id);
                          if (event.key === 'Escape') cancelEditName();
                        }}
                        autoFocus
                        maxLength={120}
                        style={{ width: '100%', minWidth: 0 }}
                      />
                    ) : (
                      <span>{t.name}</span>
                    )}
                  </td>
                  <td className="task-keyword-cell">
                    <span
                      style={{
                        fontSize: '0.8125rem',
                        color: 'var(--text-secondary)',
                        background: 'var(--bg-tertiary)',
                        padding: '2px 10px',
                        borderRadius: 'var(--radius-pill)',
                      }}
                      title={t.keyword}
                    >
                      {t.keyword}
                    </span>
                  </td>
                  <td>
                    <div className="table-title-cell">
                      <span>{t.created_by_name || '-'}</span>
                      <small>{t.approved_by_name || t.run_by_name || '-'}</small>
                    </div>
                  </td>
                  <td title={t.failure_reason || t.device_serial || ''}>
                    <div className="table-title-cell">
                      <span>{t.attempt_count || 0} 次</span>
                      <small>{t.device_serial || t.failure_reason || '-'}</small>
                    </div>
                  </td>
                  <td title={t.completed_at || ''}>{formatCompletedAt(t.completed_at)}</td>
                  <td><StatusBadge status={t.status} /></td>
                  <td className="task-actions-cell" style={{ textAlign: 'right' }}>
                    <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                      {editingTaskId === t.id ? (
                        <>
                          <button className="btn-sm" onClick={() => saveTaskName(t.id)} disabled={savingTaskId === t.id}>
                            {savingTaskId === t.id ? '保存中...' : '保存'}
                          </button>
                          <button className="btn-secondary btn-sm" onClick={cancelEditName} disabled={savingTaskId === t.id}>
                            取消
                          </button>
                        </>
                      ) : (
                        <>
                          <Link
                            className="btn-sm task-result-button link-button"
                            to={`/admin/tasks/${t.id}/results`}
                          >
                            查看结果
                          </Link>
                          {hasRole('operator') && (
                            <button className="btn-secondary btn-sm" onClick={() => beginEditName(t)}>
                              改名
                            </button>
                          )}
                          {hasRole('operator') && t.status === 'pending' && (
                            <button
                              className="btn-sm"
                              onClick={() => handleRun(t.id)}
                              disabled={runningId === t.id}
                            >
                              {runningId === t.id ? '启动中...' : '启动'}
                            </button>
                          )}
                          {hasRole('operator') && t.status === 'failed' && (
                            <button
                              className="btn-sm"
                              onClick={() => handleRun(t.id, true)}
                              disabled={runningId === t.id}
                            >
                              {runningId === t.id ? '重试中...' : '重试'}
                            </button>
                          )}
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
