import { useEffect, useState } from 'react';
import { listDevices, refreshDevices } from '../api';
import { useToast } from '../components/Toast';

const labels: Record<string, string> = {
  online: '在线',
  offline: '离线',
  busy: '占用中',
  disabled: '禁用',
};

export default function AdminDevices() {
  const { showToast } = useToast();
  const [devices, setDevices] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await listDevices();
      setDevices(data);
    } finally {
      setLoading(false);
    }
  };

  const refresh = async () => {
    const { data } = await refreshDevices();
    const nextDevices = data.devices || [];
    setDevices(nextDevices);
    const hasWorkerDevice = nextDevices.some((device: any) => (
      device.status === 'online' && String(device.notes || '').startsWith('worker:')
    ));
    if (data.adb_available) {
      showToast('设备状态已刷新', 'success');
    } else if (hasWorkerDevice) {
      showToast('本地设备机在线，已刷新设备状态', 'success');
    } else {
      showToast('未检测到本机 adb，已展示现有设备记录', 'warning');
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="animate-fade-in">
      <div className="page-header watch-header">
        <div>
          <h1>设备管理</h1>
          <p>查看 Android 设备状态和当前占用任务</p>
        </div>
        <button className="btn-sm" onClick={refresh}>刷新设备</button>
      </div>
      <div className="table-shell">
        {loading ? (
          <div style={{ padding: 24 }}><div className="skeleton" style={{ height: 120 }} /></div>
        ) : devices.length === 0 ? (
          <div className="empty-state">暂无设备记录</div>
        ) : (
          <table>
            <thead>
              <tr>
                <th>序列号</th>
                <th>名称</th>
                <th>状态</th>
                <th>当前运行</th>
                <th>最近心跳</th>
                <th>备注</th>
              </tr>
            </thead>
            <tbody>
              {devices.map(device => (
                <tr key={device.id}>
                  <td><code>{device.serial}</code></td>
                  <td>{device.name || '-'}</td>
                  <td>{labels[device.status] || device.status}</td>
                  <td>{device.current_task_run_id ? device.current_task_run_id.slice(0, 8) : '-'}</td>
                  <td>{device.last_seen_at ? new Date(device.last_seen_at).toLocaleString('zh-CN') : '-'}</td>
                  <td>{device.notes || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
