import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  addComparisonBasketItem,
  createComparisonAssetFromImage,
  exportTaskUrl,
  getTaskImages,
  getTaskRunLogs,
  listTaskRuns,
} from '../api';
import ImageCard from '../components/ImageCard';
import { useAuth } from '../auth';
import { useToast } from '../components/Toast';

function isVisibleTaskResult(result: any) {
  if (String(result?.image?.scenario || '').includes('促销贴片')) return true;
  if (String(result?.image?.scenario || '').includes('新品楼层规范检查')) return true;
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
  const [selectedImageIds, setSelectedImageIds] = useState<string[]>([]);
  const [addingCompare, setAddingCompare] = useState(false);
  const [loading, setLoading] = useState(true);
  const visibleTaskImages = taskImages.filter(isVisibleTaskResult);
  const currentRun = runs.find(run => run.id === runId) || runs[0];
  const goalValidation = currentRun?.goal_validation_json;
  const runReport = currentRun?.result_json;
  const promotionReport = runReport?.report_type === 'scroll_promo' || runReport?.step3 ? runReport : null;
  const promotionSummary = promotionReport?.summary;
  const floorAuditReport = runReport?.report_type === 'jd_new_floor_audit' ? runReport : null;
  const floorAuditSummary = floorAuditReport?.summary;
  const secondaryTabSummary = floorAuditReport?.secondary_tab_audit?.summary;

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

  const toggleImage = (id: string) => {
    setSelectedImageIds(prev => prev.includes(id) ? prev.filter(item => item !== id) : [...prev, id]);
  };

  const selectAllVisible = () => {
    setSelectedImageIds(visibleTaskImages.map(result => result.image.id));
  };

  const addSelectedToCompare = async () => {
    if (!selectedImageIds.length) return;
    setAddingCompare(true);
    try {
      for (const imageId of selectedImageIds) {
        const { data: asset } = await createComparisonAssetFromImage({ image_id: imageId });
        await addComparisonBasketItem({ asset_id: asset.id });
      }
      showToast(`已加入对比篮 ${selectedImageIds.length} 张截图`, 'success');
      setSelectedImageIds([]);
    } catch {
      // api 拦截器已弹出错误 Toast
    } finally {
      setAddingCompare(false);
    }
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
          {promotionReport && (
            <Link className="btn-sm link-button" to={`/admin/tasks/${taskId}/scroll-promo-report?runId=${currentRun?.id || ''}`}>
              滑动贴片报告
            </Link>
          )}
          {floorAuditReport && (
            <Link className="btn-sm link-button" style={{ background: '#c96f00' }} to={`/admin/tasks/${taskId}/jd-new-floor-report?runId=${currentRun?.id || ''}`}>
              新品楼层报告
            </Link>
          )}
          <Link className="btn-secondary btn-sm link-button" to="/admin/tasks">
            返回任务列表
          </Link>
          <Link className="btn-sm link-button" to="/compare">
            对比工作台
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
          {Array.isArray(runReport?.model_calls) && runReport.model_calls.length > 0 && <details>
            <summary>手机控制模型调用记录</summary>
            {runReport.model_calls.map((call: any, index: number) => <p key={index}>
              {call.endpoint_host} · 请求 {call.requested_model} · 返回 {call.response_model || '接口未提供模型名称'} · {call.status} · {call.duration_ms} ms
            </p>)}
          </details>}
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
          {promotionSummary && (
            <div className="goal-validation-panel">
              <div className="goal-validation-head">
                <span>滑动贴片结论</span>
                <strong>{promotionSummary.collapsed_frame_count > 0 ? '检测到收起态' : '未检测到收起态'}</strong>
              </div>
              <p>
                静态帧贴片：{promotionSummary.static_promo_present ? '存在' : '未发现'}；
                静态帧关闭按钮：{promotionSummary.static_close_button_present ? '存在' : '未发现'}；
                收起判定：宽度 &lt; 基准的 2/3；
                过程帧 {promotionReport.step3?.selected_frame_count || 0} 张，发现贴片 {promotionSummary.motion_promo_frame_count || 0} 张，
                收起态 {promotionSummary.collapsed_frame_count || 0} 张。
              </p>
            </div>
          )}
          {floorAuditSummary && (
            <div className="goal-validation-panel">
              <div className="goal-validation-head">
                <span>腰部楼层巡查结论</span>
                <strong>{floorAuditSummary.status === 'pass' ? '通过' : floorAuditSummary.status === 'fail' ? '存在不合规项' : '需要复核'}</strong>
              </div>
              <p>
                通过 {floorAuditSummary.counts?.pass || 0} 项；
                不通过 {floorAuditSummary.counts?.fail || 0} 项；
                待确认 {floorAuditSummary.counts?.uncertain || 0} 项；
                不适用 {floorAuditSummary.counts?.not_applicable || 0} 项。
              </p>
            </div>
          )}
          {secondaryTabSummary && (
            <div className="goal-validation-panel">
              <div className="goal-validation-head">
                <span>二级tab组件巡查结论</span>
                <strong>{secondaryTabSummary.status === 'pass' ? '通过' : secondaryTabSummary.status === 'fail' ? '存在不合规项' : '需要复核'}</strong>
              </div>
              <p>
                通过 {secondaryTabSummary.counts?.pass || 0} 项；
                不通过 {secondaryTabSummary.counts?.fail || 0} 项；
                待确认 {secondaryTabSummary.counts?.uncertain || 0} 项。
              </p>
            </div>
          )}
        </div>
      )}

      {!loading && visibleTaskImages.length > 0 && (
        <div className="compare-select-toolbar">
          <div>
            <strong>已选 {selectedImageIds.length} 张</strong>
            <span>选择截图加入对比篮</span>
          </div>
          <div className="compare-toolbar-actions">
            <button type="button" className="btn-secondary btn-sm" onClick={selectAllVisible}>
              全选本页
            </button>
            <button type="button" className="btn-secondary btn-sm" onClick={() => setSelectedImageIds([])} disabled={!selectedImageIds.length}>
              取消选择
            </button>
            <button type="button" className="btn-sm" onClick={addSelectedToCompare} disabled={!selectedImageIds.length || addingCompare}>
              {addingCompare ? '加入中...' : '加入对比篮'}
            </button>
          </div>
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
            <div key={result.image?.id || index} className={`compare-select-card ${selectedImageIds.includes(result.image?.id) ? 'selected' : ''}`}>
              <button
                type="button"
                className="compare-select-toggle"
                onClick={(event) => {
                  event.stopPropagation();
                  toggleImage(result.image.id);
                }}
              >
                {selectedImageIds.includes(result.image?.id) ? '已选' : '选择'}
              </button>
              <ImageCard result={result} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
