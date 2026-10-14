export type Phase = 'pre' | 'post';
export type Round = 'initial' | 'recheck' | 'verified';
export type FindingStatus = 'issue' | 'uncertain' | 'pass';

export interface Attachment { name: string; type: string; }
export interface Finding {
  id: string;
  title: string;
  status: FindingStatus;
  observed: string;
  expected: string;
  suggestion: string;
}
export interface Report {
  id: string;
  projectId: string;
  baselineReportId: string | null;
  phase: Phase;
  round: Round;
  findings: Finding[];
  source: string;
}
export interface Message {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  attachments?: Attachment[];
  report?: Report;
  needsMaterial?: boolean;
}
export interface AuditProject {
  id: string;
  title: string;
  messages: Message[];
  approvedPreReportId: string | null;
}

const preFindings: Finding[] = [
  { id: 'OV-017', title: '主标题需要缩短', status: 'issue', observed: '示例主标题“家电焕新好物限时抢购”共 10 个字符。', expected: '该示例绑定的官方会场 v5 口径：主标题不超过 8 个字符，保留已确认例外。', suggestion: '可改为“家电焕新限时购”，修改后重新核对。' },
  { id: 'OV-005', title: '首屏没有完整露出商品', status: 'issue', observed: '示例中首屏只露出商品的一部分，主视觉占用过多高度。', expected: '未滚动首屏至少完整露出一个 feeds 商品。', suggestion: '压缩主视觉或上方模块高度，再提供未滚动首屏。' },
  { id: 'OV-009', title: 'Tab 间距还缺测量依据', status: 'uncertain', observed: '仅凭示例截图，无法确认容器边界与 CSS 像素间距。', expected: 'H5 当前口径为 7 至 9 CSS px；没有可靠 DOM 测量时保持待确认。', suggestion: '补充同页面 DOM 测量记录，不直接将截图像素当作 CSS px。' },
];
const postFindings: Finding[] = [
  { id: 'OV-010', title: '商品区背景与上线前不同', status: 'issue', observed: '演示场景假设 App 的商品区容器变为灰底，与已确认的上线前白底要求不同。', expected: '本例假设规范负责人已确认 App 沿用该会场白底要求。正式执行需保存这一确认。', suggestion: '核对线上容器样式，再提供同一对象的新截图复查。' },
  { id: 'LINK-01', title: '规则入口的跳转还需确认', status: 'uncertain', observed: '静态截图只能证明入口存在，不能证明跳转目标正确。', expected: '需要只读跳转后的落地页和返回记录。', suggestion: '补充跳转证据；手机截图本身不能证明跳转通过。' },
];

export function makeReport(projectId: string, phase: Phase, round: Round = 'initial', source = '内置演示材料', baselineReportId: string | null = null): Report {
  const findings = (phase === 'pre' ? preFindings : postFindings).map(item => {
    const passed = round === 'verified' || (round === 'recheck' && item.status === 'issue');
    return passed ? { ...item, status: 'pass' as const, observed: `${item.title}：已在本次模拟复核中补充对应证据并确认。` } : { ...item };
  });
  return { id: crypto.randomUUID(), projectId, baselineReportId, phase, round, findings, source };
}

const officialBaseline = makeReport('official', 'pre', 'verified', '已确认的上线前演示材料');
export const initialProjects: AuditProject[] = [
  { id: 'official', title: '11.11 官方会场', approvedPreReportId: officialBaseline.id, messages: [
    { id: 'official-pre-user', role: 'user', text: '帮我复核 11.11 官方会场的上线前稿件，之前的问题已经修改，测量记录也已补齐。' },
    { id: 'official-pre-result', role: 'assistant', text: '上线前的模拟复核已完成，这一轮已由审核人确认，作为本项目后续检查的依据。', report: officialBaseline },
    { id: 'official-1', role: 'user', text: '页面已上线，检查手机端效果。' },
    { id: 'official-2', role: 'assistant', text: '这轮手机走查仍归入 11.11 官方会场，并引用本项目已确认的上线前记录。以下为模拟结果。', report: makeReport('official', 'post', 'initial', '内置手机演示材料', officialBaseline.id) },
  ] },
  { id: 'home', title: '家居焕新会场', approvedPreReportId: null, messages: [
    { id: 'home-1', role: 'user', text: '帮我检查家居会场的上线前 HTML。' },
    { id: 'home-2', role: 'assistant', text: '先看需要处理的地方，规范依据可以逐项展开。以下为流程示例。', report: makeReport('home', 'pre') },
  ] },
];

export const examples = [
  { phase: 'pre' as const, title: '检查上线前的 HTML', description: '页面内容、布局与规范', icon: 'code' as const },
  { phase: 'post' as const, title: '检查上线后的手机页面', description: '实际效果与上线前要求', icon: 'phone' as const },
];
