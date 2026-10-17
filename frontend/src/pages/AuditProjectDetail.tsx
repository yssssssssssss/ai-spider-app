import { ReactNode, useCallback, useEffect, useId, useMemo, useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';
import { AuditOutcome, AuditProjectDetail as Project, AuditProjectMatrix as Matrix, AuditRule, AuditRun, AuditStage, getAuditProject, getAuditProjectMatrix, getAuditSpecVersion, listAuditRuns, listAuditTargets } from '../api';
import { DemoBadge, LoadState } from '../components/AuditWorkspaceUI';
import { pageDeltaText, pageLifelinePath, PageStatusStrip, ProjectViews, stageHints, stageLabels, stageOrder, StageBadge } from '../components/AuditProjectUI';
import AuditProjectFlow from '../components/AuditProjectFlow';
import { DashboardRing, OutcomeBar } from '../components/AuditDashboardUI';
import { AssignAuditRunsDialog, AuditJobsSection, AuditLaunchDialog } from '../components/AuditJobUI';
import { useAuth } from '../auth';
import AuditProjectMatrix from '../components/AuditProjectMatrix';

function LifecycleRail({ project, selected, dominant, onSelect }: { project: Project; selected: AuditStage | null; dominant: AuditStage | null; onSelect: (stage: AuditStage | null) => void }) {
  const versionCount = new Set([...project.stage_specs.pre, ...project.stage_specs.post].map(version => version.id)).size;
  const steps = ['spec', 'review', 'recheck', 'baseline', 'launch', 'post', 'closed'] as const;
  const furthest = steps.reduce((last, step, index) => step !== 'spec' && step !== 'launch' && project.stages[step].count > 0 ? index : last, 0);
  return <section className="aw-panel ap-rail-panel" aria-labelledby="rail-title">
    <div><h2 id="rail-title">生命周期轨道</h2><p className="aw-muted ap-rail-help">点击阶段筛选下方页面列表；需要处理与规则流向始终统计全项目。</p></div>
    <div className="ap-rail-bands" aria-hidden="true"><span>上线前</span><span>上线后</span></div>
    <ol className="ap-rail">{steps.map((step, index) => {
      const track = <span className="ap-rail-track" aria-hidden="true"><i /></span>;
      const className = `ap-rail-step ${index <= furthest ? 'is-reached' : ''} ${index === furthest ? 'is-furthest' : ''}`;
      if (step === 'launch') return <li key={step} className={`${className} ap-launch-marker`}>{track}<strong>上线</strong></li>;
      if (step === 'spec') return <li key={step} className={className}>{track}<button type="button" className="ap-stage-node ap-spec-node" aria-pressed={selected === null} onClick={() => onSelect(null)}>
        <span className="ap-node-number">01 · 项目规范</span><strong>规范确认</strong><span className="ap-stage-count">{versionCount}<small> 个版本</small></span>
        <small>前 {project.stage_specs.pre.length} · 后 {project.stage_specs.post.length}</small><span className="ap-spec-track" aria-hidden="true" /><small>查看全部 {project.page_count} 个页面</small>
      </button></li>;
      const outcomes: Record<AuditOutcome, number> = { issues: 0, needs_confirmation: 0, partial: 0, clean: 0, capture_failed: 0 };
      project.stages[step].pages.forEach(page => outcomes[page.outcome]++);
      return <li key={step} className={className}>{track}<button type="button" className={`ap-stage-node ${dominant === step ? 'is-current' : ''}`}
        aria-current={dominant === step ? 'step' : undefined} aria-pressed={selected === step} onClick={() => onSelect(selected === step ? null : step)}>
        <span className="ap-node-number">0{index > 4 ? index : index + 1}{dominant === step ? ' · 主要阶段' : ''}</span><strong>{stageLabels[step]}</strong>
        <span className="ap-stage-count">{project.stages[step].count}<small> 页</small></span><small>{stageHints[step]}</small>
        <OutcomeBar outcomes={outcomes} label={stageLabels[step]} />
      </button></li>;
    })}</ol>
    <div className="aw-legend"><span><i className="aw-key aw-fill-fail" />不符合</span><span><i className="aw-key aw-fill-uncertain" />待确认</span><span><i className="aw-key aw-fill-pass" />部分审核 / 全部符合</span><span><i className="aw-key aw-fill-capture" />采集失败</span></div>
  </section>;
}

function CappedList({ items, className = 'aw-chips', unit = '个页面' }: { items: { key: string; content: ReactNode }[]; className?: string; unit?: string }) {
  const [expanded, setExpanded] = useState(false);
  const id = useId();
  return <div className="ap-capped-list"><div className={className} id={id}>{(expanded ? items : items.slice(0, 8)).map(item => <div className="ap-capped-item" key={item.key}>{item.content}</div>)}</div>
    {items.length > 8 && <button type="button" className="aw-secondary ap-expand" aria-expanded={expanded} aria-controls={id} onClick={() => setExpanded(value => !value)}>{expanded ? '收起页面' : `+${items.length - 8} ${unit}`}</button>}
  </div>;
}

function CarriedRule({ rule, project, matrix, title }: { rule: Project['clusters']['carried']['rules'][number]; project: Project; matrix: Matrix; title: string }) {
  const handled = new Set([...rule.pages, ...rule.fixed_pages].map(page => page.id));
  const index = matrix.rules.findIndex(item => item.rule_id === rule.rule_id);
  const pending = matrix.pages.filter(page => !handled.has(page.id) && index >= 0 && (page.post_target_id ? page.post : page.pre)[index] === 'F');
  const items = [
    ...rule.pages.map(page => ({ page, key: `${page.target_id}-open`, label: '未修', tone: 'still_open' })),
    ...rule.fixed_pages.map(page => ({ page, key: `${page.target_id}-fixed`, label: '已修', tone: 'fixed' })),
    ...pending.map(page => ({ page, key: `${page.id}-pending`, label: '待整改', tone: 'still_open' })),
  ];
  return <div className="ap-cluster-rule"><h3><span className="aw-mono">{rule.rule_id}</span> {title}</h3>
    <CappedList items={items.map(({ page, key, label, tone }) => ({ key, content: <Link className={`aw-chip ap-category-${tone}`} to={pageLifelinePath(project.id, page.id)}>{page.name} · {label}</Link> }))} />
  </div>;
}

function ProjectClusters({ project, matrix, rules, simulated }: { project: Project; matrix: Matrix; rules: Map<string, AuditRule>; simulated: boolean }) {
  const [allSystemic, setAllSystemic] = useState(false);
  const systemicId = useId();
  const { regressed, systemic, carried, evidence_gaps: gaps } = project.clusters;
  const title = (id: string) => rules.get(id)?.title || id;
  const ranked = [...systemic].sort((a, b) => b.count - a.count || a.rule_id.localeCompare(b.rule_id));
  const empty = !regressed.total && !systemic.length && !carried.total && !gaps.total;
  return <section className="ap-clusters" aria-labelledby="clusters-title">
    <div className="aw-heading"><h2 id="clusters-title">需要处理</h2><span className="aw-muted">按规则与影响范围聚类</span></div>
    <div className="ap-cockpit-columns"><div className="ap-systemic-column">
    {empty && <div className="aw-panel aw-empty">当前没有需要处理的聚类。可继续查看页面生命线与规范覆盖情况。</div>}
    {systemic.length > 0 && <article className="aw-panel ap-cluster"><div className="aw-heading"><h3>系统性问题</h3><span className="aw-chip ap-systemic-chip">{systemic.length} 条规则</span></div>
      <p className="aw-muted ap-cluster-description">最新审核中，同一规则在 ≥3 个或 ≥30% 页面不符合，通常来自共享组件或楼层模板。</p>
      <ol className="ap-systemic-list" id={systemicId}>{(allSystemic ? ranked : ranked.slice(0, 5)).map(cluster => <li key={cluster.rule_id}>
        <div className="ap-systemic-label"><span className="aw-mono">{cluster.rule_id}</span><strong>{title(cluster.rule_id)}</strong><span className="ap-systemic-count">{cluster.count} / {project.page_count}</span></div>
        <div className="ap-systemic-bar" role="img" aria-label={`${cluster.rule_id} ${title(cluster.rule_id)}：${cluster.count} / ${project.page_count} 个页面不符合`}><span style={{ width: `${project.page_count ? cluster.count / project.page_count * 100 : 0}%` }} /></div>
      </li>)}</ol>
      {systemic.length > 5 && <button type="button" className="aw-secondary ap-expand" aria-expanded={allSystemic} aria-controls={systemicId} onClick={() => setAllSystemic(value => !value)}>{allSystemic ? '收起规则' : `展开全部 ${systemic.length} 条`}</button>}
      <p className="ap-insight">同一规则在多个页面重复不符合，根因可能来自共享组件或楼层模板。建议先核查组件，再批量复查相关页面。</p>
    </article>}
    </div><div className="ap-followup-column">
    {regressed.total > 0 && <details className="aw-panel ap-cluster ap-cluster-regressed"><summary><span><strong>发布回归 {simulated && <span className="aw-chip aw-demo">模拟数据</span>}</strong><small className="aw-muted">上线前符合、上线后不符合的规则，优先处理。</small></span><span className="aw-status aw-status-fail">{regressed.total} 项</span></summary>
      <CappedList className="ap-regression-grid" unit="个页面记录" items={regressed.items.map(item => ({ key: `${item.rule_id}-${item.page.target_id}`, content: <Link className="ap-regression" to={pageLifelinePath(project.id, item.page.id)}><span className="aw-mono">{item.rule_id}</span><strong>{title(item.rule_id)}</strong><span>{item.page.name}</span><span className="aw-chips"><span className="aw-status aw-status-pass">符合</span> → <span className="aw-status aw-status-fail">不符合</span></span></Link> }))} />
    </details>}
    {carried.total > 0 && <details className="aw-panel ap-cluster"><summary><span><strong>跨阶段未修 {simulated && <span className="aw-chip aw-demo">模拟数据</span>}</strong><small className="aw-muted">上线前已指出、上线后仍不符合。</small></span><span className="aw-status aw-status-fail">{carried.total} 项</span></summary>
      {carried.rules.map(rule => <CarriedRule key={rule.rule_id} rule={rule} project={project} matrix={matrix} title={title(rule.rule_id)} />)}
    </details>}
    {gaps.total > 0 && <details className="aw-panel ap-cluster ap-cluster-evidence"><summary><span><strong>证据缺口</strong><small className="aw-muted">结论为待确认，需补证据或人工判定。</small></span><span className="aw-warning">{gaps.total} 项</span></summary>
      <p>比对待确认 {gaps.comparison_total} · 独立检查待确认 {gaps.independent_total}。先补证，再判定。</p>
      <CappedList items={gaps.pages.map(page => ({ key: page.id, content: <Link className="aw-chip" to={pageLifelinePath(project.id, page.id)}>{page.name} · {page.count}</Link> }))} />
    </details>}
    <AuditProjectFlow flow={project.flow} simulated={simulated} />
    </div></div>
  </section>;
}

function PageCards({ project, matrix, selected, onClear }: { project: Project; matrix: Matrix; selected: AuditStage | null; onClear: () => void }) {
  const [search, setSearch] = useState('');
  const [pageIndex, setPageIndex] = useState(1);
  useEffect(() => setPageIndex(1), [selected]);
  const pageStages = useMemo(() => new Map(stageOrder.flatMap(stage => project.stages[stage].pages.map(page => [page.id, stage] as const))), [project.stages]);
  const query = search.trim().toLowerCase();
  const pages = matrix.pages.filter(page => (!selected || pageStages.get(page.id) === selected) && (!query || page.name.toLowerCase().includes(query) || page.id.toLowerCase().includes(query)));
  const pageCount = Math.max(1, Math.ceil(pages.length / 20));
  const currentPage = Math.min(pageIndex, pageCount);
  const visible = pages.slice((currentPage - 1) * 20, currentPage * 20);
  return <section id="project-pages" className="aw-panel ap-pages" aria-labelledby="pages-title">
    <div className="aw-heading"><div><h2 id="pages-title">页面生命线</h2>{selected && <button type="button" className="aw-secondary ap-filter-pill" onClick={onClear} aria-label={`清除${stageLabels[selected]}筛选`}>筛选：{stageLabels[selected]} <span aria-hidden="true">×</span></button>}<p>{selected ? stageLabels[selected] : '全部页面'} · {pages.length} 个页面</p></div>
      <label className="ap-page-search">搜索页面<input type="search" value={search} placeholder="页面名称或 ID" onChange={event => { setSearch(event.target.value); setPageIndex(1); }} /></label>
    </div>
    <p className="aw-muted">× 不符合 · ? 待确认 · ✓ 符合 · · 不适用 / 未覆盖</p>
    <div className="aw-scroll ap-page-table-scroll" tabIndex={0} role="region" aria-label="页面生命线表格，可横向滚动">
    <table className="ap-page-table"><caption className="aw-sr-only">{selected ? stageLabels[selected] : '全部页面'}，共 {pages.length} 个页面，第 {currentPage} / {pageCount} 页</caption>
      <thead><tr><th scope="col">页面 / 业务键</th><th scope="col">当前阶段</th><th scope="col">上线前</th><th scope="col">上线后</th><th scope="col">变化</th><th scope="col"><span className="aw-sr-only">操作</span></th></tr></thead>
      <tbody>{visible.map(page => <tr key={page.id}>
        <th scope="row"><Link to={pageLifelinePath(project.id, page.id)}>{page.name}</Link><small className="aw-mono">{page.id.startsWith('t:') ? '无业务键 · ' : ''}{page.id}</small></th>
        <td data-label="当前阶段"><StageBadge stage={pageStages.get(page.id) || 'review'} /></td>
        <td data-label="上线前"><PageStatusStrip label="上线前" codes={page.pre} present={!!page.pre_target_id} /></td>
        <td data-label="上线后"><PageStatusStrip label="上线后" codes={page.post} present={!!page.post_target_id} /></td>
        <td data-label="变化" className="ap-page-delta">{pageDeltaText(page)}</td>
        <td><Link className="ap-open-link" to={pageLifelinePath(project.id, page.id)} aria-label={`查看 ${page.name} 的生命线`}>查看 →</Link></td>
      </tr>)}</tbody>
    </table>
    </div>
    {!pages.length && <div className="aw-empty">{query ? '没有匹配的页面，请调整搜索条件。' : '该阶段暂无页面。'}</div>}
    <nav className="ap-pagination" aria-label="页面生命线分页"><span className="aw-muted" role="status">第 {currentPage} / {pageCount} 页 · 共 {pages.length} 个页面</span><div className="aw-actions">
      <button type="button" className="aw-secondary" disabled={currentPage <= 1} onClick={() => setPageIndex(currentPage - 1)}>上一页</button>
      <button type="button" className="aw-secondary" disabled={currentPage >= pageCount} onClick={() => setPageIndex(currentPage + 1)}>下一页</button>
    </div></nav>
  </section>;
}

export default function AuditProjectDetail() {
  const { id = '' } = useParams();
  const { hasRole } = useAuth();
  const [launching, setLaunching] = useState(false);
  const [assigning, setAssigning] = useState(false);
  const [jobsReload, setJobsReload] = useState(0);
  const [params] = useSearchParams();
  const view = params.get('view') === 'matrix' ? 'matrix' : 'cockpit';
  const [data, setData] = useState<{ project: Project; matrix: Matrix; runs: AuditRun[]; rules: Map<string, AuditRule>; simulated: boolean } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [reload, setReload] = useState(0);
  const [selected, setSelected] = useState<AuditStage | null>(null);
  const refresh = useCallback(() => setReload(value => value + 1), []);
  useEffect(() => {
    let active = true;
    setLoading(true); setError(false); setData(previous => previous?.project.id === id ? previous : null); setSelected(null);
    (async () => {
      // Project reads reconcile jobs, so load its dependent views after that transaction.
      const { data: project } = await getAuditProject(id);
      const [{ data: matrix }, { data: runs }] = await Promise.all([getAuditProjectMatrix(id), listAuditRuns({ project_id: id })]);
      const versions = await Promise.all([...new Set(runs.map(run => run.spec_version_id))].map(versionId => getAuditSpecVersion(versionId)));
      const rules = new Map(versions.flatMap(version => version.data.rules_json.map(rule => [rule.rule_id, rule] as const)));
      if (active) setData({ project, matrix, runs, rules, simulated: false });
      const posts = runs.filter(run => run.phase === 'post');
      let simulated = project.flow.linked_posts > 0 && posts.every(run => run.source_ref_json.demo === true);
      // A real, independent check must not hide a badge on an entirely demo flow.
      if (project.flow.linked_posts > 0 && !simulated && posts.some(run => run.source_ref_json.demo === true)) {
        const realContributors = await Promise.all(posts.filter(run => run.source_ref_json.demo !== true).map(async run => {
          let page = 1;
          while (true) {
            const { data } = await listAuditTargets(run.id, { page, page_size: 200 });
            if (data.items.some(target => target.baseline_target_id)) return true;
            if (!data.items.length || page * data.page_size >= data.total) return false;
            page++;
          }
        })).catch(() => [true]);
        simulated = realContributors.every(contributes => !contributes);
      }
      if (active) setData({ project, matrix, runs, rules, simulated });
    })().catch(() => { if (active) setError(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [id, reload]);
  function selectStage(stage: AuditStage | null) {
    setSelected(stage);
    document.getElementById('project-pages')?.scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' });
  }
  const project = data?.project;
  const dominant = project?.page_count ? stageOrder.reduce((best, stage) => project.stages[stage].count >= project.stages[best].count ? stage : best, stageOrder[0]) : null;
  const demo = data?.runs.some(run => run.source_ref_json.demo === true);
  const fixed = project?.flow.counts.fixed || 0;
  const carried = project?.flow.counts.still_open || 0;
  const closure = fixed + carried ? Math.round(fixed / (fixed + carried) * 100) : null;
  return <div className={`aw ${view === 'cockpit' ? 'ap-cockpit' : ''}`}><div className="aw-heading"><nav className="aw-breadcrumb" aria-label="面包屑"><Link to="/audit-projects">项目走查</Link><span>/</span>{view === 'matrix' ? <><Link to={`/audit-projects/${id}`}>{project?.name || '项目'}</Link><span>/</span><span>规范矩阵</span></> : <span>{project?.name || '项目驾驶舱'}</span>}</nav><ProjectViews id={id} view={view} /></div>
    {error && data ? <LoadState error retry={refresh} /> : null}
    {!data ? <LoadState loading={loading} error={error} retry={() => setReload(value => value + 1)} /> : view === 'matrix' ? <AuditProjectMatrix key={id} project={data.project} matrix={data.matrix} /> : <>
      <header className="ap-project-header">
        <div className="aw-heading"><h1>{data.project.name}</h1>{hasRole('operator') && <button type="button" onClick={() => setLaunching(true)}>发起审核</button>}</div>
        <div className="aw-chips"><details className="ap-spec-versions"><summary>规范 {new Set([...data.project.stage_specs.pre, ...data.project.stage_specs.post].map(version => version.id)).size} 个版本</summary>
          <div className="ap-spec-version-list">{(['pre', 'post'] as const).map(phase => <div key={phase}><strong>{phase === 'pre' ? '上线前' : '上线后'}</strong>{data.project.stage_specs[phase].length ? data.project.stage_specs[phase].map(version => <Link key={version.id} to={`/specs/${version.spec_id}?version=${version.id}`}>{version.label}</Link>) : <span className="aw-muted">暂无规范</span>}</div>)}</div>
        </details>{dominant && <span className="aw-chip">主要阶段 · {stageLabels[dominant]}</span>}{demo && <DemoBadge source={{ demo: true }} />}</div>
        <section className="aw-kpi-band ap-project-metrics" aria-label="项目关键指标">
          <div className="aw-kpi"><span>页面数</span><strong>{data.project.page_count}</strong><small>前 {data.matrix.pages.filter(page => page.pre_target_id).length} · 后 {data.matrix.pages.filter(page => page.post_target_id).length}</small></div>
          <div className="aw-kpi"><span>审核次数</span><strong>{data.project.run_count}</strong><small>项目累计审核</small></div>
          <div className="aw-kpi aw-kpi-ring"><div><span>上线前问题闭环率</span><small>已修 {fixed} / {fixed + carried}</small></div><DashboardRing label={`上线前问题闭环率：${closure === null ? '暂无' : `${closure}%`}，已修 ${fixed}，未修 ${carried}`} value={closure === null ? '暂无' : `${closure}%`} caption="闭环率" segments={[{ count: fixed, tone: 'highlight' }, { count: carried, tone: 'remaining' }]} /></div>
          <div className="aw-kpi"><span>发布回归</span><strong className="aw-kpi-fail">{data.project.clusters.regressed.total}</strong><small>项上线后回归</small></div>
          <div className="aw-kpi"><span>证据缺口</span><strong className="aw-warning">{data.project.clusters.evidence_gaps.total}</strong><small>项待补充确认</small></div>
        </section>
      </header>
      <AuditJobsSection key={`jobs-${id}`} projectId={id} reload={jobsReload} onTerminal={refresh} />
      {data.project.run_count === 0 ? <section className="aw-panel aw-empty"><h2>项目还没有审核记录</h2><p>发起第一次审核，或将已有审核归入项目。</p>{hasRole('operator') && <div className="aw-actions aw-empty-actions"><button type="button" onClick={() => setLaunching(true)}>发起第一次审核</button><button type="button" className="aw-secondary" onClick={() => setAssigning(true)}>归入已有审核</button></div>}</section> : null}
      <LifecycleRail project={data.project} selected={selected} dominant={dominant} onSelect={selectStage} /><ProjectClusters key={`clusters-${id}`} project={data.project} matrix={data.matrix} rules={data.rules} simulated={data.simulated} /><PageCards key={`pages-${id}`} project={data.project} matrix={data.matrix} selected={selected} onClear={() => setSelected(null)} />
    </>}
    {launching && data ? <AuditLaunchDialog project={data.project} onClose={() => setLaunching(false)} onCreated={() => setJobsReload(value => value + 1)} /> : null}
    {assigning ? <AssignAuditRunsDialog projectId={id} onClose={() => setAssigning(false)} onAssigned={refresh} /> : null}
  </div>;
}
