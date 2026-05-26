import { useEffect, useState } from 'react';
import { listAdminRequests, approveRequest, rejectRequest } from '../api';

export default function AdminRequests() {
  const [requests, setRequests] = useState<any[]>([]);
  const [adminId] = useState('admin');

  const load = async () => {
    const { data } = await listAdminRequests();
    setRequests(data);
  };

  useEffect(() => { load(); }, []);

  const handleApprove = async (id: string) => {
    await approveRequest(id, { admin_id: adminId });
    load();
  };

  const handleReject = async (id: string) => {
    await rejectRequest(id, { admin_id: adminId });
    load();
  };

  return (
    <div>
      <h1>后台 - 需求汇总</h1>
      <table border={1} cellPadding={8}>
        <thead><tr><th>ID</th><th>App</th><th>场景</th><th>关键词</th><th>状态</th><th>操作</th></tr></thead>
        <tbody>
          {requests.map(r => (
            <tr key={r.id}>
              <td>{r.id.slice(0, 8)}</td>
              <td>{r.target_app}</td>
              <td>{r.target_scenario}</td>
              <td>{r.keywords?.join(', ')}</td>
              <td>{r.status}</td>
              <td>
                {r.status === 'pending' && (
                  <>
                    <button onClick={() => handleApprove(r.id)}>通过</button>
                    <button onClick={() => handleReject(r.id)}>拒绝</button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
