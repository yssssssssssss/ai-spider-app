import { ReactNode, useEffect, useId, useRef } from 'react';
import { AuditCaptureReason, AuditComposition, AuditOutcome, AuditStatus } from '../api';

export const outcomeOrder: AuditOutcome[] = ['issues', 'needs_confirmation', 'partial', 'clean', 'capture_failed'];
export const outcomeLabels: Record<AuditOutcome, string> = {
  issues: '有不符合', needs_confirmation: '待确认', partial: '部分审核', clean: '全部符合', capture_failed: '采集失败',
};
export const statusLabels: Record<AuditStatus, string> = {
  fail: '不符合', uncertain: '待确认', pass: '符合', not_applicable: '不适用', disabled: '未启用',
};
export const captureLabels: Record<AuditCaptureReason, string> = {
  offline: '活动已下线', expired: '已过期或已结束', login_required: '需要登录', other: '其他采集异常',
  venue_lost: '活动迷路', not_ready: '加载未就绪', floor_error: '楼层异常', capture_failed: '采集失败',
};
export function auditTime(value?: string | null) {
  if (!value) return '暂无时间';
  const date = new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? '暂无时间' : date.toLocaleString('zh-CN', { hour12: false });
}
export function versionChipLabel(label: string) {
  const match = /^v?(\d+)(?:$|[-._\s])/i.exec(label);
  return match ? `v${match[1]}` : label;
}
export function OutcomeBadge({ outcome }: { outcome: AuditOutcome }) {
  return <span className={`aw-chip aw-outcome-${outcome}`}>{outcomeLabels[outcome]}</span>;
}
export function DemoBadge({ source }: { source: Record<string, unknown> }) {
  return source.demo === true ? <span className="aw-chip aw-demo">演示数据</span> : null;
}
export function AuditDialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current!;
    const previous = document.activeElement;
    dialog.showModal();
    (dialog.querySelector<HTMLElement>('input, select, textarea') || dialog.querySelector<HTMLElement>('button'))?.focus();
    return () => {
      dialog.close();
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);
  return <dialog ref={ref} className="aw aw-dialog" aria-labelledby={titleId} onCancel={event => { event.preventDefault(); onClose(); }}>
    <div className="aw-heading"><h2 id={titleId}>{title}</h2><button type="button" className="aw-quiet" onClick={onClose}>关闭</button></div>
    {children}
  </dialog>;
}
export function LoadState({ loading, error, retry }: { loading?: boolean; error?: boolean; retry?: () => void }) {
  return <div className="aw-empty" role={error ? 'alert' : 'status'}>{loading ? '正在加载…' : error ? <>加载失败。{retry && <button type="button" className="aw-quiet" onClick={retry}>重试</button>}</> : '暂无数据'}</div>;
}
export function CompositionBar({ composition, selected, onSelect, compact = false }: {
  composition: Pick<AuditComposition, 'total' | 'outcomes'>; selected?: AuditOutcome;
  onSelect?: (outcome: AuditOutcome) => void; compact?: boolean;
}) {
  const label = outcomeOrder.map(key => `${outcomeLabels[key]} ${composition.outcomes[key]}`).join('，');
  if (!composition.total) return <span className="aw-muted">暂无对象</span>;
  return <div className={`aw-composition ${compact ? 'is-compact' : ''}`} role={onSelect ? 'group' : 'img'} aria-label={label} title={compact ? label : undefined}>
    {outcomeOrder.filter(key => composition.outcomes[key] > 0).map(key => {
      const count = composition.outcomes[key];
      const style = { flex: `${count} 1 0` };
      return onSelect ? <button key={key} type="button" className={`aw-segment aw-outcome-${key} ${selected && selected !== key ? 'is-dim' : ''}`} style={style} aria-pressed={selected === key} onClick={() => onSelect(key)} title={`${outcomeLabels[key]} ${count}`}>
        <strong>{count}</strong><span>{outcomeLabels[key]}</span>
      </button> : <span key={key} className={`aw-segment aw-outcome-${key}`} style={style} />;
    })}
  </div>;
}
export const stripColors: Record<string, string> = { F: '#FF6A3D', U: '#8C7A3A', P: '#1F5C46', '-': '#2A303C', x: '#161A22' };
// One gradient element per strip; never one element per rule/target intersection.
export function stripGradient(codes: string) {
  if (!codes.length) return undefined;
  return `linear-gradient(90deg,${Array.from(codes, (code, i) => `${stripColors[code] || stripColors['-']} ${i / codes.length * 100}% ${(i + 1) / codes.length * 100}%`).join(',')})`;
}
export function StatusLegend() {
  return <div className="aw-legend"><span><i className="aw-key aw-fail" />不符合</span><span><i className="aw-key aw-uncertain" />待确认</span><span><i className="aw-key aw-pass" />符合</span><span><i className="aw-key aw-na" />不适用 / 无覆盖</span><span><i className="aw-key aw-disabled" />未启用 / 不适用载体 / 共享证据</span></div>;
}
