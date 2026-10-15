import { useRef, useState } from 'react';
import { AuditFinding, AuditReviewInput, AuditReviewVerdict, createAuditReview } from '../api';
import { useAuth } from '../auth';
import { statusLabels } from './AuditWorkspaceUI';

export const reviewVerdicts: { value: AuditReviewVerdict; label: string }[] = [
  { value: 'confirmed', label: '确认问题' }, { value: 'false_positive', label: '误报' },
  { value: 'false_negative', label: '漏报' }, { value: 'exception', label: '接受例外' },
  { value: 'recapture', label: '需重采' },
];

export default function AuditFindingReview({ finding, targetId, uncovered = false, onReviewed }: {
  finding: AuditFinding; targetId: string; uncovered?: boolean; onReviewed: () => Promise<void>;
}) {
  const { hasRole } = useAuth();
  const [note, setNote] = useState('');
  const [corrected, setCorrected] = useState('');
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const [error, setError] = useState('');
  async function review(verdict: AuditReviewVerdict) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError('');
    try {
      await createAuditReview(targetId, { rule_id: finding.rule_id, verdict, note: note.trim() || null,
        corrected_status: (corrected || null) as AuditReviewInput['corrected_status'] });
      await onReviewed(); setNote(''); setCorrected('');
    } catch { setError('复核保存或刷新失败，请重试。'); }
    finally { pending.current = false; setBusy(false); }
  }
  const current = finding.review;
  return <section className="aw-review" aria-label={`${finding.rule_id} 人工复核`}>
    {current ? <><p className="aw-chips"><span className="aw-chip">已复核</span><strong>人工：{reviewVerdicts.find(v => v.value === current.verdict)?.label}（原：{statusLabels[finding.status]}）</strong>{finding.excepted ? <span className="aw-chip">例外 · 闭环按符合计</span> : null}{finding.needs_recapture ? <span className="aw-chip">等待重采</span> : null}</p>{current.note ? <p>备注：{current.note}</p> : null}</> : null}
    {hasRole('operator') ? <>
      <div className="aw-actions aw-review-actions">{reviewVerdicts.map((verdict, index) => <button type="button" className="aw-secondary" data-verdict={index + 1} key={verdict.value} disabled={busy || (uncovered && verdict.value !== 'false_negative')} aria-pressed={current?.verdict === verdict.value} onClick={() => void review(verdict.value)}><kbd>{index + 1}</kbd> {verdict.label}</button>)}</div>
      <div className="aw-review-fields"><label>备注（可选）<textarea aria-label={`${finding.rule_id} 复核备注`} value={note} onChange={event => setNote(event.target.value)} rows={1} /></label><label>修正状态（可选）<select value={corrected} onChange={event => setCorrected(event.target.value)}><option value="">使用判定默认值</option><option value="pass">符合</option><option value="fail">不符合</option><option value="not_applicable">不适用</option></select></label></div>
      {error ? <p role="alert">{error}</p> : null}
    </> : null}
  </section>;
}
