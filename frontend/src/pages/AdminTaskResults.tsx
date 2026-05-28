import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getTaskImages } from '../api';
import ImageCard from '../components/ImageCard';

function isVisibleTaskResult(result: any) {
  return result?.analysis?.status !== 'skipped';
}

export default function AdminTaskResults() {
  const { taskId } = useParams();
  const [taskImages, setTaskImages] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const visibleTaskImages = taskImages.filter(isVisibleTaskResult);

  useEffect(() => {
    let ignore = false;

    async function loadResults() {
      if (!taskId) return;
      setLoading(true);
      try {
        const { data } = await getTaskImages(taskId);
        if (!ignore) setTaskImages(data);
      } catch {
        if (!ignore) setTaskImages([]);
      } finally {
        if (!ignore) setLoading(false);
      }
    }

    loadResults();
    return () => {
      ignore = true;
    };
  }, [taskId]);

  return (
    <div className="animate-fade-in">
      <div className="page-header" style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16 }}>
        <div>
          <h1>任务结果</h1>
          <p>任务 {taskId?.slice(0, 8)} 的截图和分析内容</p>
        </div>
        <Link className="btn-secondary btn-sm link-button" to="/admin/tasks">
          返回任务列表
        </Link>
      </div>

      {loading ? (
        <div className="skeleton" style={{ height: 220, borderRadius: 'var(--radius-md)' }} />
      ) : visibleTaskImages.length === 0 ? (
        <div style={{ color: 'var(--text-tertiary)', padding: '32px 0' }}>
          暂无可展示的截图结果
        </div>
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
            gap: 20,
          }}
        >
          {visibleTaskImages.map((result, index) => (
            <ImageCard key={result.image?.id || index} result={result} />
          ))}
        </div>
      )}
    </div>
  );
}
