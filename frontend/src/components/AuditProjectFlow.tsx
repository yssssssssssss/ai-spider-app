import { AuditFlowEdge, AuditProjectDetail } from '../api';
import { categoryColors, categoryLabels } from './AuditProjectUI';

const origins = ['fail', 'pass', 'uncertain', 'uncovered'] as const;
const originLabels = { fail: '不符合', pass: '符合', uncertain: '待确认', uncovered: '未覆盖' };
const originColors = { fail: '#FF6A3D', pass: '#34D399', uncertain: '#F2C14E', uncovered: '#4A5262' };
const categoryOrder: AuditFlowEdge['to'][] = ['fixed', 'still_open', 'regressed', 'kept', 'needs_confirmation', 'new_issue'];

// Both columns share a scale. Each node reserves label space even at zero;
// each edge consumes exactly count * scale from both of its node offsets.
export function layoutAuditFlow(edges: AuditFlowEdge[], height = 330) {
  const total = edges.reduce((sum, edge) => sum + edge.count, 0);
  const gap = 26;
  const scale = total ? Math.max(0, height - categoryOrder.length * gap) / total : 0;
  function column<T extends string>(keys: readonly T[], side: 'from' | 'to') {
    let cursor = (height - (total * scale + keys.length * gap)) / 2;
    return keys.map(id => {
      const count = edges.reduce((sum, edge) => sum + (edge[side] === id ? edge.count : 0), 0);
      const node = { id, count, y: cursor + gap / 2, height: count * scale };
      cursor += node.height + gap;
      return node;
    });
  }
  const left = column(origins, 'from');
  const sourceCenters = new Map(left.map(node => [node.id, node.y + node.height / 2]));
  const barycenters = new Map(categoryOrder.map(category => {
    const incoming = edges.filter(edge => edge.to === category);
    const count = incoming.reduce((sum, edge) => sum + edge.count, 0);
    const weightedCenter = incoming.reduce((sum, edge) => sum + sourceCenters.get(edge.from)! * edge.count, 0);
    return [category, count ? weightedCenter / count : Infinity];
  }));
  const orderedCategories = [...categoryOrder].sort((a, b) => {
    const first = barycenters.get(a)!;
    const second = barycenters.get(b)!;
    // Equal weighted centers can differ slightly through floating-point division.
    const tied = first === second || Math.abs(first - second) < 1e-9;
    return tied ? categoryOrder.indexOf(a) - categoryOrder.indexOf(b) : first - second;
  });
  const right = column(orderedCategories, 'to');
  const leftPositions = new Map(left.map((node, index) => [node.id, index]));
  const rightPositions = new Map(right.map((node, index) => [node.id, index]));
  const leftOffsets = new Map(left.map(node => [node.id, node.y]));
  const rightOffsets = new Map(right.map(node => [node.id, node.y]));
  const active = edges.filter(edge => edge.count > 0);
  const leftStarts = new Map<AuditFlowEdge, number>();
  const rightStarts = new Map<AuditFlowEdge, number>();
  // A source stacks destinations top to bottom; a destination stacks sources
  // top to bottom. Input edge order must not introduce crossings at either end.
  for (const edge of [...active].sort((a, b) => rightPositions.get(a.to)! - rightPositions.get(b.to)!)) {
    leftStarts.set(edge, leftOffsets.get(edge.from)!);
    leftOffsets.set(edge.from, leftOffsets.get(edge.from)! + edge.count * scale);
  }
  for (const edge of [...active].sort((a, b) => leftPositions.get(a.from)! - leftPositions.get(b.from)!)) {
    rightStarts.set(edge, rightOffsets.get(edge.to)!);
    rightOffsets.set(edge.to, rightOffsets.get(edge.to)! + edge.count * scale);
  }
  const bands = active.map(edge => {
    const y1 = leftStarts.get(edge)!;
    const y2 = rightStarts.get(edge)!;
    const bandHeight = edge.count * scale;
    return { ...edge, path: `M100,${y1} C330,${y1} 330,${y2} 560,${y2} L560,${y2 + bandHeight} C330,${y2 + bandHeight} 330,${y1 + bandHeight} 100,${y1 + bandHeight} Z` };
  });
  return { left, right, bands, total };
}

export default function AuditProjectFlow({ flow }: { flow: AuditProjectDetail['flow'] }) {
  const layout = layoutAuditFlow(flow.edges);
  const aria = `规则流向，上线前到上线后，共 ${layout.total} 条。左侧：${layout.left.map(node => `${originLabels[node.id]} ${node.count}`).join('，')}。右侧：${layout.right.map(node => `${categoryLabels[node.id]} ${node.count}`).join('，')}。流向：${flow.edges.map(edge => `${originLabels[edge.from]}到${categoryLabels[edge.to]} ${edge.count}`).join('，') || '暂无可比对规则'}。另有 ${flow.not_comparable} 条无法比对。`;
  return <section className="aw-panel ap-flow" aria-labelledby="flow-title"><div><h2 id="flow-title">规则流向 · 上线前 → 上线后</h2><p>{flow.linked_posts} 次已关联基线的巡检 · {layout.total} 条可比对规则</p></div>
    <div className="aw-scroll" tabIndex={0} role="region" aria-label="规则流向图，可横向滚动"><svg viewBox="0 0 680 350" role="img" aria-label={aria}>
      <g fillOpacity=".42">{layout.bands.map(edge => <path key={`${edge.from}-${edge.to}`} d={edge.path} fill={categoryColors[edge.to]}><title>{originLabels[edge.from]} → {categoryLabels[edge.to]} {edge.count}</title></path>)}</g>
      {layout.left.map(node => <g key={node.id}>{node.height > 0 && <rect x="92" y={node.y} width="8" height={node.height} rx="2" fill={originColors[node.id]} />}<text x="84" y={node.y + node.height / 2} dominantBaseline="middle" textAnchor="end">{originLabels[node.id]} {node.count}</text></g>)}
      {layout.right.map(node => <g key={node.id}>{node.height > 0 && <rect x="560" y={node.y} width="8" height={node.height} rx="2" fill={categoryColors[node.id]} />}<text x="578" y={node.y + node.height / 2} dominantBaseline="middle">{categoryLabels[node.id]} {node.count}</text></g>)}
    </svg></div><p className="aw-muted">另有 {flow.not_comparable} 条无法比对，未计入流向；未启用、不适用或规范范围变化的规则以实际比对结果为准。</p>
  </section>;
}
