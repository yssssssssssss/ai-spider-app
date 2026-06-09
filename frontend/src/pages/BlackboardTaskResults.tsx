import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { blackboardImageFileUrl, getBlackboardTask, getBlackboardTaskImages, listBlackboardTaskRuns } from '../api';
import ImageCard from '../components/ImageCard';

function isVisibleTaskResult(result: any) {
  return result?.analysis?.status !== 'skipped';
}

function validationLabel(status?: string) {
  if (status === 'matched') return '已覆盖';
  if (status === 'missing') return '缺失';
  if (status === 'uncertain') return '待确认';
  return '未校验';
}

export default function BlackboardTaskResults() {
  const { taskId } = useParams();
  const [detail, setDetail] = useState<any>(null);
  const [taskImages, setTaskImages] = useState<any[]>([]);
  const [runs, setRuns] = useState<any[]>([]);
  const [runId, setRunId] = useState('');
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const visibleTaskImages = taskImages.filter(isVisibleTaskResult);
  const currentRun = runs.find(run => run.id === runId) || runs[0];
  const goalValidation = currentRun?.goal_validation_json;

  useEffect(() => {
    if (!taskId) return;
    getBlackboardTask(taskId)
      .then(({ data }) => {
        setDetail(data);
        setNotFound(false);
      })
      .catch(() => setNotFound(true));
  }, [taskId]);

  useEffect(() => {
    let ignore = false;

    async function loadResults() {
      if (!taskId) return;
      setLoading(true);
      try {
        const { data } = await getBlackboardTaskImages(taskId, runId ? { run_id: runId } : undefined);
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
  }, [taskId, runId]);

  useEffect(() => {
    if (!taskId) return;
    listBlackboardTaskRuns(taskId).then(({ data }) => setRuns(data)).catch(() => setRuns([]));
  }, [taskId]);

  if (notFound) {
    return (
      <div className="animate-fade-in">
        <div className="empty-state">
          <p>这个任务尚未发布到黑板报</p>
          <Link className="link-button btn-sm" to="/blackboard">返回黑板报</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="animate-fade-in">
      <div className="page-header" style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16 }}>
        <div>
          <h1>黑板报任务结果</h1>
          <p>
            {detail?.task?.name || `任务 ${taskId?.slice(0, 8)}`} · {[detail?.task?.target_app, detail?.task?.target_scenario].filter(Boolean).join(' / ')}
          </p>
        </div>
        <Link className="btn-secondary btn-sm link-button" to="/blackboard">
          返回黑板报
        </Link>
      </div>

      {runs.length > 0 && (
        <div className="run-history-panel">
          <label>
            <span>运行记录</span>
            <select value={runId} onChange={(event) => setRunId(event.target.value)}>
              <option value="">全部运行</option>
              {runs.map(run => (
                <option key={run.id} value={run.id}>
                  第 {run.attempt_no} 次 · {run.status}
                </option>
              ))}
            </select>
          </label>
          {goalValidation && (
            <div className="goal-validation-panel">
              <div className="goal-validation-head">
                <span>目标覆盖</span>
                <strong>{validationLabel(goalValidation.status)}</strong>
              </div>
              {goalValidation.reason && <p>{goalValidation.reason}</p>}
              {Array.isArray(goalValidation.goals) && (
                <div className="goal-chip-row">
                  {goalValidation.goals.map((goal: any, index: number) => (
                    <span key={`${goal.label}-${index}`} className={`goal-chip goal-chip-${goal.status || 'unknown'}`}>
                      {goal.label} · {validationLabel(goal.status)}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

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
            <ImageCard
              key={result.image?.id || index}
              result={result}
              imageUrl={blackboardImageFileUrl(result.image.id)}
            />
          ))}
        </div>
      )}
    </div>
  );
}
