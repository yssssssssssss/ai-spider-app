import { CSSProperties, useRef, useState } from 'react';
import { isAxiosError } from 'axios';
import { AuditEvidenceBox, AuditEvidenceItem, AuditEvidenceMark, AuditEvidenceUploadResult, AuditFinding, auditEvidenceUrl, imageFileUrl, uploadAuditEvidence } from '../api';
import { useAuth } from '../auth';
import { AuditDialog, statusLabels } from './AuditWorkspaceUI';

const sourceLabels = { dom: 'DOM 测量', pixel: '像素测量', model: '模型判断', hybrid: '混合' };
const verdictLabels: Record<string, string> = { ...statusLabels, unknown: '待确认' };
const measurementUnits: Record<string, string> = { hex: '', css_px: ' CSS px' };
const imageUrl = (item: AuditEvidenceItem) => item.asset ? auditEvidenceUrl(item.asset) : item.image_id ? imageFileUrl(item.image_id) : '';
const imageKey = (item: AuditEvidenceItem) => item.asset || item.image_id || item.file;
const validSize = (size?: [number, number] | null): size is [number, number] => !!size && size.length === 2 && size.every(value => Number.isFinite(value) && value > 0);
const validBox = (box?: AuditEvidenceBox | null): box is AuditEvidenceBox => !!box && box.length === 4 && box.every(Number.isFinite) && box[2] > box[0] && box[3] > box[1];
const validMark = (mark: AuditEvidenceMark) => mark.kind === 'rect' ? validBox(mark.bbox_px)
  : mark.kind === 'line' && !!mark.start_px && !!mark.end_px && [...mark.start_px, ...mark.end_px].every(Number.isFinite);

function MarkLabels({ marks }: { marks: AuditEvidenceMark[] }) {
  return marks.length ? <ul className="aw-evidence-labels">{marks.map((mark, index) => <li key={index} className={`aw-evidence-source-${mark.source}`}><i aria-hidden="true" /><span>{index + 1}. {mark.label || sourceLabels[mark.source]}{mark.source === 'model' ? <small>模型定位，未核对</small> : <small>{sourceLabels[mark.source]}</small>}</span></li>)}</ul> : null;
}

function EvidenceImage({ item, label, full = false }: { item: AuditEvidenceItem; label: string; full?: boolean }) {
  const [naturalSize, setNaturalSize] = useState<[number, number] | null>(null);
  const [failed, setFailed] = useState(false);
  const size = validSize(item.image_size) ? item.image_size : naturalSize;
  const marks = (item.marks || []).filter(validMark);
  const appBoxes = item.image_id ? marks.map(mark => mark.bbox_px).filter(validBox) : [];
  const cropBox = item.crop_px || (appBoxes.length ? [Math.min(...appBoxes.map(box => box[0])), Math.min(...appBoxes.map(box => box[1])), Math.max(...appBoxes.map(box => box[2])), Math.max(...appBoxes.map(box => box[3]))] as AuditEvidenceBox : null);
  let crop: AuditEvidenceBox | null = null;
  if (!full && item.role !== 'context' && item.state !== 'context' && size && validBox(cropBox)) {
    const box: AuditEvidenceBox = [Math.max(0, cropBox[0]), Math.max(0, cropBox[1]), Math.min(size[0], cropBox[2]), Math.min(size[1], cropBox[3])];
    if (validBox(box)) crop = box;
  }
  const view: AuditEvidenceBox = crop || [0, 0, size?.[0] || 1, size?.[1] || 1];
  const width = view[2] - view[0], height = view[3] - view[1];
  // Image and SVG share the same full-image box; only this outer viewport clips the crop.
  const imageStyle: CSSProperties = size ? { width: `${size[0] / width * 100}%`, height: `${size[1] / height * 100}%`, left: `${-view[0] / width * 100}%`, top: `${-view[1] / height * 100}%` } : {};
  const frameStyle = size ? {
    aspectRatio: `${width} / ${height}`,
    width: full ? `min(100%, ${width}px, calc(min(80dvh, 100dvh - 260px) * ${width / height}))` : Math.min(300, 220 * width / height),
  } : undefined;
  const fontSize = width / 22;
  return <>
    <div className={`aw-evidence-image${full ? ' is-full' : ''}${!size || failed ? ' is-placeholder' : ''}`} style={frameStyle}>
      {failed ? <span role="status">截图加载失败</span> : <>
        {!size ? <span className="aw-muted">正在加载截图…</span> : null}
        <img src={imageUrl(item)} alt={label} loading="lazy" decoding="async" style={imageStyle} onLoad={event => {
          const { naturalWidth, naturalHeight } = event.currentTarget;
          if (naturalWidth && naturalHeight) setNaturalSize([naturalWidth, naturalHeight]); else setFailed(true);
        }} onError={() => setFailed(true)} />
        {size ? <svg className="aw-evidence-marks" style={imageStyle} viewBox={`0 0 ${size[0]} ${size[1]}`} aria-hidden="true">{marks.map((mark, index) => {
          const [x, y] = mark.kind === 'rect' ? mark.bbox_px! : mark.start_px!;
          return <g key={index} className={`aw-evidence-source-${mark.source}`}>
            {mark.kind === 'rect' && mark.bbox_px ? <rect x={x} y={y} width={mark.bbox_px[2] - x} height={mark.bbox_px[3] - y} vectorEffect="non-scaling-stroke" /> : <line x1={x} y1={y} x2={mark.end_px![0]} y2={mark.end_px![1]} vectorEffect="non-scaling-stroke" />}
            <text x={Math.max(view[0] + fontSize / 3, Math.min(x + fontSize / 3, view[2] - fontSize))} y={Math.max(view[1] + fontSize, Math.min(y + fontSize, view[3] - fontSize / 3))} fontSize={fontSize}>{index + 1}</text>
          </g>;
        })}</svg> : null}
      </>}
    </div>
    {!full && (!crop || item.role === 'context') ? <span className="aw-evidence-context">整屏参考 · 暂无局部定位</span> : null}
    <MarkLabels marks={marks} />
  </>;
}

function EvidenceViewer({ items, initial, title, onClose }: { items: AuditEvidenceItem[]; initial: AuditEvidenceItem; title: string; onClose: () => void }) {
  const screens: AuditEvidenceItem[] = [];
  for (const item of items) {
    const screen = screens.find(candidate => imageKey(candidate) === imageKey(item));
    if (screen) screen.marks.push(...(item.marks || []));
    else screens.push({ ...item, marks: [...(item.marks || [])] });
  }
  const [active, setActive] = useState(() => Math.max(0, screens.findIndex(item => imageKey(item) === imageKey(initial))));
  const item = screens[active];
  function move(delta: number) { setActive(value => (value + delta + screens.length) % screens.length); }
  return <AuditDialog title={title} onClose={onClose} className="aw-evidence-dialog" onKeyDown={event => {
      if (screens.length > 1 && (event.key === 'ArrowLeft' || event.key === 'ArrowRight')) { event.preventDefault(); move(event.key === 'ArrowLeft' ? -1 : 1); }
    }}>
    <div className="aw-evidence-viewer">
      {screens.length > 1 ? <div className="aw-evidence-tabs" role="group" aria-label="截图屏幕切换">{screens.map((screen, index) => <button type="button" className="aw-secondary" aria-pressed={active === index} key={imageKey(screen)} onClick={() => setActive(index)}>屏 {screen.screen ?? index + 1}</button>)}<span className="aw-muted">← / → 切屏</span></div> : null}
      <p className="aw-muted">{item.label || `屏 ${item.screen ?? active + 1}`}</p>
      <EvidenceImage key={imageKey(item)} item={item} label={item.label || title} full />
    </div>
  </AuditDialog>;
}

function EvidenceUpload({ runId, onReload }: { runId: string; onReload: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AuditEvidenceUploadResult | null>(null);
  const [error, setError] = useState('');
  function close() { if (busy) return; setOpen(false); if (result) onReload(); }
  async function upload(file: File) {
    if (busy) return;
    setOpen(true); setResult(null); setError('');
    if (!/\.zip$/i.test(file.name) || !file.size) { setError('请选择非空的 .zip 证据包。'); return; }
    setBusy(true);
    try { const { data } = await uploadAuditEvidence(runId, file); setResult(data); }
    catch (err) { setError(isAxiosError(err) && typeof err.response?.data?.detail === 'string' ? err.response.data.detail : '补传失败，请重试。'); }
    finally { setBusy(false); }
  }
  return <div>
    <input ref={input} type="file" accept=".zip,application/zip" aria-label="证据包（zip）" style={{ display: 'none' }} onChange={event => {
      const file = event.currentTarget.files?.[0]; event.currentTarget.value = '';
      if (file) void upload(file);
    }} />
    <button type="button" className="aw-secondary" onClick={() => input.current?.click()} disabled={busy}>补传证据包</button>
    {open ? <AuditDialog title="补传证据包" onClose={close}>
      {busy ? <p role="status">正在补传证据包…</p> : result ? <><p role="status">证据包处理完成</p><dl className="aw-evidence-stats"><div><dt>匹配对象</dt><dd>{result.matched_targets}</dd></div><div><dt>新增截图</dt><dd>{result.stored_assets}</dd></div><div><dt>证据缺失</dt><dd>{result.missing}</dd></div><div><dt>校验失败</dt><dd>{result.integrity_errors}</dd></div><div><dt>未匹配</dt><dd>{result.unmatched}</dd></div></dl><div className="aw-actions"><button type="button" onClick={close}>完成并刷新</button></div></> : <p role="alert">{error}</p>}
    </AuditDialog> : null}
  </div>;
}

export default function AuditEvidence({ finding, runId, onReload }: { finding: AuditFinding; runId: string; onReload: () => void }) {
  const { hasRole } = useAuth();
  const [viewing, setViewing] = useState<AuditEvidenceItem | null>(null);
  const items = finding.evidence?.items || [];
  const state = finding.evidence?.items ? finding.evidence.state || (items.length ? 'context' : 'missing') : 'not_attached';
  const itemState = (item: AuditEvidenceItem) => item.state || (state === 'missing' || state === 'not_attached' ? state : undefined);
  const notAttached = state === 'not_attached' || items.some(item => itemState(item) === 'not_attached');
  const integrityError = !!finding.evidence_integrity_error && !items.some(item => item.integrity_error);
  const available = items.filter(item => !integrityError && !item.integrity_error && itemState(item) !== 'missing' && itemState(item) !== 'not_attached' && imageUrl(item));
  return <section className="aw-evidence" aria-label={`${finding.rule_id} 审核证据`}>
    <div className="aw-chips"><span className={`aw-chip aw-evidence-method-${finding.method || 'model'}`}>{sourceLabels[finding.method || 'model']}</span>{finding.model_status && finding.model_status !== finding.status ? <span className="aw-evidence-decision">模型：{statusLabels[finding.model_status]} → 测量：{statusLabels[finding.status]}</span> : null}</div>
    {integrityError && !items.length ? <p className="aw-warning" role="status">截图校验失败，未展示</p> : null}
    {items.length ? <div className="aw-evidence-strip" tabIndex={0} role="region" aria-label="截图证据，可横向滚动">{items.map((item, index) => <div className="aw-evidence-card" key={`${imageKey(item) || 'missing'}-${index}`}>
      {integrityError || item.integrity_error ? <div className="aw-evidence-placeholder aw-warning">截图校验失败，未展示</div> : itemState(item) === 'not_attached' ? <div className="aw-evidence-placeholder">证据未随附</div> : itemState(item) === 'missing' || !imageUrl(item) ? <div className="aw-evidence-placeholder">证据缺失</div> : <button type="button" className="aw-evidence-thumbnail" onClick={() => setViewing(item)} aria-label={`查看整屏：${item.label || finding.title}`}><EvidenceImage item={item} label={item.label || finding.title || finding.rule_id} /></button>}
      <p className="aw-evidence-caption">{item.label || `屏 ${item.screen ?? index + 1}`}</p>
    </div>)}</div> : <p className="aw-muted">{state === 'not_attached' ? '证据未随附' : '证据缺失'}</p>}
    {notAttached && finding.evidence?.kind !== 'app_images' && hasRole('operator') ? <EvidenceUpload runId={runId} onReload={onReload} /> : null}
    {finding.evidence?.measurements?.length ? <ul className="aw-evidence-measurements">{finding.evidence.measurements.map(measurement => <li key={measurement.id}>
      <span>{measurement.label ? `${measurement.label} · ` : ''}实测 {measurement.value ?? '—'}{measurement.value !== null ? measurementUnits[measurement.unit] ?? measurement.unit : ''} · 规范 {measurement.expected ?? '—'}</span><span className="aw-chip">{verdictLabels[measurement.verdict] || measurement.verdict}</span><span className="aw-muted">{sourceLabels[measurement.source]}</span>{!measurement.verified ? <span className="aw-chip">未核对</span> : null}
    </li>)}</ul> : null}
    {viewing ? <EvidenceViewer items={available} initial={viewing} title={`${finding.rule_id} · ${finding.title}`} onClose={() => setViewing(null)} /> : null}
  </section>;
}
