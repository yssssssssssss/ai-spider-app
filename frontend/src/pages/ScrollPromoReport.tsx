import { useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { imageFileUrl, listTaskRuns } from '../api';

function DetectionCard({ item, title }: { item: any; title: string }) {
  return (
    <article className="promo-report-card">
      <div className="promo-report-card-head">
        <strong>{title}</strong>
        <span className={`badge ${item.promo_present ? 'badge-completed' : 'badge-pending'}`}>
          {item.promo_present ? item.promo_state : '未发现贴片'}
        </span>
      </div>
      {item.image_id ? <img src={imageFileUrl(item.image_id)} alt={title} /> : <div className="empty-state">图片 ID 未记录</div>}
      <dl>
        <div><dt>促销贴片</dt><dd>{item.promo_present ? '存在' : '不存在'}</dd></div>
        <div><dt>关闭按钮</dt><dd>{item.close_button_below_promo ? '贴片正下方存在' : '未发现'}</dd></div>
        {item.promo_confidence_threshold != null && <div><dt>静态置信度阈值</dt><dd>{Math.round(Number(item.promo_confidence_threshold) * 100)}%</dd></div>}
        {item.promo_confidence_passed != null && <div><dt>置信度判断</dt><dd>{item.promo_confidence_passed ? '通过' : '未通过'}</dd></div>}
        {item.promo_width_norm != null && <div><dt>过程贴片宽度</dt><dd>{item.promo_width_norm}</dd></div>}
        {item.baseline_promo_width_norm != null && <div><dt>静态最大宽度</dt><dd>{item.baseline_promo_width_norm}</dd></div>}
        {item.baseline_promo_width_norm != null && <div><dt>收起宽度阈值</dt><dd>{(Number(item.baseline_promo_width_norm) * 2 / 3).toFixed(2)}</dd></div>}
        {item.width_ratio_to_baseline != null && <div><dt>宽度比例</dt><dd>{Number(item.width_ratio_to_baseline).toFixed(4)}</dd></div>}
        {item.collapsed_by_width != null && <div><dt>收起判断</dt><dd>{item.collapsed_by_width ? '是' : '否'}</dd></div>}
        <div><dt>置信度</dt><dd>{Math.round(Number(item.confidence || 0) * 100)}%</dd></div>
      </dl>
    </article>
  );
}

export default function ScrollPromoReport() {
  const { taskId } = useParams();
  const [params, setParams] = useSearchParams();
  const [runs, setRuns] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!taskId) return;
    setLoading(true);
    listTaskRuns(taskId)
      .then(({ data }) => setRuns(data.filter((run: any) => run.result_json?.summary)))
      .finally(() => setLoading(false));
  }, [taskId]);

  const selectedRun = useMemo(() => {
    const runId = params.get('runId');
    return runs.find(run => run.id === runId) || runs[0];
  }, [runs, params]);
  const report = selectedRun?.result_json;
  const staticFrames = report?.step2?.frames || [];
  const motionFrames = report?.step3?.detections || [];
  const summary = report?.summary;

  return (
    <div className="animate-fade-in">
      <div className="page-header promo-report-header">
        <div>
          <h1>滑动贴片报告</h1>
          <p>任务 {taskId?.slice(0, 8)} 的静态基准、过程帧和收起态结论</p>
        </div>
        <Link className="btn-secondary btn-sm link-button" to={`/admin/tasks/${taskId}/results`}>返回任务结果</Link>
      </div>

      {runs.length > 0 && (
        <label className="promo-report-run-select">
          <span>运行记录</span>
          <select value={selectedRun?.id || ''} onChange={event => setParams({ runId: event.target.value })}>
            {runs.map(run => <option key={run.id} value={run.id}>第 {run.attempt_no} 次 · {run.status}</option>)}
          </select>
        </label>
      )}

      {loading ? <div className="skeleton" style={{ height: 220 }} /> : !report ? (
        <div className="empty-state">该运行暂无滑动贴片报告</div>
      ) : (
        <>
          <section className="promo-report-summary">
            <h2>汇总结论</h2>
            <div className="promo-conclusion-stack">
              <article className="promo-conclusion-group">
                <div className="promo-conclusion-result">
                  <span>静态贴片</span>
                  <strong className={summary.static_promo_present ? 'positive' : 'negative'}>
                    {summary.static_promo_present ? '存在' : '不存在'}
                  </strong>
                </div>
                <div className="promo-conclusion-metrics two-columns">
                  <div><span>静态帧数量</span><strong>{staticFrames.length} 张</strong></div>
                  <div><span>静态上滑间隔</span><strong>{report.step2?.static_scroll_distance_px || 0}px</strong></div>
                </div>
              </article>

              <article className="promo-conclusion-group">
                <div className="promo-conclusion-result">
                  <span>静态关闭按钮</span>
                  <strong className={summary.static_close_button_present ? 'positive' : 'negative'}>
                    {summary.static_close_button_present ? '存在' : '不存在'}
                  </strong>
                </div>
                <div className="promo-conclusion-metrics two-columns">
                  <div><span>静态置信度阈值</span><strong>{Math.round(Number(report.step2?.confidence_threshold || 0) * 100)}%</strong></div>
                  <div><span>静态最大宽度</span><strong>{summary.baseline_promo_width_norm || '-'}</strong></div>
                </div>
              </article>

              <article className="promo-conclusion-group">
                <div className="promo-conclusion-result">
                  <span>收起态</span>
                  <strong className={summary.collapsed_frame_count > 0 ? 'positive' : 'negative'}>
                    {summary.collapsed_frame_count > 0 ? '存在' : '不存在'}
                  </strong>
                </div>
                <div className="promo-conclusion-metrics four-columns">
                  <div><span>收起宽度阈值</span><strong>{summary.baseline_promo_width_norm ? (Number(summary.baseline_promo_width_norm) * Number(summary.collapse_width_ratio_threshold || 2 / 3)).toFixed(2) : '-'}</strong></div>
                  <div><span>过程候选帧</span><strong>{report.step3?.candidate_frame_count || 0} 张</strong></div>
                  <div><span>过程分析帧</span><strong>{motionFrames.length} 张</strong></div>
                  <div><span>收起态数量</span><strong>{summary.collapsed_frame_count || 0} 张</strong></div>
                </div>
              </article>
            </div>
            <div className="promo-rule-list">
              <p><strong>静态判断：</strong>每帧需同时满足“检测为存在”且置信度 ≥ {Math.round(Number(report.step2?.confidence_threshold || 0) * 100)}%；三帧任一通过则汇总为存在。静态宽度取通过帧中的最大值。</p>
              <p><strong>收起规则：</strong>过程贴片宽度严格小于静态最大宽度 × {(Number(summary.collapse_width_ratio_threshold || 2 / 3) * 100).toFixed(1)}%；当前阈值为 {summary.baseline_promo_width_norm ? (Number(summary.baseline_promo_width_norm) * Number(summary.collapse_width_ratio_threshold || 2 / 3)).toFixed(2) : '-'}。</p>
            </div>
          </section>

          <section className="promo-report-section">
            <h2>静态帧判断</h2>
            <p>三张静态帧之间分别上滑 600px。每帧先执行右下贴片和正下方关闭按钮检测，再进行置信度判断；三次判断任一通过，则静态汇总结论为 true。</p>
            <div className="promo-report-grid">
              {staticFrames.map((item: any, index: number) => <DetectionCard key={item.annotated_file || index} item={item} title={`静态帧 ${index + 1}`} />)}
            </div>
          </section>

          <section className="promo-report-section">
            <h2>滑动过程帧判断</h2>
            <p>2 秒上滑，从真实运动开始后 0.5 秒起截取 1 秒，10 FPS 得到 10 张候选帧，再最多筛选 6 张分析。</p>
            <div className="promo-report-grid">
              {motionFrames.map((item: any, index: number) => <DetectionCard key={item.annotated_file || index} item={item} title={`过程帧 ${index + 1}`} />)}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
