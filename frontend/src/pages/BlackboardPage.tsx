import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { blackboardImageFileUrl, listBlackboard } from '../api';

function formatPublishedAt(value?: string | null) {
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

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    pending: '待执行',
    queued: '等待节点',
    running: '执行中',
    completed: '已完成',
    failed: '失败',
  };
  return labels[status] || status;
}

export default function BlackboardPage() {
  const [posts, setPosts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await listBlackboard();
      setPosts(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  return (
    <div className="animate-fade-in">
      <div className="page-header" style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16 }}>
        <div>
          <h1>黑板报</h1>
          <p>大家公开分享的竞品采集任务和完整结果</p>
        </div>
        <button className="btn-secondary btn-sm" onClick={load} disabled={loading}>
          {loading ? '刷新中...' : '刷新'}
        </button>
      </div>

      {loading && posts.length === 0 ? (
        <div className="skeleton" style={{ height: 220, borderRadius: 'var(--radius-md)' }} />
      ) : posts.length === 0 ? (
        <div className="empty-state">
          <p>暂无公开任务</p>
        </div>
      ) : (
        <div className="blackboard-grid">
          {posts.map(post => (
            <Link key={post.id} className="blackboard-card" to={`/blackboard/tasks/${post.task_id}`}>
              <div className="blackboard-thumb">
                {post.preview_image_id ? (
                  <img src={blackboardImageFileUrl(post.preview_image_id)} alt="任务预览截图" loading="lazy" />
                ) : (
                  <span>暂无截图</span>
                )}
              </div>
              <div className="blackboard-card-body">
                <div className="blackboard-card-topline">
                  <span>{statusLabel(post.task_status)}</span>
                  <small>{post.image_count || 0} 张截图</small>
                </div>
                <h3>{post.task_name || `${post.target_app || '任务'} · ${post.target_scenario || ''}`}</h3>
                <p>{[post.target_app, post.target_scenario, post.keyword].filter(Boolean).join(' / ')}</p>
                <div className="blackboard-meta">
                  <span>{post.published_by_name || '匿名用户'}</span>
                  <span>{formatPublishedAt(post.published_at)}</span>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
