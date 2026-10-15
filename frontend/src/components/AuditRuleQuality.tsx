import { useEffect, useState } from 'react';
import { type AuditRuleQuality, getAuditRuleQuality } from '../api';
import { LoadState } from './AuditWorkspaceUI';

const rate = (value: number | null) => value === null ? '—' : `${(value * 100).toFixed(1)}%`;
export default function AuditRuleQuality({ versionId }: { versionId: string }) {
  const [rows, setRows] = useState<AuditRuleQuality[] | null>(null);
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    setRows(null); setError(false);
    getAuditRuleQuality(versionId).then(({ data }) => {
      if (active) setRows([...data.rules].sort((a, b) => (b.fp_rate ?? -1) - (a.fp_rate ?? -1)));
    }).catch(() => { if (active) setError(true); });
    return () => { active = false; };
  }, [versionId, reload]);
  if (!rows) return <LoadState loading={!error} error={error} retry={() => setReload(value => value + 1)} />;
  return <>
    <p className="aw-muted">按误报率降序 · 误报率基于原判不符合且已确认/误报的条目；漏报率基于已复核且无需重采的条目；待确认率基于全部原始判定。</p>
    <div className="aw-scroll" tabIndex={0} role="region" aria-label="规则质量表"><table className="aw-rule-table"><thead><tr>{['规则 / 方法', '已复核', '确认', '误报', '漏报', '例外', '重采', '误报率', '漏报率', '待确认率', '样本'].map(label => <th key={label} scope="col">{label}</th>)}</tr></thead><tbody>{rows.map(row => <tr key={row.rule_id}>
      <th scope="row"><span className="aw-mono">{row.rule_id}</span><p>{row.title}</p><details><summary>按方法拆分</summary>{(['model', 'dom', 'pixel'] as const).map(method => <p key={method}>{({ model: '模型', dom: 'DOM', pixel: '像素' })[method]}：复核 {row.by_method[method].reviewed} · 误报 {rate(row.by_method[method].fp_rate)} · 漏报 {rate(row.by_method[method].fn_rate)} · 待确认 {rate(row.by_method[method].uncertain_rate)}{row.by_method[method].insufficient ? ' · 样本不足' : ''}</p>)}</details></th>
      <td>{row.reviewed}</td><td>{row.confirmed}</td><td>{row.false_positive}</td><td>{row.false_negative}</td><td>{row.exception}</td><td>{row.recapture}</td><td>{rate(row.fp_rate)}</td><td>{rate(row.fn_rate)}</td><td>{rate(row.uncertain_rate)}</td><td>{row.insufficient ? <span className="aw-chip">样本不足</span> : '充足'}</td>
    </tr>)}</tbody></table></div>
  </>;
}
