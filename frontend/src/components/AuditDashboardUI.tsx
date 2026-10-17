import { useId } from 'react';
import { AuditOutcome } from '../api';

export function outcomeSegments(outcomes: Record<AuditOutcome, number>) {
  return [
    { label: '不符合', count: outcomes.issues, tone: 'fail' },
    { label: '待确认', count: outcomes.needs_confirmation, tone: 'uncertain' },
    { label: `部分审核 ${outcomes.partial} / 全部符合 ${outcomes.clean}，合计`, count: outcomes.partial + outcomes.clean, tone: 'pass' },
    { label: '采集失败', count: outcomes.capture_failed, tone: 'capture' },
  ];
}

export function OutcomeBar({ outcomes, label }: { outcomes: Record<AuditOutcome, number>; label: string }) {
  const segments = outcomeSegments(outcomes);
  const description = `${label}：${segments.map(item => `${item.label} ${item.count}`).join('，')}`;
  return <span className="aw-outcome-bar" role="img" aria-label={description} title={description}>
    {segments.filter(item => item.count > 0).map(item => <span key={item.tone} className={`aw-fill-${item.tone}`} style={{ flex: item.count }} />)}
  </span>;
}

export function DashboardRing({ label, value, caption, segments }: {
  label: string; value: string | number; caption: string;
  segments: { count: number; tone: string }[];
}) {
  const hatchId = useId();
  const total = segments.reduce((sum, item) => sum + item.count, 0);
  let offset = 0;
  return <div className="aw-ring" role="img" aria-label={label}>
    <svg viewBox="0 0 100 100" aria-hidden="true">
      <defs><pattern id={hatchId} width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="var(--aw-na)" /><path d="M0 0V6" stroke="var(--aw-muted)" strokeWidth="2" /></pattern></defs>
      <circle className="aw-ring-track" cx="50" cy="50" r="42" />
      {segments.filter(item => item.count > 0).map((item, index) => {
        const portion = item.count / total * 100;
        const start = offset;
        offset += portion;
        return <circle className={`aw-ring-${item.tone}`} key={index} cx="50" cy="50" r="42" pathLength="100" stroke={item.tone === 'capture' || item.tone === 'remaining' ? `url(#${hatchId})` : undefined} strokeDasharray={`${portion} ${100 - portion}`} strokeDashoffset={-start} transform="rotate(-90 50 50)" />;
      })}
    </svg>
    <span className="aw-ring-value" aria-hidden="true"><strong>{value}</strong><small>{caption}</small></span>
  </div>;
}
