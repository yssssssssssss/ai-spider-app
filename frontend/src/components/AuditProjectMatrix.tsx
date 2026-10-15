import { CSSProperties, useState } from 'react';
import { Link } from 'react-router-dom';
import { AuditMatrixPage, AuditProjectDetail, AuditProjectMatrix as Matrix, AuditRuleDistribution } from '../api';
import { StatusLegend, statusLabels } from './AuditWorkspaceUI';
import { categoryLabels, categoryOrder, codeStatus, deltaCategory, deltaGlyphs, pageLifelinePath, RuleDistribution, statusGlyphs } from './AuditProjectUI';

type Mode = 'pre' | 'post' | 'delta';
const modes: { key: Mode; label: string }[] = [{ key: 'pre', label: '上线前' }, { key: 'post', label: '上线后' }, { key: 'delta', label: '变化' }];
const strengths = { mandatory: '强制', conditional: '条件', recommended: '建议' };
function matrixRowNote(page: AuditMatrixPage, mode: Mode) {
  if (mode === 'pre' && !page.pre_target_id) return page.post_target_id ? '无上线前记录 · 独立检查' : '无上线前记录';
  if (mode !== 'pre' && !page.post_target_id) return '未巡检';
  if (mode === 'delta') return page.baseline_target_id ? '已关联基线' : '独立检查';
  return `${Array.from(page[mode]).filter(code => code === 'F').length} 处不符合`;
}
function matrixCell(page: AuditMatrixPage, index: number, mode: Mode) {
  if (!(mode === 'pre' ? page.pre_target_id : page.post_target_id)) return { label: matrixRowNote(page, mode), glyph: '—', className: 'ap-cell-absent' };
  if (mode === 'delta') {
    if (!page.baseline_target_id) return { label: '独立检查（无基线）', glyph: '∕', className: 'ap-cell-independent' };
    const category = deltaCategory[page.delta[index]] || 'not_comparable';
    return { label: categoryLabels[category], glyph: deltaGlyphs[category], className: `ap-cell-${category}` };
  }
  const status = codeStatus[page[mode][index]] || 'not_applicable';
  return { label: page[mode][index] === 'x' ? '未启用 / 不适用载体 / 共享证据' : statusLabels[status], glyph: statusGlyphs[status], className: `ap-cell-${status}` };
}
function distribution(matrix: Matrix, index: number, mode: Mode): AuditRuleDistribution {
  if (mode === 'pre') return matrix.pre_distribution[matrix.rules[index].rule_id];
  const counts = { fail: 0, pass: 0, uncertain: 0, uncovered: 0 };
  for (const page of matrix.pages) {
    const code = page.post_target_id ? page.post[index] : '-';
    counts[code === 'F' ? 'fail' : code === 'P' ? 'pass' : code === 'U' ? 'uncertain' : 'uncovered'] += 1;
  }
  return counts;
}

export default function AuditProjectMatrix({ project, matrix }: { project: AuditProjectDetail; matrix: Matrix }) {
  const [mode, setMode] = useState<Mode>('pre');
  const [ruleId, setRuleId] = useState('');
  const selectedIndex = Math.max(0, matrix.rules.findIndex(rule => rule.rule_id === ruleId));
  const selected = matrix.rules[selectedIndex];
  const counts = selected ? distribution(matrix, selectedIndex, mode) : null;
  // Systemic clusters use current pages, not the historical pre distribution.
  const systemic = selected && project.clusters.systemic.find(cluster => cluster.rule_id === selected.rule_id);
  const insight = systemic ? '系统性问题' : counts && counts.uncertain > 0 ? '证据缺口' : counts && counts.fail > 0 ? '页面问题' : '状态良好';
  return <><header className="aw-heading"><div><h1>规范 × 页面</h1><p>一列是一条规则，一行是一个页面；切到“变化”查看实际基线与上线后的差异。</p></div><div className="ap-view-switch" role="group" aria-label="矩阵模式">{modes.map(item => <button type="button" key={item.key} aria-pressed={mode === item.key} onClick={() => setMode(item.key)}>{item.label}</button>)}</div></header>
    {!matrix.rules.length ? <div className="aw-panel aw-empty">项目暂无上线前规范，归入上线前审核后即可查看矩阵。</div> : <div className="ap-matrix-layout" style={{ '--ap-matrix-min-width': `${180 + matrix.rules.length * 48}px` } as CSSProperties}><section className="aw-panel" aria-label="规范矩阵"><div className="aw-scroll ap-matrix-scroll" tabIndex={0} role="region" aria-label="页面与规则矩阵，可横向滚动"><table className="ap-matrix"><colgroup><col style={{ width: 168 }} /><col span={matrix.rules.length} /></colgroup><thead><tr><th scope="col" rowSpan={2}>页面</th>{matrix.clauses.map(group => <th scope="colgroup" colSpan={group.rule_ids.length} key={group.clause}>{group.clause || '未指定条款'}</th>)}</tr><tr>{matrix.rules.map(rule => <th scope="col" key={rule.rule_id}><button type="button" className="ap-column-button" title={rule.title} aria-label={`${rule.rule_id} ${rule.title}`} aria-pressed={selected.rule_id === rule.rule_id} onClick={() => setRuleId(rule.rule_id)}><span className="aw-mono">{rule.rule_id}</span><small>{strengths[rule.strength]}</small></button></th>)}</tr></thead>
      <tbody>{matrix.pages.map(page => <tr key={page.id}><th scope="row"><Link to={pageLifelinePath(project.id, page.id)}>{page.name}</Link><small>{matrixRowNote(page, mode)}</small></th>{matrix.rules.map((rule, index) => { const cell = matrixCell(page, index, mode); return <td key={rule.rule_id}><span className={`ap-matrix-cell ${cell.className} ${selected.rule_id === rule.rule_id ? 'is-selected' : ''}`} title={`${page.name} · ${rule.rule_id} · ${cell.label}`} aria-label={`${rule.rule_id}：${cell.label}`}>{cell.glyph}</span></td>; })}</tr>)}</tbody>
      <tfoot><tr><th scope="row">{mode === 'delta' ? '需处理页面数' : '不符合页面数'}</th>{matrix.rules.map((rule, index) => <td key={rule.rule_id}>{matrix.pages.filter(page => mode === 'delta' ? page.baseline_target_id && ['R', 'O', 'N'].includes(page.delta[index]) : page[mode][index] === 'F').length}</td>)}</tr></tfoot></table></div>
      {mode === 'delta' ? <div className="aw-legend">{categoryOrder.map(category => <span key={category}><i className={`aw-key ap-cell-${category}`} />{categoryLabels[category]} {deltaGlyphs[category]}</span>)}<span>∕ 独立检查（无基线）</span><span>— 未巡检</span><span>· 无法比对</span></div> : <><StatusLegend /><div className="aw-legend">× 不符合 · ✓ 符合 · ? 待确认 · ○ 未启用 / 不适用载体 / 共享证据 · · 不适用 / 未覆盖 · — 无上线前记录 / 未巡检</div></>}
    </section><aside className="aw-panel ap-rule-panel" aria-labelledby="matrix-rule-title"><span className="aw-muted">点击列头查看规则</span><h2 id="matrix-rule-title"><span className="aw-mono">{selected.rule_id}</span> {selected.title}</h2><div className="aw-chips"><span className="aw-chip">{strengths[selected.strength]}规则</span><span className="aw-chip">条款 {selected.clause || '未指定'}</span></div><h3>本项目 {matrix.pages.length} 个页面 · {mode === 'pre' ? '上线前' : '上线后'}</h3>{counts && <RuleDistribution counts={counts} />}
      {mode === 'delta' && <p className="aw-muted">分布显示最新上线后状态；矩阵变化使用各页面实际关联的基线。</p>}<div className={`ap-insight ${systemic ? 'is-systemic' : insight === '证据缺口' ? 'is-evidence' : ''}`}><strong>{insight}</strong><p>{systemic ? `当前 ${systemic.count} / ${project.page_count} 个页面不符合，达到 ≥3 页或 ≥30% 页面阈值，根因可能来自共享组件或模板。` : counts?.uncertain ? `${counts.uncertain} 个页面待确认，先补充证据再判定。` : counts?.fail ? `${counts.fail} 个页面不符合，可按页面逐项整改。` : '当前展示阶段没有不符合或待确认记录；未覆盖部分仍需检查。'}</p></div><div className="ap-rule-expected"><h3>规范预期</h3><p>{selected.expected || '未提供'}</p>{selected.duplicate_of && <p>与 {selected.duplicate_of} 共享证据，不重复计数。</p>}</div>
    </aside></div>}
  </>;
}
