import { imageFileUrl } from '../api';

const labels: Record<string, string> = { pass: '符合', fail: '不符合', uncertain: '待确认', not_applicable: '不适用' };

export default function AnalysisDetails({ analysis, onEvidence }: { analysis: any; onEvidence: (evidence: any) => void }) {
  const report = analysis.inspection_json;
  const provenance = analysis.provenance_json;
  return <>
    <p>{provenance?.skill?.name || analysis.skill_key || '默认分析'} · {analysis.status}
      {provenance?.skill?.version && ` · Skill v${provenance.skill.version}`}</p>
    {report && <section>
      <h3>{report.specification.title} · 规范 {report.specification.version}</h3>
      <p>来源：{report.specification.source}</p>
      <p>{Object.entries(report.summary).map(([key, value]) => `${labels[key]} ${value}`).join(' · ')}</p>
      {report.checks.map((check: any) => <article key={check.rule_id} style={{ borderTop: '1px solid var(--border)', padding: '16px 0' }}>
        <strong>{check.rule_id} · {check.clause} · {labels[check.status]}</strong>
        <p style={{ whiteSpace: 'pre-wrap' }}>标准：{check.expected}</p>
        <p>观察：{check.observed || '未取得观察结果'}</p>
        <p>依据：{check.reason}</p>
        {check.evidence.map((evidence: any, index: number) => <button key={index} type="button" className="btn-secondary btn-sm" onClick={() => onEvidence(evidence)}>查看证据区域</button>)}
      </article>)}
      <details><summary>当时的规范原文</summary><pre style={{ whiteSpace: 'pre-wrap' }}>{report.specification.document}</pre></details>
    </section>}
    {analysis.design_analysis && <section><h4>设计分析</h4><p style={{ whiteSpace: 'pre-wrap' }}>{analysis.design_analysis}</p></section>}
    {analysis.ops_analysis && <section><h4>运营分析</h4><p style={{ whiteSpace: 'pre-wrap' }}>{analysis.ops_analysis}</p></section>}
    {!report && analysis.result_json && <section><h4>分析结果</h4><pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(analysis.result_json, null, 2)}</pre></section>}
    {provenance && <details><summary>模型调用与版本记录</summary>
      {(provenance.model_calls || []).map((call: any, index: number) => <p key={index}>
        {call.purpose === 'target_validation' ? '目标页判断' : '截图分析'} · {call.endpoint_host || call.provider} · 请求 {call.requested_model} · 返回 {call.response_model || '接口未提供模型名称'} · {call.status} · {call.duration_ms} ms
      </p>)}
      <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{JSON.stringify(provenance, null, 2)}</pre>
    </details>}
  </>;
}

export function EvidencePreview({ evidence }: { evidence: any }) {
  if (!evidence) return null;
  const [width, height] = evidence.image_size;
  const [left, top, right, bottom] = evidence.bbox_px;
  return <div style={{ position: 'relative' }}>
    <img src={imageFileUrl(evidence.image_id)} alt="检查项原始截图" style={{ width: '100%', display: 'block' }} />
    <svg viewBox={`0 0 ${width} ${height}`} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}>
      <rect x={left} y={top} width={right - left} height={bottom - top} fill="none" stroke="#ff453a" strokeWidth={Math.max(3, width / 180)} />
    </svg>
  </div>;
}
