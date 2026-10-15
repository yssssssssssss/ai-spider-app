import { Link } from 'react-router-dom';
import { AuditCategory, AuditMatrixPage, AuditProjectListItem, AuditRuleDistribution, AuditStage, AuditStatus } from '../api';
import { statusLabels, stripGradient } from './AuditWorkspaceUI';

export const stageOrder: AuditStage[] = ['review', 'recheck', 'baseline', 'post', 'closed'];
export const stageLabels: Record<AuditStage, string> = { review: '上线前审核', recheck: '整改复查', baseline: '基线就绪', post: '上线后巡检', closed: '已闭环' };
export const stageHints: Record<AuditStage, string> = { review: '首次审核，仍需处理或补证', recheck: '多次审核，仍需处理或补证', baseline: '上线前无不符合、无待确认', post: '已巡检，等待处理或关联基线', closed: '已关联基线，问题与待确认清零' };
export const categoryOrder: Exclude<AuditCategory, 'not_comparable'>[] = ['fixed', 'still_open', 'regressed', 'new_issue', 'kept', 'needs_confirmation'];
export const categoryLabels: Record<AuditCategory, string> = { fixed: '已修', still_open: '未修', regressed: '回归', new_issue: '新增', kept: '保持', needs_confirmation: '待确认', not_comparable: '无法比对' };
export const categoryColors: Record<AuditCategory, string> = { fixed: '#34D399', still_open: '#E8875A', regressed: '#FF5A36', new_issue: '#D96BFF', kept: '#2F7D62', needs_confirmation: '#F2C14E', not_comparable: '#4A5262' };
export const statusGlyphs: Record<AuditStatus, string> = { fail: '×', pass: '✓', uncertain: '?', not_applicable: '·', disabled: '○' };
export const codeStatus: Record<string, AuditStatus> = { F: 'fail', U: 'uncertain', P: 'pass', '-': 'not_applicable', x: 'disabled' };
export const deltaCategory: Record<string, AuditCategory> = { F: 'fixed', O: 'still_open', R: 'regressed', N: 'new_issue', K: 'kept', U: 'needs_confirmation', '-': 'not_comparable' };
export const deltaGlyphs: Record<AuditCategory, string> = { fixed: '↑', still_open: '=', regressed: '↓', new_issue: '+', kept: '✓', needs_confirmation: '?', not_comparable: '·' };
export function pageLifelinePath(projectId: string, pageKey: string) { return `/audit-projects/${projectId}/pages/${encodeURIComponent(pageKey)}`; }
export function StageBadge({ stage }: { stage: AuditStage }) { return <span className={`aw-chip ap-stage-${stage}`}>{stageLabels[stage]}</span>; }
export function CategoryBadge({ category }: { category: AuditCategory }) { return <span className={`aw-chip ap-category-${category}`}>{categoryLabels[category]}</span>; }
export function ProjectViews({ id, view }: { id: string; view: 'cockpit' | 'matrix' | 'lifeline' }) {
  return <nav className="ap-view-switch" aria-label="项目视图"><Link to={`/audit-projects/${id}`} aria-current={view === 'cockpit' ? 'page' : undefined}>驾驶舱</Link><Link to={`/audit-projects/${id}?view=matrix`} aria-current={view === 'matrix' ? 'page' : undefined}>规范矩阵</Link>{view === 'lifeline' && <span aria-current="page">页面生命线</span>}</nav>;
}
export function StageBar({ project }: { project: AuditProjectListItem }) {
  const label = stageOrder.map(stage => `${stageLabels[stage]} ${project.stages[stage].count}`).join(' · ');
  return <div className="ap-stage-distribution"><div className="ap-mini-bar" role="img" aria-label={label}>{stageOrder.filter(stage => project.stages[stage].count > 0).map(stage => <span className={`ap-stage-fill-${stage}`} key={stage} style={{ flex: project.stages[stage].count }} />)}</div><small>{label}</small></div>;
}
export function RuleDistribution({ counts }: { counts: AuditRuleDistribution }) {
  const items = [['fail', '不符合'], ['uncertain', '待确认'], ['pass', '符合'], ['uncovered', '未覆盖 / 不适用']] as const;
  const label = items.map(([key, text]) => `${text} ${counts[key]}`).join(' · ');
  return <div className="ap-distribution"><div className="ap-mini-bar" role="img" aria-label={label}>{items.filter(([key]) => counts[key] > 0).map(([key]) => <span className={`ap-distribution-${key}`} key={key} style={{ flex: counts[key] }} />)}</div><p>{label}</p></div>;
}
export function PageStatusStrip({ label, codes, present }: { label: string; codes: string; present: boolean }) {
  const description = Object.entries(codeStatus).map(([code, status]) => `${code === 'x' ? '未启用 / 不适用载体 / 共享证据' : statusLabels[status]} ${Array.from(codes).filter(value => value === code).length}`).join('，');
  return <div className="ap-page-strip"><span>{label}</span>{present ? <span className="ap-status-strip" role="img" aria-label={`${label}：${description}`} title={description} style={{ background: stripGradient(codes) }}>{Array.from(codes, (code, index) => <span key={index} aria-hidden="true">{statusGlyphs[codeStatus[code]] || '·'}</span>)}</span> : <span className="ap-strip-absent">未巡检</span>}</div>;
}
export function pageDeltaText(page: AuditMatrixPage) {
  if (!page.post_target_id) return '尚未上线后巡检';
  if (!page.baseline_target_id) return '独立检查';
  const parts = categoryOrder.map(category => {
    const count = Array.from(page.delta).filter(code => deltaCategory[code] === category).length;
    return count ? `${categoryLabels[category]} ${count}` : '';
  }).filter(Boolean);
  return parts.join(' · ') || '无可比对规则';
}
