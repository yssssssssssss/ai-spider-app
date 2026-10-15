import { useEffect, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { AuditProjectDetail as Project, AuditProjectMatrix as Matrix, AuditRule, AuditRun, AuditStage, getAuditProject, getAuditProjectMatrix, getAuditSpecVersion, listAuditRuns } from '../api';
import { DemoBadge, LoadState, outcomeLabels } from '../components/AuditWorkspaceUI';
import { pageDeltaText, pageLifelinePath, PageStatusStrip, ProjectViews, stageHints, stageLabels, stageOrder, StageBadge } from '../components/AuditProjectUI';
import AuditProjectFlow from '../components/AuditProjectFlow';
import AuditProjectMatrix from '../components/AuditProjectMatrix';

function LifecycleRail({ project, selected, dominant, onSelect }: { project: Project; selected: AuditStage | null; dominant: AuditStage | null; onSelect: (stage: AuditStage | null) => void }) {
  return <section className="aw-panel ap-rail-panel" aria-labelledby="rail-title"><div className="aw-heading"><h2 id="rail-title">生命周期轨道</h2><p>每个圆点是一个页面，点击阶段筛选下方页面。</p></div><div className="aw-scroll" tabIndex={0} role="region" aria-label="生命周期阶段，可横向滚动"><div className="ap-rail">
    <button type="button" className="ap-stage-node ap-spec-node" aria-pressed={false} onClick={() => onSelect(null)}><span className="ap-node-number"><i />01</span><strong>规范确认</strong><div className="ap-spec-labels">{(['pre', 'post'] as const).map(phase => <span key={phase}>{phase === 'pre' ? '上线前' : '上线后'}：{project.stage_specs[phase].map(version => version.label).join('、') || '暂无规范'}</span>)}</div><small>规范版本 · 查看全部页面</small></button>
    {stageOrder.map((stage, index) => <button type="button" className={`ap-stage-node ap-stage-${stage} ${dominant === stage ? 'is-current' : ''}`} key={stage} aria-current={dominant === stage ? 'step' : undefined} aria-pressed={selected === stage} onClick={() => onSelect(selected === stage ? null : stage)}><span className="ap-node-number"><i />0{index + 2}</span><strong>{stageLabels[stage]}</strong><span className="ap-stage-count">{project.stages[stage].count}</span><small>{stageHints[stage]}</small><span className="ap-page-dots">{project.stages[stage].pages.map(page => <span className={`ap-page-dot ap-dot-${page.outcome}`} key={page.id} title={`${page.name} · ${outcomeLabels[page.outcome]}`} aria-label={`${page.name} · ${outcomeLabels[page.outcome]}`}>{page.outcome === 'clean' || page.outcome === 'partial' ? '✓' : page.outcome === 'issues' ? '×' : '?'}</span>)}</span></button>)}
  </div></div></section>;
}

function ProjectClusters({ project, matrix, rules }: { project: Project; matrix: Matrix; rules: Map<string, AuditRule> }) {
  const { regressed, systemic, carried, evidence_gaps: gaps } = project.clusters;
  const title = (id: string) => rules.get(id)?.title || id;
  const empty = !regressed.total && !systemic.length && !carried.total && !gaps.total;
  const ruleIndexes = new Map(matrix.rules.map((rule, index) => [rule.rule_id, index]));
  return <section className="ap-clusters" aria-labelledby="clusters-title"><div className="aw-heading"><h2 id="clusters-title">需要处理 · 按影响聚类</h2><span className="aw-muted">按规则、影响页面与生命周期聚合</span></div>
    {empty && <div className="aw-panel aw-empty">当前没有需要处理的聚类。可继续查看页面生命线与规范覆盖情况。</div>}
    {regressed.total > 0 && <article className="aw-panel ap-cluster ap-cluster-regressed"><div className="aw-heading"><h3><span className="aw-chip ap-category-regressed">发布回归</span> 上线前符合，上线后不符合</h3><span className="aw-muted">{regressed.total} 项 · 优先处理</span></div><div className="ap-regression-grid">{regressed.items.map(item => <Link className="ap-regression" to={pageLifelinePath(project.id, item.page.id)} key={`${item.rule_id}-${item.page.target_id}`}><span className="aw-mono">{item.rule_id}</span><strong>{title(item.rule_id)}</strong><span>{item.page.name}</span><span className="aw-chips"><span className="aw-status aw-status-pass">符合</span> → <span className="aw-status aw-status-fail">不符合</span></span></Link>)}</div></article>}
    {systemic.length > 0 && <article className="aw-panel ap-cluster"><div className="aw-heading"><h3><span className="aw-chip ap-systemic-chip">系统性问题</span> 跨页面重复不符合</h3><span className="aw-muted">{systemic.length} 条规则</span></div>{systemic.map(cluster => { const failed = new Set(cluster.pages.map(page => page.id)); return <div className="ap-cluster-rule" key={cluster.rule_id}><h3><span className="aw-mono">{cluster.rule_id}</span> {title(cluster.rule_id)}</h3><p>{cluster.count} / {project.page_count} 个页面当前不符合</p><div className="ap-systemic-strip" role="img" aria-label={matrix.pages.map(page => `${page.name} ${failed.has(page.id) ? '不符合' : '未进入该聚类'}`).join('，')}>{matrix.pages.map(page => <span className={`ap-systemic-cell ${failed.has(page.id) ? 'ap-cell-fail' : 'ap-cell-not_applicable'}`} key={page.id} title={`${page.name} · ${failed.has(page.id) ? '不符合' : '未进入该聚类'}`} aria-label={`${page.name} · ${failed.has(page.id) ? '不符合' : '未进入该聚类'}`}>{failed.has(page.id) ? '×' : '·'}</span>)}</div></div>; })}<p className="ap-insight">同一规则在多个页面重复不符合，根因可能来自共享组件或楼层模板。建议先核查组件，再批量复查相关页面。</p></article>}
    {carried.total > 0 && <article className="aw-panel ap-cluster"><div className="aw-heading"><h3><span className="aw-chip ap-category-still_open">跨阶段未修</span> 上线前已指出，上线后仍不符合</h3><span className="aw-muted">{carried.rules.length} 条规则 · {carried.total} 项未修</span></div>{carried.rules.map(rule => { const handled = new Set([...rule.pages, ...rule.fixed_pages].map(page => page.id)); const index = ruleIndexes.get(rule.rule_id); const pending = matrix.pages.filter(page => !handled.has(page.id) && index !== undefined && (page.post_target_id ? page.post : page.pre)[index] === 'F'); return <div className="ap-cluster-rule" key={rule.rule_id}><h3><span className="aw-mono">{rule.rule_id}</span> {title(rule.rule_id)}</h3><div className="aw-chips">{rule.pages.map(page => <Link className="aw-chip ap-category-still_open" key={page.target_id} to={pageLifelinePath(project.id, page.id)}>{page.name} · 未修</Link>)}{rule.fixed_pages.map(page => <Link className="aw-chip ap-category-fixed" key={page.target_id} to={pageLifelinePath(project.id, page.id)}>{page.name} · 已修</Link>)}{pending.map(page => <Link className="aw-chip" key={page.id} to={pageLifelinePath(project.id, page.id)}>{page.name} · 待整改</Link>)}</div></div>; })}</article>}
    {gaps.total > 0 && <article className="aw-panel ap-cluster ap-cluster-evidence"><div className="aw-heading"><h3><span className="aw-chip ap-category-needs_confirmation">证据缺口</span> {gaps.total} 项待确认</h3><span className="aw-muted">{gaps.pages.length} 个页面</span></div><p>比对待确认 {gaps.comparison_total} · 独立检查待确认 {gaps.independent_total}。先补证，再判定。</p><div className="aw-chips">{gaps.pages.map(page => <Link className="aw-chip" to={pageLifelinePath(project.id, page.id)} key={page.id}>{page.name} · {page.count}</Link>)}</div></article>}
  </section>;
}

function PageCards({ project, matrix, selected }: { project: Project; matrix: Matrix; selected: AuditStage | null }) {
  const pageStages = new Map(stageOrder.flatMap(stage => project.stages[stage].pages.map(page => [page.id, stage] as const)));
  const pages = selected ? matrix.pages.filter(page => pageStages.get(page.id) === selected) : matrix.pages;
  return <section className="ap-pages" aria-labelledby="pages-title"><div className="aw-heading"><h2 id="pages-title">页面生命线 <span className="aw-muted">{selected ? stageLabels[selected] : '全部页面'} · {pages.length}</span></h2><span className="aw-muted">× 不符合 · ? 待确认 · ✓ 符合 · · 不适用 / 未覆盖</span></div><div className="ap-page-grid">{pages.map(page => <article className="aw-panel ap-page-card" key={page.id}><div className="aw-heading"><h3><Link to={pageLifelinePath(project.id, page.id)}>{page.name}</Link></h3><StageBadge stage={pageStages.get(page.id) || 'review'} /></div><span className="aw-mono">{page.id.startsWith('t:') ? '无业务键 · ' : '业务键 · '}{page.id}</span><PageStatusStrip label="上线前" codes={page.pre} present={!!page.pre_target_id} /><PageStatusStrip label="上线后" codes={page.post} present={!!page.post_target_id} /><p className="ap-page-delta">{pageDeltaText(page)}</p><Link className="ap-open-link" to={pageLifelinePath(project.id, page.id)}>查看生命线 →</Link></article>)}</div>{!pages.length && <div className="aw-empty">该阶段暂无页面。</div>}</section>;
}

export default function AuditProjectDetail() {
  const { id = '' } = useParams();
  const [params] = useSearchParams();
  const view = params.get('view') === 'matrix' ? 'matrix' : 'cockpit';
  const [data, setData] = useState<{ project: Project; matrix: Matrix; runs: AuditRun[]; rules: Map<string, AuditRule> } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);
  const [selected, setSelected] = useState<AuditStage | null>(null);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(false); setData(null); setSelected(null);
    (async () => {
      const [{ data: project }, { data: matrix }, { data: runs }] = await Promise.all([getAuditProject(id), getAuditProjectMatrix(id), listAuditRuns({ project_id: id })]);
      const versions = await Promise.all([...new Set(runs.map(run => run.spec_version_id))].map(versionId => getAuditSpecVersion(versionId)));
      const rules = new Map(versions.flatMap(version => version.data.rules_json.map(rule => [rule.rule_id, rule] as const)));
      if (active) setData({ project, matrix, runs, rules });
    })().catch(() => { if (active) setError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id, reload]);
  const project = data?.project;
  const dominant = project?.page_count ? stageOrder.reduce((best, stage) => project.stages[stage].count >= project.stages[best].count ? stage : best, stageOrder[0]) : null;
  const demo = data?.runs.some(run => run.source_ref_json.demo === true);
  const fixed = project?.flow.counts.fixed || 0;
  const carried = project?.flow.counts.still_open || 0;
  const closure = fixed + carried ? Math.round(fixed / (fixed + carried) * 100) : null;
  return <div className="aw"><div className="aw-heading"><nav className="aw-breadcrumb" aria-label="面包屑"><Link to="/audit-projects">项目走查</Link><span>/</span>{view === 'matrix' ? <><Link to={`/audit-projects/${id}`}>{project?.name || '项目'}</Link><span>/</span><span>规范矩阵</span></> : <span>{project?.name || '项目驾驶舱'}</span>}</nav><ProjectViews id={id} view={view} /></div>
    {loading || !data ? <LoadState loading={loading} error={error} retry={() => setReload(value => value + 1)} /> : view === 'matrix' ? <AuditProjectMatrix key={id} project={data.project} matrix={data.matrix} /> : <>
      <header className="ap-project-header"><div className="aw-run-header"><div className="aw-chips">{(['pre', 'post'] as const).flatMap(phase => data.project.stage_specs[phase].map(version => <Link className={`aw-chip aw-${phase}`} key={`${phase}-${version.id}`} to={`/specs/${version.spec_id}?version=${version.id}`}>{phase === 'pre' ? '上线前' : '上线后'}规范 {version.label}</Link>))}{dominant && <span className="aw-chip aw-post">当前主要阶段 · {stageLabels[dominant]}</span>}{demo && <DemoBadge source={{ demo: true }} />}</div><h1>{data.project.name}</h1><p className="aw-summary">{data.project.page_count} 个页面、{data.project.run_count} 次审核，{data.matrix.pages.filter(page => page.pre_target_id).length} 个页面已有上线前记录，{data.matrix.pages.filter(page => page.post_target_id).length} 个已进入上线后巡检；发布回归 {data.project.clusters.regressed.total} 项，系统性问题 {data.project.clusters.systemic.length} 条规则，证据缺口 {data.project.clusters.evidence_gaps.total} 项。</p></div><div className="ap-project-metrics"><div className="ap-metric"><strong>{closure === null ? '暂无' : `${closure}%`}</strong><span>上线前问题闭环率 · {fixed}/{fixed + carried}</span></div><div className="ap-metric"><strong className="ap-regression-number">{data.project.clusters.regressed.total}</strong><span>发布回归</span></div><div className="ap-metric"><strong className="aw-warning">{data.project.clusters.evidence_gaps.total}</strong><span>证据缺口</span></div></div></header>
      <LifecycleRail project={data.project} selected={selected} dominant={dominant} onSelect={setSelected} /><div className="ap-cockpit-columns"><ProjectClusters project={data.project} matrix={data.matrix} rules={data.rules} /><AuditProjectFlow flow={data.project.flow} /></div><PageCards project={data.project} matrix={data.matrix} selected={selected} />
    </>}
  </div>;
}
