import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { exportWatchPlanUrl, getWatchPlan, pauseWatchPlan, resumeWatchPlan, runWatchPlanNow } from '../api';
import { useAuth } from '../auth';
import ImageCard from '../components/ImageCard';
import { useToast } from '../components/Toast';

function formatDate(value?: string | null) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  });
}

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

function cycleLabel(value?: string) {
  const labels: Record<string, string> = {
    daily: '每天',
    weekly: '每周',
    monthly: '每月',
  };
  return labels[value || 'daily'] || '每天';
}

const fieldLabels: Record<string, string> = {
  added: '新增内容',
  removed: '消失内容',
  strengthened: '强化内容',
  weakened: '弱化内容',
  note: '说明',
  continuous_actions: '持续动作',
  key_changes: '关键变化',
  stable_modules: '稳定模块',
  short_term_campaigns: '短期活动',
  design_takeaways: '设计启示',
  ops_takeaways: '运营启示',
  period_days: '周期天数',
  summary_count: '日报数量',
  name: '名称',
};

function labelFor(key: string) {
  return fieldLabels[key] || key.replace(/_/g, ' ');
}

function isEmptyValue(value: any): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === 'string') return value.trim() === '';
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === 'object') return Object.keys(value).length === 0;
  return false;
}

function scalarText(value: any) {
  if (typeof value === 'boolean') return value ? '是' : '否';
  return String(value);
}

function ReadableValue({ value }: { value: any }) {
  if (isEmptyValue(value)) {
    return <p className="structured-empty">暂无</p>;
  }

  if (Array.isArray(value)) {
    const items = value.filter(item => !isEmptyValue(item));
    if (items.length === 0) return <p className="structured-empty">暂无</p>;
    if (items.every(item => typeof item !== 'object' || item === null)) {
      return (
        <div className="structured-chip-list">
          {items.map((item, index) => (
            <span className="structured-chip" key={`${item}-${index}`}>
              {scalarText(item)}
            </span>
          ))}
        </div>
      );
    }
    return (
      <div className="structured-card-list">
        {items.map((item, index) => (
          <div className="structured-subcard" key={index}>
            <ReadableValue value={item} />
          </div>
        ))}
      </div>
    );
  }

  if (typeof value === 'object') {
    const entries = Object.entries(value).filter(([key, entryValue]) => key !== 'mock' && !isEmptyValue(entryValue));
    if (entries.length === 0) return <p className="structured-empty">暂无</p>;
    return (
      <div className="structured-fields">
        {entries.map(([key, entryValue]) => (
          <div className="structured-field" key={key}>
            <div className="structured-label">{labelFor(key)}</div>
            <ReadableValue value={entryValue} />
          </div>
        ))}
      </div>
    );
  }

  return <p className="structured-text">{scalarText(value)}</p>;
}

function StructuredPreview({ value }: { value: any }) {
  if (isEmptyValue(value)) return <p>暂无结构化内容</p>;
  return (
    <div className="structured-preview">
      <ReadableValue value={value} />
    </div>
  );
}

export default function AdminWatchPlanDetail() {
  const { planId } = useParams();
  const { showToast } = useToast();
  const { hasRole } = useAuth();
  const [detail, setDetail] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);

  const load = async () => {
    if (!planId) return;
    setLoading(true);
    try {
      const { data } = await getWatchPlan(planId);
      setDetail(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [planId]);

  const handleRun = async () => {
    if (!planId) return;
    setBusy(true);
    try {
      await runWatchPlanNow(planId);
      showToast('观察运行已启动', 'success');
      await load();
    } catch {
      // API 拦截器会提示错误
    } finally {
      setBusy(false);
    }
  };

  const handleToggle = async () => {
    if (!planId || !detail?.plan) return;
    setBusy(true);
    try {
      if (detail.plan.status === 'active') {
        await pauseWatchPlan(planId);
        showToast('观察计划已暂停', 'success');
      } else {
        await resumeWatchPlan(planId);
        showToast('观察计划已恢复', 'success');
      }
      await load();
    } catch {
      // API 拦截器会提示错误
    } finally {
      setBusy(false);
    }
  };

  const download = async (format: 'json' | 'xlsx') => {
    if (!planId) return;
    setDownloading(format);
    try {
      const response = await fetch(exportWatchPlanUrl(planId, format));
      if (!response.ok) throw new Error(await response.text());
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `watch-plan-${planId}.${format}`;
      link.click();
      URL.revokeObjectURL(url);
      showToast('导出已开始下载', 'success');
    } catch {
      showToast('导出失败', 'error');
    } finally {
      setDownloading(null);
    }
  };

  if (loading && !detail) {
    return <div className="skeleton" style={{ height: 320, borderRadius: 'var(--radius-md)' }} />;
  }

  if (!detail?.plan) {
    return (
      <div className="empty-state">
        <p>未找到观察计划</p>
      </div>
    );
  }

  const {
    plan,
    latest_run,
    latest_success_run,
    latest_snapshot,
    latest_summary,
    period_reports = [],
    recent_runs = [],
  } = detail;
  const reportsByDays = new Map(period_reports.map((report: any) => [report.period_days, report]));

  return (
    <div className="animate-fade-in">
      <div className="page-header watch-header">
        <div>
          <h1>{plan.name}</h1>
          <p>{plan.target_app} / {plan.target_page}</p>
        </div>
        <div className="watch-header-actions">
          <button className="btn-secondary btn-sm" onClick={() => download('json')} disabled={!!downloading}>{downloading === 'json' ? '下载中...' : 'JSON'}</button>
          <button className="btn-secondary btn-sm" onClick={() => download('xlsx')} disabled={!!downloading}>{downloading === 'xlsx' ? '下载中...' : 'Excel'}</button>
          <Link className="btn-secondary btn-sm link-button" to="/admin/watch-plans">
            返回列表
          </Link>
          {hasRole('operator') && (
            <>
              <button className="btn-secondary btn-sm" onClick={handleToggle} disabled={busy}>
                {plan.status === 'active' ? '暂停' : '恢复'}
              </button>
              <button className="btn-sm" onClick={handleRun} disabled={busy}>
                {busy ? '处理中...' : '立即运行'}
              </button>
            </>
          )}
        </div>
      </div>

      <section className="watch-overview">
        <div className="watch-meta-panel">
          <div className="watch-meta-row"><span>状态</span><StatusBadge status={plan.status} /></div>
          <div className="watch-meta-row"><span>执行周期</span><strong>{cycleLabel(plan.schedule_cycle)}</strong></div>
          <div className="watch-meta-row"><span>执行时间</span><strong>{String(plan.schedule_time).slice(0, 5)}</strong></div>
          <div className="watch-meta-row"><span>开始日期</span><strong>{plan.schedule_start_date || '-'}</strong></div>
          <div className="watch-meta-row"><span>结束日期</span><strong>{plan.schedule_end_date || '-'}</strong></div>
          <div className="watch-meta-row"><span>最近运行</span><strong>{formatDate(plan.last_run_at)}</strong></div>
          <div className="watch-meta-row"><span>最近运行状态</span>{latest_run ? <StatusBadge status={latest_run.status} /> : <strong>-</strong>}</div>
          <div className="watch-meta-row"><span>累计运行</span><strong>{plan.run_count || 0} 次</strong></div>
          <div className="watch-meta-row"><span>最近成功</span><strong>{formatDate(plan.latest_success_run_at)}</strong></div>
          <div className="watch-meta-row"><span>创建人</span><strong>{plan.created_by_name || '-'}</strong></div>
          {plan.pause_reason && <p className="watch-warning">{plan.pause_reason}</p>}
        </div>
        <div className="watch-meta-panel">
          <h3>进入路径</h3>
          <p>{plan.entry_instruction}</p>
          <h3 style={{ marginTop: 20 }}>关注问题</h3>
          <p>{plan.focus_question || '未设置关注问题'}</p>
        </div>
      </section>

      <section className="watch-section">
        <div className="section-title-row">
          <h2>最新成功观察</h2>
          {latest_success_run && <span>运行日期 {latest_success_run.run_date}</span>}
        </div>
        {latest_snapshot ? (
          <div className="watch-snapshot-grid">
            <ImageCard result={latest_snapshot} />
            <div className="summary-panel">
              <h3>今日摘要</h3>
              <p>{latest_summary?.summary || '暂无日报摘要'}</p>
              <h3>设计摘要</h3>
              <p>{latest_summary?.design_summary || '暂无设计摘要'}</p>
              <h3>运营摘要</h3>
              <p>{latest_summary?.ops_summary || '暂无运营摘要'}</p>
              <h3>与昨日相比</h3>
              <StructuredPreview value={latest_summary?.changes_from_previous_json} />
            </div>
          </div>
        ) : (
          <div className="empty-state"><p>暂无有效观察截图</p></div>
        )}
      </section>

      <section className="watch-section">
        <div className="section-title-row">
          <h2>周期报告</h2>
        </div>
        <div className="report-grid">
          {[7, 30].map(days => {
            const report: any = reportsByDays.get(days);
            return (
              <article className="report-panel" key={days}>
                <h3>{days} 天报告</h3>
                <p>{report?.report || '暂无周期报告'}</p>
                {report?.structured_json && <StructuredPreview value={report.structured_json} />}
              </article>
            );
          })}
        </div>
      </section>

      <section className="watch-section">
        <div className="section-title-row">
          <h2>历史运行</h2>
        </div>
        <div className="table-shell">
          <table>
            <thead>
              <tr>
                <th>日期</th>
                <th>状态</th>
                <th>尝试</th>
                <th>截图</th>
                <th>有效</th>
                <th>完成时间</th>
              </tr>
            </thead>
            <tbody>
              {recent_runs.length === 0 ? (
                <tr><td colSpan={6}>暂无运行记录</td></tr>
              ) : recent_runs.map((run: any) => (
                <tr key={run.id}>
                  <td>{run.run_date}</td>
                  <td><StatusBadge status={run.status} /></td>
                  <td>{run.attempt_count}</td>
                  <td>{run.screenshot_count || 0}</td>
                  <td>{run.valid_snapshot_count || 0}</td>
                  <td>{formatDate(run.completed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
