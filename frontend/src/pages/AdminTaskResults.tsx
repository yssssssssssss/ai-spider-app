import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { exportTaskUrl, getTaskImages, getTaskRunLogs, listTaskRuns } from '../api';
import ImageCard from '../components/ImageCard';
import { useAuth } from '../auth';
import { useToast } from '../components/Toast';

function isVisibleTaskResult(result: any) {
  return result?.analysis?.status !== 'skipped';
}

function validationLabel(status?: string) {
  if (status === 'matched') return '已覆盖';
  if (status === 'missing') return '缺失';
  if (status === 'uncertain') return '待确认';
  return '未校验';
}

export default function AdminTaskResults() {
  const { taskId } = useParams();
  const { hasRole } = useAuth();
  const { showToast } = useToast();
  const [taskImages, setTaskImages] = useState<any[]>([]);
  const [runs, setRuns] = useState<any[]>([]);
  const [runId, setRunId] = useState('');
  const [logs, setLogs] = useState('');
  const [downloading, setDownloading] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const visibleTaskImages = taskImages.filter(isVisibleTaskResult);
  const currentRun = runs.find(run => run.id === runId) || runs[0];
  const goalValidation = currentRun?.goal_validation_json;

  useEffect(() => {
    let ignore = false;

    async function loadResults() {
      if (!taskId) return;
      setLoading(true);
      try {
        const { data } = await getTaskImages(taskId, runId ? { run_id: runId } : undefined);
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
    listTaskRuns(taskId).then(({ data }) => setRuns(data)).catch(() => setRuns([]));
  }, [taskId]);

  const loadLogs = async (id: string) => {
    const { data } = await getTaskRunLogs(id);
    setLogs(data.logs || '');
  };

  const download = async (format: 'json' | 'xlsx' | 'zip') => {
    if (!taskId) return;
    setDownloading(format);
    try {
      const response = await fetch(exportTaskUrl(taskId, format));
      if (!response.ok) throw new Error(await response.text());
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `task-${taskId}.${format}`;
      link.click();
      URL.revokeObjectURL(url);
      showToast('导出已开始下载', 'success');
    } catch {
      showToast('导出失败', 'error');
    } finally {
      setDownloading(null);
    }
  };

  return (
    <div className="animate-fade-in">
      <div className="page-header" style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', gap: 16 }}>
        <div>
          <h1>任务结果</h1>
          <p>任务 {taskId?.slice(0, 8)} 的截图和分析内容</p>
        </div>
        <div className="watch-header-actions">
          <button className="btn-secondary btn-sm" onClick={() => download('json')} disabled={!!downloading}>{downloading === 'json' ? '下载中...' : 'JSON'}</button>
          <button className="btn-secondary btn-sm" onClick={() => download('xlsx')} disabled={!!downloading}>{downloading === 'xlsx' ? '下载中...' : 'Excel'}</button>
          {hasRole('operator') && (
            <button className="btn-secondary btn-sm" onClick={() => download('zip')} disabled={!!downloading}>{downloading === 'zip' ? '下载中...' : 'ZIP'}</button>
          )}
          <Link className="btn-secondary btn-sm link-button" to="/admin/tasks">
            返回任务列表
          </Link>
        </div>
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
          <div className="run-chip-row">
            {runs.map(run => (
              <button key={run.id} className="btn-secondary btn-sm" onClick={() => loadLogs(run.id)}>
                日志 {run.attempt_no}
              </button>
            ))}
          </div>
          {logs && <pre className="log-preview">{logs}</pre>}
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
            <ImageCard key={result.image?.id || index} result={result} />
          ))}
        </div>
      )}
    </div>
  );
}
