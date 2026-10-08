import { useEffect, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { imageFileUrl, listTaskRuns } from '../api';

const statusMeta: Record<string, { label: string; className: string }> = {
  pass: { label: '通过', className: 'floor-status-pass' },
  fail: { label: '不通过', className: 'floor-status-fail' },
  uncertain: { label: '待确认', className: 'floor-status-uncertain' },
  not_applicable: { label: '不适用', className: 'floor-status-na' },
};

const checkDisplayNumbers: Record<string, string> = {
  '3.3': '1',
  '3.4': '2',
  '3.5': '3',
  '3.6': '4',
  '3.7': '5',
  '3.8': '6',
  '3.9': '7',
};

type BoundingBox = [number, number, number, number];

function boundingBox(value: unknown): BoundingBox | null {
  if (!Array.isArray(value) || value.length !== 4) return null;
  const box = value.map(Number);
  if (box.some(value => !Number.isFinite(value)) || box[2] <= box[0] || box[3] <= box[1]) return null;
  return box as BoundingBox;
}

function evidenceCrop(item: any, regions: any, imageWidth: number, imageHeight: number): BoundingBox {
  const region = boundingBox(regions?.[item.region]?.bbox_px) || [0, 0, imageWidth, imageHeight];
  const boxes = [region];
  for (const annotation of Array.isArray(item.annotations) ? item.annotations : []) {
    const box = boundingBox(annotation?.bbox_px);
    if (box) boxes.push(box);
  }

  const padding = Math.max(12, Math.round(Math.min(region[2] - region[0], region[3] - region[1]) * 0.025));
  return [
    Math.max(0, Math.floor(Math.min(...boxes.map(box => box[0])) - padding)),
    Math.max(0, Math.floor(Math.min(...boxes.map(box => box[1])) - padding)),
    Math.min(imageWidth, Math.ceil(Math.max(...boxes.map(box => box[2])) + padding)),
    Math.min(imageHeight, Math.ceil(Math.max(...boxes.map(box => box[3])) + padding)),
  ];
}

function yesNo(value: unknown) {
  if (value === true) return '是';
  if (value === false) return '否';
  return '待确认';
}

function Requirement({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="floor-requirement">
      <span>{label}</span>
      <strong className={value === true ? 'is-pass' : value === false ? 'is-fail' : ''}>{yesNo(value)}</strong>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: unknown }) {
  const text = typeof value === 'boolean' ? (value ? '有' : '无') : value ?? '待确认';
  return <div className="floor-requirement"><span>{label}</span><strong>{String(text)}</strong></div>;
}

function AnnotationLegend({ item, displayNumber }: { item: any; displayNumber: string }) {
  const annotations = Array.isArray(item.annotations) ? item.annotations : [];
  if (!annotations.length) {
    return <p className="floor-annotation-empty">本项无独立标注，仅展示{item.region || '分析'}区域裁图。</p>;
  }
  return (
    <div className="floor-annotation-legend" aria-label={`检查 ${displayNumber} 标注图例`}>
      {annotations.map((annotation: any, index: number) => (
        <span key={`${displayNumber}-${index}`}>
          <b>{displayNumber}-{index + 1}</b>
          {annotation.label || '未命名标注'}
        </span>
      ))}
    </div>
  );
}

function CheckEvidenceFigure({
  item,
  displayNumber,
  imageUrl,
  imageWidth,
  imageHeight,
  regions,
}: {
  item: any;
  displayNumber: string;
  imageUrl: string;
  imageWidth: number;
  imageHeight: number;
  regions: any;
}) {
  const crop = evidenceCrop(item, regions, imageWidth, imageHeight);
  const cropWidth = crop[2] - crop[0];
  const cropHeight = crop[3] - crop[1];
  const annotations = Array.isArray(item.annotations) ? item.annotations : [];
  const regionLabel = `${item.region || '分析'}区域`;
  const labelFontSize = Math.max(10, cropWidth / 52);
  const labelHeight = labelFontSize * 1.75;

  return (
    <figure className={`floor-check-evidence floor-check-evidence-${item.region || 'unknown'}`}>
      <figcaption>
        <span>检查 {displayNumber} · {regionLabel}证据</span>
        <small>{Math.round(cropWidth)} × {Math.round(cropHeight)}px</small>
      </figcaption>
      {imageUrl ? (
        <div className="floor-evidence-canvas">
          <svg
            viewBox={`${crop[0]} ${crop[1]} ${cropWidth} ${cropHeight}`}
            role="img"
            aria-label={`检查 ${displayNumber} 的${regionLabel}裁图，共 ${annotations.length} 个标注`}
          >
            <image href={imageUrl} x="0" y="0" width={imageWidth} height={imageHeight} />
            {annotations.map((annotation: any, index: number) => {
              const box = boundingBox(annotation?.bbox_px);
              if (!box) return null;
              const marker = `${displayNumber}-${index + 1}`;
              const labelWidth = marker.length * labelFontSize * 0.62 + labelFontSize;
              const labelX = Math.min(Math.max(box[0], crop[0]), crop[2] - labelWidth);
              const labelY = box[1] - labelHeight >= crop[1] ? box[1] - labelHeight : box[1];
              return (
                <g key={`${marker}-${annotation.label || ''}`}>
                  <rect
                    x={box[0]}
                    y={box[1]}
                    width={box[2] - box[0]}
                    height={box[3] - box[1]}
                    className="floor-evidence-box"
                    vectorEffect="non-scaling-stroke"
                  />
                  <rect
                    x={labelX}
                    y={labelY}
                    width={labelWidth}
                    height={labelHeight}
                    rx={labelHeight * 0.18}
                    className="floor-evidence-marker"
                  />
                  <text
                    x={labelX + labelFontSize * 0.5}
                    y={labelY + labelHeight * 0.7}
                    fontSize={labelFontSize}
                    className="floor-evidence-marker-text"
                  >
                    {marker}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      ) : (
        <div className="empty-state floor-evidence-empty">原始截图尚未关联，无法生成本项裁图</div>
      )}
      <AnnotationLegend item={item} displayNumber={displayNumber} />
    </figure>
  );
}

function CheckDetails({ item }: { item: any }) {
  const details = item.details || {};
  if (item.id === '3.3') {
    return (
      <div className="floor-requirement-grid">
        <Requirement label="上方导航栏" value={details.navigation_bar_above} />
        <Requirement label="下方 Tab 栏" value={details.tab_bar_below} />
        {details.navigation_bar_above === true && <Requirement label="导航栏标注" value={details.navigation_annotation_available} />}
        {details.tab_bar_below === true && <Requirement label="Tab 栏标注" value={details.tab_annotation_available} />}
      </div>
    );
  }
  if (item.id === '3.4') {
    const type = details.floor_type === 'combination'
      ? '组合型楼层'
      : details.floor_type === 'one_row_one_hit'
        ? '一行一爆品楼层'
        : '待确认';
    return <div className="floor-detail-line"><span>识别类型</span><strong>{type}</strong></div>;
  }
  if (item.id === '3.5') {
    const subtitleNote = details.subtitle_rejected_as_badge
      ? '未出现（“新发布+”是角标）'
      : details.subtitle_present === true
        ? '已出现'
        : details.subtitle_present === false
          ? '未出现（可选）'
          : '待确认';
    const benefitNote = details.benefit_present === true
      ? '已出现'
      : details.benefit_present === false
        ? '未出现（可选）'
        : '待确认';
    return (
      <div className="floor-requirement-grid">
        <Requirement label="封面图" value={details.cover_image_present} />
        <Requirement label="渐变蒙层" value={details.gradient_overlay_present} />
        <Requirement label="白字可读性" value={details.overlay_supports_white_text} />
        <Requirement label="蒙层位于封面底部" value={details.overlay_at_cover_bottom} />
        <Requirement label="首焦栏目标题" value={details.primary_focus_title_present} />
        <Requirement label="标题由蒙层承托" value={details.primary_focus_title_supported_by_overlay} />
        <Requirement label="底部信息容器" value={details.bottom_info_container_present} />
        <Requirement label="小标题或利益点至少一项" value={details.bottom_info_has_subtitle_or_benefit} />
        <Fact label="小标题（可选）" value={subtitleNote} />
        {details.subtitle_present === true && <Fact label="小标题 icon（可选）" value={details.subtitle_icon_present} />}
        {details.subtitle_present === true && <Requirement label="小标题位于信息容器内" value={details.subtitle_inside_bottom_info_container} />}
        <Fact label="利益点（可选）" value={benefitNote} />
        {details.benefit_present === true && <Requirement label="利益点位于信息容器内" value={details.benefit_inside_bottom_info_container} />}
        {details.benefit_present === true && <Requirement label="利益点由蒙层承托" value={details.benefit_supported_by_overlay} />}
        {details.benefit_present === true && <div className="floor-requirement"><span>利益点形式</span><strong>{details.benefit_presentation || '待确认'}</strong></div>}
      </div>
    );
  }
  if (item.id === '3.6') {
    if ('condition_1_cover_title_floor' in details) {
      return (
        <div className="floor-requirement-grid">
          <Fact label="条件1：X区域为封面图+首焦标题" value={details.condition_1_cover_title_floor} />
          <Fact label="条件2：下方紧接一行4商品" value={details.condition_2_four_product_floor_immediately_below} />
          {details.condition_1_cover_title_floor === true && <Requirement label="条件1标注完整" value={details.cover_title_floor_annotation_available} />}
          {details.condition_2_four_product_floor_immediately_below === true && <Requirement label="条件2标注完整" value={details.four_product_floor_annotation_available} />}
        </div>
      );
    }
    return (
      <div className="floor-requirement-grid">
        <Fact label="两类楼层共存" value={details.coexistence_present} />
        {details.coexistence_present === true && <Requirement label="首焦楼层标注" value={details.cover_title_floor_annotation_available} />}
        {details.coexistence_present === true && <Requirement label="四商品楼层标注" value={details.four_product_row_annotation_available} />}
      </div>
    );
  }
  if (item.id === '3.7') {
    return (
      <div className="floor-requirement-grid">
        <Fact label="右侧入口数" value={details.entry_count} />
        <Requirement label="上下排列" value={details.entries_vertical} />
      </div>
    );
  }
  if (item.id === '3.8') {
    const entries = Array.isArray(details.entries) ? details.entries : [];
    return entries.length ? (
      <div className="floor-entry-list">
        {entries.map((entry: any) => (
          <div className="floor-entry-row" key={entry.index}>
            <div className="floor-entry-heading">
              <strong>入口 {entry.index}</strong>
              <span>{statusMeta[entry.status]?.label || '待确认'}</span>
            </div>
            <div className="floor-entry-facts">
              <Requirement label="标签栏" value={entry.tag_bar_present} />
              <Requirement label="入口标注" value={entry.annotation_available} />
              <Requirement label="标签 ≤ 6 字" value={entry.tag_text_within_6_chars} />
              <Requirement label="商品缩略图" value={entry.product_thumbnail_present} />
              <Requirement label="商品名" value={entry.product_name_present} />
              <Requirement label="商品名单行" value={entry.product_name_single_line} />
              <Requirement label="价格行" value={entry.price_row_present} />
              <Requirement label="主价格" value={entry.main_price_present} />
              <Requirement label="CTA 按钮" value={entry.cta_present} />
              <Requirement label="CTA ≤ 2 字" value={entry.cta_text_within_2_chars} />
            </div>
          </div>
        ))}
      </div>
    ) : <div className="floor-detail-line"><span>右侧入口数</span><strong>{details.entry_count ?? '待确认'}</strong></div>;
  }
  if (item.id === '3.9') {
    const superstar = details.superstar_benefits || {};
    return (
      <div className="floor-requirement-grid">
        <Requirement label="右侧超级明星福利标题" value={superstar.title_present} />
        <Fact label="明星模块数" value={superstar.star_module_count ?? '不适用'} />
        <Requirement label="明星模块纵向排列" value={superstar.star_modules_vertical} />
        <Requirement label="换一换按钮" value={superstar.refresh_button_present} />
        <Requirement label="未混入其他栏目" value={superstar.other_section_present == null ? null : !superstar.other_section_present} />
      </div>
    );
  }
  return null;
}

function SecondaryEvidenceFigure({ evidence, frames }: { evidence: any; frames: any }) {
  const frame = frames?.[evidence?.frame] || {};
  const crop = boundingBox(evidence?.bbox_px || frame?.bbox_px);
  const imageUrl = frame?.image_id ? imageFileUrl(frame.image_id) : '';
  const imageWidth = Number(frame?.image_width) || 1080;
  const imageHeight = Number(frame?.image_height) || 2400;
  const annotations = Array.isArray(evidence?.annotations) ? evidence.annotations : [];
  if (!crop) return null;
  const cropWidth = crop[2] - crop[0];
  const cropHeight = crop[3] - crop[1];

  return (
    <figure className={`floor-check-evidence secondary-tab-evidence ${evidence?.full_frame ? 'secondary-tab-evidence-full' : ''}`}>
      <figcaption>
        <span>{evidence?.label || frame?.label || evidence?.frame}</span>
        <small>{Math.round(cropWidth)} × {Math.round(cropHeight)}px</small>
      </figcaption>
      {imageUrl ? (
        <div className="floor-evidence-canvas">
          <svg viewBox={`${crop[0]} ${crop[1]} ${cropWidth} ${cropHeight}`} role="img" aria-label={`${evidence?.label || '二级Tab'}证据图`}>
            <image href={imageUrl} x="0" y="0" width={imageWidth} height={imageHeight} />
            <rect
              x={crop[0] + 2}
              y={crop[1] + 2}
              width={Math.max(1, cropWidth - 4)}
              height={Math.max(1, cropHeight - 4)}
              className="secondary-region-box"
              vectorEffect="non-scaling-stroke"
            />
            {annotations.map((annotation: any, index: number) => {
              const box = boundingBox(annotation?.bbox_px);
              if (!box) return null;
              return (
                <rect
                  key={`${evidence?.frame}-${index}`}
                  x={box[0]}
                  y={box[1]}
                  width={box[2] - box[0]}
                  height={box[3] - box[1]}
                  className="secondary-item-box"
                  vectorEffect="non-scaling-stroke"
                />
              );
            })}
          </svg>
        </div>
      ) : (
        <div className="empty-state floor-evidence-empty">截图尚未关联</div>
      )}
      {annotations.length > 0 && (
        <div className="floor-annotation-legend">
          {annotations.map((annotation: any, index: number) => (
            <span key={`${evidence?.frame}-legend-${index}`}><b>{index + 1}</b>{annotation.label || '文本项'}</span>
          ))}
        </div>
      )}
    </figure>
  );
}

function SecondaryCheckDetails({ item }: { item: any }) {
  const details = item?.details || {};
  if (item?.id === '1') {
    return (
      <div className="floor-requirement-grid">
        <Fact label="选中态组数" value={details.selected_count} />
        <Fact label="非选中态组数" value={details.unselected_count} />
        <Fact label="选中态色值" value={details.selected_color_hex} />
        <Fact label="选中目标色" value={details.selected_target_hex} />
        <Requirement label="选中色视觉一致" value={details.selected_color_matches_target} />
        <Fact label="非选中态色值" value={details.unselected_color_hex} />
        <Fact label="非选中目标色" value={details.unselected_target_hex} />
        <Requirement label="非选中色视觉一致" value={details.unselected_color_matches_target} />
        <Fact label="背景色值" value={details.background_color_hex} />
        <Fact label="背景目标色" value={details.background_target_hex} />
        <Requirement label="背景色视觉一致" value={details.background_color_matches_target} />
        {details.second_button_target_hex && (
          <>
            <Fact label="第二个按钮" value={details.second_button_text} />
            <Fact label="第二按钮文字色" value={details.second_button_color_hex} />
            <Fact label="第二按钮目标色" value={details.second_button_target_hex} />
            <Requirement label="第二按钮色视觉一致" value={details.second_button_color_matches_target} />
          </>
        )}
        <Fact label="颜色来源" value={details.color_source} />
      </div>
    );
  }
  if (item?.id === '2' || item?.id === '3') {
    const region = item.id === '2' ? 'z2' : 'z3';
    return (
      <div className="floor-requirement-grid">
        <Fact label={`${region} 是否与 z1 一致`} value={yesNo(details.matches_z1)} />
        {item.id === '3' && <Fact label="审核期望" value="z3 与 z1 不一致" />}
        <Fact label="z1 文本" value={(details.z1_texts || []).join('、') || '未识别'} />
        <Fact label={`${region} 文本`} value={(details[`${region}_texts`] || []).join('、') || '未识别'} />
      </div>
    );
  }
  if (item?.id === '4') {
    const regions = details.regions || {};
    return (
      <div className="floor-requirement-grid">
        {['z1', 'z2'].map(region => (
          <Requirement key={region} label={`${region} 文本保持单行`} value={regions[region]?.all_single_line} />
        ))}
      </div>
    );
  }
  if (item?.id === '5') {
    const regions = details.regions || {};
    return (
      <div className="secondary-region-results">
        {['z1', 'z2'].map(region => (
          <div className="floor-entry-row" key={region}>
            <div className="floor-entry-heading"><strong>{region}</strong></div>
            <div className="floor-requirement-grid">
              <Requirement label="只有一个选中态" value={regions[region]?.exactly_one_selected} />
              <Fact label="选中态数量" value={regions[region]?.selected_count} />
              <Fact label="选中内容" value={(regions[region]?.selected_texts || []).join('、') || '未识别'} />
            </div>
          </div>
        ))}
        <div className="floor-detail-line"><span>两处选中内容一致</span><strong>{yesNo(details.selected_content_consistent)}</strong></div>
      </div>
    );
  }
  if (item?.id === '6') {
    const regions = details.regions || {};
    return (
      <div className="secondary-region-results">
        {['z1', 'z2'].map(region => (
          <div className="floor-entry-row" key={region}>
            <div className="floor-entry-heading"><strong>{region}</strong></div>
            <div className="floor-requirement-grid">
              <Requirement label="区域内可左滑 400px" value={regions[region]?.content_moved_horizontally} />
              <Requirement label="区域外内容不变" value={regions[region]?.outside_region_unchanged} />
            </div>
          </div>
        ))}
      </div>
    );
  }
  return null;
}

function SecondaryTabSection({ report }: { report: any }) {
  if (!report) return null;
  const checks = report.checks ? Object.values(report.checks) as any[] : [];
  const counts = report.summary?.counts || {};
  const frames = report.frames || {};

  return (
    <section className="floor-report-part secondary-tab-part" aria-labelledby="secondary-tab-title">
      <div className="floor-section-heading floor-part-heading">
        <div>
          <span className="floor-part-kicker">第二部分</span>
          <h2 id="secondary-tab-title">二级tab组件巡查</h2>
          <p>动态定位红色“推荐”所在 z1，结合固定 z2/z3 完成颜色、一致性、单行、唯一选中态及横滑验证。</p>
        </div>
      </div>

      <section className="floor-summary-strip secondary-summary" aria-label="二级tab组件巡查汇总">
        <div className="floor-summary-primary">
          <span>二级tab总评</span>
          <strong className={`floor-summary-${report.summary?.status || 'uncertain'}`}>{report.summary?.conclusion || '待确认'}</strong>
        </div>
        <dl>
          <div><dt>通过</dt><dd>{counts.pass || 0}</dd></div>
          <div><dt>不通过</dt><dd>{counts.fail || 0}</dd></div>
          <div><dt>待确认</dt><dd>{counts.uncertain || 0}</dd></div>
        </dl>
      </section>

      <section className="floor-report-section">
        <div className="floor-section-heading">
          <div>
            <h2>逐项检查</h2>
            <p>每项均显示带区域框的证据裁图；横滑检查显示动作前后对照。</p>
          </div>
        </div>
        <div className="floor-check-list">
          {checks.map((item: any, index: number) => {
            const meta = statusMeta[item.status] || statusMeta.uncertain;
            return (
              <article className="floor-check" key={item.id || index}>
                <div className="floor-check-index">{item.id || index + 1}</div>
                <div className="floor-check-content">
                  <div className="secondary-evidence-grid">
                    {(item.evidence || []).map((evidence: any, evidenceIndex: number) => (
                      <SecondaryEvidenceFigure
                        key={`${item.id}-${evidence.frame}-${evidenceIndex}`}
                        evidence={evidence}
                        frames={frames}
                      />
                    ))}
                  </div>
                  <div className="floor-check-heading">
                    <h3>{item.title}</h3>
                    <span className={`floor-status ${meta.className}`}>{meta.label}</span>
                  </div>
                  <p className="floor-check-conclusion">{item.conclusion}</p>
                  <SecondaryCheckDetails item={item} />
                </div>
              </article>
            );
          })}
        </div>
      </section>
    </section>
  );
}

export default function JdNewFloorReport() {
  const { taskId } = useParams();
  const [params, setParams] = useSearchParams();
  const [runs, setRuns] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!taskId) return;
    setLoading(true);
    listTaskRuns(taskId)
      .then(({ data }) => setRuns(data.filter((run: any) => run.result_json?.report_type === 'jd_new_floor_audit')))
      .finally(() => setLoading(false));
  }, [taskId]);

  const selectedRun = useMemo(() => {
    const runId = params.get('runId');
    return runs.find(run => run.id === runId) || runs[0];
  }, [runs, params]);
  const report = selectedRun?.result_json;
  const checks = report?.checks ? Object.values(report.checks) as any[] : [];
  const counts = report?.summary?.counts || {};
  const capture = report?.capture || {};
  const regions = report?.regions || {};
  const artifacts = report?.artifacts || {};
  const imageWidth = Number(capture.image_width || capture.width) || 1080;
  const imageHeight = Number(capture.image_height || capture.height) || 2400;
  const rawImageUrl = artifacts.raw?.image_id ? imageFileUrl(artifacts.raw.image_id) : '';
  const secondaryReport = report?.secondary_tab_audit;

  return (
    <div className="animate-fade-in floor-report-page" lang="zh-CN">
      <div className="page-header floor-report-header">
        <div>
          <h1>京东新品楼层检查</h1>
          <p>腰部楼层巡查与二级tab组件巡查</p>
        </div>
        <Link className="btn-secondary btn-sm link-button" to={`/admin/tasks/${taskId}/results`}>返回任务结果</Link>
      </div>

      {runs.length > 0 && (
        <label className="floor-report-run-select">
          <span>运行记录</span>
          <select value={selectedRun?.id || ''} onChange={event => setParams({ runId: event.target.value })}>
            {runs.map(run => <option key={run.id} value={run.id}>第 {run.attempt_no} 次 · {run.status}</option>)}
          </select>
        </label>
      )}

      {loading ? <div className="skeleton" style={{ height: 260 }} /> : !report ? (
        <div className="empty-state">该运行暂无新品楼层检查报告</div>
      ) : (
        <>
          <section className="floor-section-heading floor-part-heading" aria-labelledby="waist-floor-title">
            <div>
              <span className="floor-part-kicker">第一部分</span>
              <h2 id="waist-floor-title">腰部楼层巡查</h2>
              <p>保留原有固定 X/Y 区域与 1 至 7 逐项核验。</p>
            </div>
          </section>

          <section className="floor-summary-strip" aria-label="腰部楼层巡查汇总">
            <div className="floor-summary-primary">
              <span>腰部楼层总评</span>
              <strong className={`floor-summary-${report.summary?.status || 'uncertain'}`}>{report.summary?.conclusion || '待确认'}</strong>
            </div>
            <dl>
              <div><dt>通过</dt><dd>{counts.pass || 0}</dd></div>
              <div><dt>不通过</dt><dd>{counts.fail || 0}</dd></div>
              <div><dt>待确认</dt><dd>{counts.uncertain || 0}</dd></div>
              <div><dt>不适用</dt><dd>{counts.not_applicable || 0}</dd></div>
            </dl>
          </section>

          <section className="floor-report-section">
            <div className="floor-section-heading">
              <div>
                <h2>腰部楼层逐项检查</h2>
                <p>结论由模型识别原子事实后按固定规则计算，条件项未触发时显示“不适用”。</p>
              </div>
            </div>
            <div className="floor-check-list">
              {checks.map((item, index) => {
                const meta = statusMeta[item.status] || statusMeta.uncertain;
                const displayNumber = checkDisplayNumbers[item.id] || String(index + 1);
                return (
                  <article className="floor-check" key={item.id}>
                    <div className="floor-check-index">{displayNumber}</div>
                    <div className="floor-check-content">
                      <CheckEvidenceFigure
                        item={item}
                        displayNumber={displayNumber}
                        imageUrl={rawImageUrl}
                        imageWidth={imageWidth}
                        imageHeight={imageHeight}
                        regions={regions}
                      />
                      <div className="floor-check-heading">
                        <h3>{item.title}</h3>
                        <span className={`floor-status ${meta.className}`}>{meta.label}</span>
                      </div>
                      <p className="floor-check-conclusion">{item.conclusion}</p>
                      <CheckDetails item={item} />
                    </div>
                  </article>
                );
              })}
            </div>
          </section>

          <SecondaryTabSection report={secondaryReport} />
        </>
      )}
    </div>
  );
}
