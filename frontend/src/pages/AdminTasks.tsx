import { useEffect, useState } from 'react';
import { listAdminTasks, runTask } from '../api';

export default function AdminTasks() {
  const [tasks, setTasks] = useState<any[]>([]);

  const load = async () => {
    const { data } = await listAdminTasks();
    setTasks(data);
  };

  useEffect(() => { load(); }, []);

  const handleRun = async (id: string) => {
    await runTask(id);
    load();
  };

  return (
    <div>
      <h1>后台 - 任务管理</h1>
      <table border={1} cellPadding={8}>
        <thead><tr><th>ID</th><th>名称</th><th>关键词</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          {tasks.map(t => (
            <tr key={t.id}>
              <td>{t.id.slice(0, 8)}</td>
              <td>{t.name}</td>
              <td>{t.keyword}</td>
              <td>{t.status}</td>
              <td>
                {t.status === 'pending' && <button onClick={() => handleRun(t.id)}>启动</button>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
