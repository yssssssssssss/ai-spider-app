import { ReactNode, useEffect, useId, useRef } from 'react';
import { AuditCategory, AuditCounts, AuditStatus } from '../api';

export const auditCategories: { key: AuditCategory; label: string }[] = [
  { key: 'regressed', label: '发布回归' },
  { key: 'still_open', label: '未修' },
  { key: 'new_issue', label: '上线后新增' },
  { key: 'needs_confirmation', label: '待确认' },
  { key: 'fixed', label: '已修' },
  { key: 'kept', label: '保持合规' },
  { key: 'not_comparable', label: '无法比对' },
];

const statusLabels: Record<AuditStatus, string> = {
  pass: '符合', fail: '不符合', uncertain: '待确认', not_applicable: '不适用', disabled: '未启用',
};

export function auditTime(value?: string | null) {
  if (!value) return '暂无时间';
  // The backend stores UTC in naive datetime columns.
  const date = new Date(/(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? '暂无时间' : date.toLocaleString('zh-CN', { hour12: false });
}

export function AuditStatusBadge({ status }: { status: string | null }) {
  const style = status === 'fail' ? 'badge-rejected' : status === 'uncertain' ? 'badge-pending' : '';
  return <span className={`badge ${style}`}>{status ? statusLabels[status as AuditStatus] || status : '无记录'}</span>;
}

export function AuditSummary({ counts, compact = false }: { counts: AuditCounts; compact?: boolean }) {
  const statuses: AuditStatus[] = compact ? ['fail', 'uncertain'] : ['fail', 'uncertain', 'pass', 'not_applicable', 'disabled'];
  const visibleStatuses = statuses.filter(status => counts[status] > 0);
  if (visibleStatuses.length === 0) return <span className="audit-muted">{compact ? '无问题' : '暂无检查项'}</span>;
  return <div className="audit-actions">{visibleStatuses.map(status => (
    <span key={status}><AuditStatusBadge status={status} /> {counts[status]}</span>
  ))}</div>;
}

export function AuditDialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current!;
    const previous = document.activeElement;
    dialog.showModal();
    dialog.querySelector<HTMLElement>('input, select, textarea')?.focus();
    return () => {
      dialog.close();
      if (previous instanceof HTMLElement && previous.isConnected) previous.focus();
    };
  }, []);
  return (
    <dialog ref={ref} className="audit-dialog" aria-labelledby={titleId} onCancel={event => { event.preventDefault(); onClose(); }}>
      <div className="section-title-row">
        <h2 id={titleId}>{title}</h2>
        <button type="button" className="btn-secondary btn-sm" onClick={onClose}>关闭</button>
      </div>
      {children}
    </dialog>
  );
}
