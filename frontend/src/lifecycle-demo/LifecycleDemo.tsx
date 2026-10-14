import { useEffect, useRef, useState, type ClipboardEvent, type FormEvent, type ReactNode } from 'react';
import { examples, initialProjects, makeReport, type Attachment, type AuditProject, type Message, type Phase, type Report, type Round } from './data';
import s from './LifecycleDemo.module.css';

type IconName = 'panel' | 'edit' | 'search' | 'plus' | 'arrow' | 'close' | 'code' | 'phone' | 'check' | 'chevron' | 'file' | 'download' | 'stop' | 'help';
const paths: Record<IconName, ReactNode> = {
  panel: <><rect x="3" y="4" width="18" height="16" rx="3" /><path d="M9 4v16" /></>,
  edit: <><path d="M12 4H5a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h13a2 2 0 0 0 2-2v-7" /><path d="m15 3 4 4M10 16l4-1 8-8-4-4-8 8-1 5Z" /></>,
  search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>,
  plus: <path d="M12 5v14M5 12h14" />,
  arrow: <path d="M12 20V4m-6 6 6-6 6 6" />,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  code: <path d="m7 6-5 6 5 6m10-12 5 6-5 6m-4-15-2 18" />,
  phone: <><rect x="6" y="2" width="12" height="20" rx="3" /><path d="M10 5h4m-3 14h2" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  chevron: <path d="m6 9 6 6 6-6" />,
  file: <><path d="M14 2H5v20h14V7l-5-5Zm0 0v5h5M8 12h8m-8 4h6" /></>,
  download: <><path d="M12 3v12m-4-4 4 4 4-4M4 17v4h16v-4" /></>,
  stop: <rect x="6" y="6" width="12" height="12" rx="1" />,
  help: <><circle cx="12" cy="12" r="9" /><path d="M9 8a3 3 0 0 1 6 1c0 2-3 2-3 4m0 3v1" /></>,
};
function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}
function Mark({ small = false }: { small?: boolean }) {
  return <span className={small ? s.smallMark : s.mark} aria-hidden="true"><span /><span /><span /></span>;
}
function id() { return crypto.randomUUID(); }
function inferPhase(text: string, previous: Phase = 'pre'): Phase {
  if (/手机|上线后|已上线|app|真机/i.test(text)) return 'post';
  if (/html|上线前|预览/i.test(text)) return 'pre';
  return previous;
}

function AuditResult({ report, confirmed, current, busy, onContinue, onConfirm, onDownload, onBaseline }: {
  report: Report; confirmed: boolean; current: boolean; busy: boolean; onBaseline: () => void; onContinue: (phase: Phase, round: Round) => void; onConfirm: () => void; onDownload: () => void;
}) {
  const issues = report.findings.filter(item => item.status === 'issue').length;
  const uncertain = report.findings.filter(item => item.status === 'uncertain').length;
  const clear = issues === 0 && uncertain === 0;
  return <section className={s.result} aria-label="审核结果" id={`report-${report.id}`}>
    <div className={s.resultMeta}><span>{report.phase === 'pre' ? '上线前 · HTML' : '上线后 · 手机端'}</span><span>演示结果</span></div>
    {report.phase === 'post' ? <div className={s.baselineLink}>{report.baselineReportId ? <button onClick={onBaseline}><Icon name="check" size={13} />已关联本项目上线前记录<span>查看依据 ↗</span></button> : <span>本项目尚无已确认的上线前记录，本轮为独立检查。</span>}</div> : null}
    <h2>{clear ? '本轮检查已完成复核' : issues ? `有 ${issues} 处需要调整` : '修改项已修正，还差一项确认'}</h2>
    <p className={s.resultIntro}>{clear ? '本次模拟复核中的问题与证据缺口均已处理，原来的发现仍保留在上方。' : issues ? `${uncertain} 项还需要补充依据。先处理下面这些地方。` : '证据补齐前，这一项会保持待确认。'}</p>
    <div className={s.findings}>{report.findings.map((finding, index) => <details className={s.finding} key={finding.id}>
      <summary><span className={s.findingIndex} data-status={finding.status}>{finding.status === 'pass' ? <Icon name="check" size={15} /> : index + 1}</span><span className={s.findingName}>{finding.title}</span><span className={s.findingLabel} data-status={finding.status}>{finding.status === 'issue' ? '需修改' : finding.status === 'uncertain' ? '待确认' : '已复核'}</span><Icon name="chevron" size={14} /></summary>
      <div className={s.findingDetail}><p><strong>发现</strong>{finding.observed}</p><p><strong>依据</strong>{finding.expected}</p><p><strong>建议</strong>{finding.suggestion}</p><small>{finding.id} · {report.source} · 不代表真实采集或模型判定</small></div>
    </details>)}</div>
    {current ? <div className={s.resultActions}>
      {!clear ? <button className={s.action} disabled={busy} onClick={() => onContinue(report.phase, report.round === 'initial' ? 'recheck' : 'verified')}>{report.round === 'initial' ? '复查修改稿' : '补充证据复核'}<Icon name="plus" size={15} /></button> : report.phase === 'pre' && !confirmed ? <button className={s.action} disabled={busy} onClick={onConfirm}><Icon name="check" size={16} />确认本轮审核</button> : null}
      {report.phase === 'pre' ? <button className={s.action} disabled={busy} onClick={() => onContinue('post', 'initial')}><Icon name="phone" size={16} />检查上线效果</button> : null}
      <button className={s.lightAction} onClick={onDownload} aria-label="下载这次审核记录"><Icon name="download" size={16} />下载记录</button>
    </div> : null}
    <p className={s.resultFootnote}>{clear && confirmed && report.phase === 'pre' ? '已记录模拟确认。上线后继续在这里发手机截图即可。' : '按钮用于演示下一步，正式复查需要提供新的稿件或证据。'}</p>
  </section>;
}

export default function LifecycleDemo() {
  const [projects, setProjects] = useState<AuditProject[]>(initialProjects);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 760);
  const [searching, setSearching] = useState(false);
  const [search, setSearch] = useState('');
  const [help, setHelp] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState('');
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const fileInput = useRef<HTMLInputElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const scrollArea = useRef<HTMLDivElement>(null);
  const active = projects.find(item => item.id === activeId);
  const messages = active?.messages ?? [];
  const latestReportId = [...messages].reverse().find(message => message.report)?.report?.id;
  const visibleProjects = projects.filter(item => item.title.toLowerCase().includes(search.toLowerCase()));

  useEffect(() => () => clearTimeout(timer.current), []);
  useEffect(() => {
    const area = scrollArea.current;
    if (area) area.scrollTop = area.scrollHeight;
  }, [activeId, messages.length, working]);
  useEffect(() => {
    const input = textarea.current;
    if (input) { input.style.height = 'auto'; input.style.height = `${Math.min(input.scrollHeight, 160)}px`; }
  }, [draft]);
  useEffect(() => {
    function close(event: KeyboardEvent) {
      if (event.key === 'Escape') { setHelp(false); if (window.innerWidth <= 760) setSidebarOpen(false); }
    }
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, []);

  function append(target: string, message: Message) {
    setProjects(old => old.map(item => item.id === target ? { ...item, messages: [...item.messages, message] } : item));
  }
  function ensureProject(text: string, suggestedTitle?: string) {
    if (activeId) return activeId;
    const newId = id();
    const rawTitle = text.replace(/https?:\/\/\S+/g, '').trim();
    const title = suggestedTitle || (rawTitle ? Array.from(rawTitle).slice(0, 20).join('') : '新项目走查');
    setProjects(old => [{ id: newId, title, messages: [], approvedPreReportId: null }, ...old]);
    setActiveId(newId);
    return newId;
  }
  function cancelWork() {
    clearTimeout(timer.current); setWorking(false);
    if (activeId) append(activeId, { id: id(), role: 'assistant', text: '已停止演示。你可以补充材料后继续。' });
  }
  function newReview() {
    if (working) cancelWork();
    clearTimeout(timer.current); setWorking(false); setActiveId(null); setDraft(''); setAttachments([]); setError(''); setHelp(false);
    if (window.innerWidth <= 760) setSidebarOpen(false);
    textarea.current?.focus();
  }
  function runExample(phase: Phase, round: Round = 'initial') {
    if (working) return;
    const projectTitle = active?.title ?? (phase === 'pre' ? '家电会场' : '数码会场');
    const text = round === 'initial' ? phase === 'pre' ? `帮我审核${projectTitle}上线前的 HTML，使用示例材料。` : `${projectTitle}已上线，帮我检查手机端效果，使用示例材料。` : round === 'recheck' ? '我已修改稿件，帮我复查。使用修改后的演示材料。' : '已补充测量与验证记录，继续复核。使用演示证据。';
    const target = ensureProject(text, projectTitle);
    append(target, { id: id(), role: 'user', text });
    setDraft(''); setAttachments([]); setError(''); setWorking(true);
    timer.current = setTimeout(() => {
      append(target, { id: id(), role: 'assistant', text: phase === 'post' && active?.approvedPreReportId ? '沿用这个项目上线前已确认的要求，继续看手机端效果。以下是模拟结果。' : round === 'initial' ? '先看需要调整的地方，点击问题可查看依据。以下为模拟结果。' : '这次只复查之前发现的问题，原始记录会继续保留。以下是模拟结果。', report: makeReport(target, phase, round, '内置演示材料', phase === 'post' ? active?.approvedPreReportId ?? null : null) });
      setWorking(false);
    }, 1000);
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (working || (!draft.trim() && !attachments.length)) return;
    const text = draft.trim() || '请审核这些材料。';
    const previousPhase = [...messages].reverse().find(message => message.report)?.report?.phase;
    const phase = inferPhase(text, previousPhase);
    const hasMaterial = /https?:\/\/\S+/i.test(text) || attachments.length > 0;
    const target = ensureProject(text);
    append(target, { id: id(), role: 'user', text, attachments });
    setDraft(''); setAttachments([]); setError('');
    if (!hasMaterial) {
      append(target, { id: id(), role: 'assistant', text: phase === 'post' ? '把手机截图发来，或说明要检查的 App 页面。如果是同一个项目，继续在这里补充就好。也可以先体验一个示例。' : '把页面链接、HTML 文件或截图发来即可。如果有指定规范，可以一起说明。也可以先体验一个示例。', needsMaterial: true });
      return;
    }
    setWorking(true);
    timer.current = setTimeout(() => {
      append(target, { id: id(), role: 'assistant', text: '材料已在本地接收。本 Demo 没有读取链接或分析文件，下面展示审核结果的呈现方式，与你提供的实际内容无关。', report: makeReport(target, phase, 'initial', '演示结果，未分析所传材料', phase === 'post' ? active?.approvedPreReportId ?? null : null) });
      setWorking(false);
    }, 1000);
  }
  function addFiles(files: FileList | File[]) {
    const accepted = Array.from(files).filter(file => /\.(html?|png|jpe?g|webp|pdf)$/i.test(file.name));
    if (accepted.length !== files.length) setError('支持 HTML、PNG、JPG、WebP 和 PDF 文件。'); else setError('');
    setAttachments(old => [...old, ...accepted.map(file => ({ name: file.name, type: file.type }))]);
  }
  function pasteFiles(event: ClipboardEvent<HTMLTextAreaElement>) {
    if (event.clipboardData.files.length) { event.preventDefault(); addFiles(event.clipboardData.files); }
  }
  function confirmReview(reportId: string) {
    const report = active?.messages.find(message => message.report?.id === reportId)?.report;
    if (!activeId || !report || report.phase !== 'pre' || report.findings.some(item => item.status !== 'pass')) return;
    setProjects(old => old.map(item => item.id === activeId ? { ...item, approvedPreReportId: reportId } : item));
    append(activeId, { id: id(), role: 'assistant', text: '已记录本轮上线前审核确认（演示）。上线后在这里发手机截图，继续检查同一项目。' });
  }
  function download(report: Report) {
    const blob = new Blob([JSON.stringify({ demo: true, projectId: active?.id, title: active?.title, approvedPreReportId: active?.approvedPreReportId, report, messages: active?.messages }, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href = url; link.download = '审核记录-demo.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <div className={s.app}>
    <a href="#main-content" className={s.skip}>跳到审核内容</a>
    {sidebarOpen && <><button className={s.mobileBackdrop} aria-label="关闭项目列表" onClick={() => setSidebarOpen(false)} /><aside className={s.sidebar} aria-label="项目走查">
      <div className={s.sidebarTop}><button className={s.brand} onClick={newReview}><Mark small /><span>全程</span></button><button className={s.iconButton} aria-label="收起侧栏" onClick={() => setSidebarOpen(false)}><Icon name="panel" size={19} /></button></div>
      <nav className={s.sidebarActions} aria-label="审核操作"><button onClick={newReview}><Icon name="edit" size={18} />新建项目走查</button><button onClick={() => setSearching(value => !value)} aria-expanded={searching}><Icon name="search" size={18} />搜索项目</button></nav>
      {searching ? <input className={s.historySearch} aria-label="搜索项目" placeholder="搜索项目名称" value={search} onChange={event => setSearch(event.target.value)} autoFocus /> : null}
      <div className={s.history}><p>我的项目</p>{visibleProjects.map(project => <button className={activeId === project.id ? s.historyActive : ''} key={project.id} title={project.title} disabled={working} onClick={() => { setActiveId(project.id); setDraft(''); setAttachments([]); setError(''); setHelp(false); if (window.innerWidth <= 760) setSidebarOpen(false); }}>{project.title}</button>)}{!visibleProjects.length ? <span className={s.historyEmpty}>没有匹配的项目</span> : null}</div>
      <div className={s.sidebarBottom}><button onClick={() => { setHelp(value => !value); if (window.innerWidth <= 760) setSidebarOpen(false); }}><Icon name="help" size={18} />如何使用</button><a href="/">返回现有平台<span>↗</span></a><div className={s.profile}><span className={s.avatar}>林</span><div>林知夏<small>审核工作空间 · 演示</small></div></div></div>
    </aside></>}
    <main className={`${s.main} ${!active ? s.home : ''}`} id="main-content">
      <header className={s.header}><div>{!sidebarOpen ? <button className={s.iconButton} aria-label="展开侧栏" onClick={() => setSidebarOpen(true)}><Icon name="panel" /></button> : null}<button className={s.headerTitle} onClick={newReview}>全程<span>审核助手</span></button>{active ? <span className={s.currentProject}>{active.title}</span> : null}</div><span className={s.demoBadge}>交互 Demo</span></header>
      {help ? <div className={s.help}><button className={s.helpClose} aria-label="关闭使用说明" onClick={() => setHelp(false)}><Icon name="close" size={18} /></button><h2>像发消息一样，完成一次审核</h2><p>1. 发来链接、HTML 或手机截图。</p><p>2. 先看结论，需要时再展开依据。</p><p>3. 修改后继续发来复查，上线后接着检查。</p><small>默认沿用项目已绑定的规范。身份、规则或证据不明确时，先补充确认。当前为本地交互演示，刷新后重置。</small></div> : null}
      <div className={s.scrollArea} ref={scrollArea}>
        {!active ? <div className={s.welcome}><div className={s.welcomeHeading}><Mark /><h1>今天，要审核什么？</h1><p>发来项目材料，从上线前一直查到上线后。</p></div></div> : <div className={s.conversation} aria-label="审核会话"><div className={s.conversationName}>本项目的走查会持续记录在这里</div>{messages.map(message => <article className={message.role === 'user' ? s.userMessage : s.assistantMessage} key={message.id} aria-label={message.role === 'user' ? '你的消息' : '审核助手'}>
          {message.role === 'user' ? <div className={s.userBubble}><p>{message.text}</p>{message.attachments?.map((file, index) => <span className={s.messageFile} key={`${file.name}-${index}`}><Icon name="file" size={16} />{file.name}</span>)}</div> : <><div className={s.assistantIdentity}><Mark small /><span>全程</span></div><p className={s.assistantText}>{message.text}</p>{message.needsMaterial ? <div className={s.materialExamples}><button onClick={() => runExample('pre')} disabled={working}><Icon name="code" size={16} />使用 HTML 示例</button><button onClick={() => runExample('post')} disabled={working}><Icon name="phone" size={16} />使用手机示例</button></div> : null}{message.report ? <AuditResult report={message.report} confirmed={active.approvedPreReportId === message.report.id} current={latestReportId === message.report.id} busy={working} onBaseline={() => document.getElementById(`report-${message.report!.baselineReportId}`)?.scrollIntoView({ block: 'start' })} onContinue={runExample} onConfirm={() => confirmReview(message.report!.id)} onDownload={() => download(message.report!)} /> : null}</>}
        </article>)}{working ? <div className={s.working} role="status"><Mark small /><span>正在演示审核流程<span className={s.pulse}>...</span></span></div> : null}</div>}
      </div>
      <div className={`${s.composerArea} ${!active ? s.homeComposer : ''}`}>
        <form className={s.composer} onSubmit={submit} onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); addFiles(event.dataTransfer.files); }}>
          {attachments.length ? <div className={s.attachments}>{attachments.map((file, index) => <span className={s.fileChip} key={`${file.name}-${index}`}><Icon name="file" size={16} /><span>{file.name}</span><button type="button" aria-label={`移除 ${file.name}`} onClick={() => setAttachments(old => old.filter((_, i) => i !== index))}><Icon name="close" size={14} /></button></span>)}</div> : null}
          <textarea ref={textarea} aria-label="审核消息" value={draft} placeholder={active ? '补充材料，或继续问我' : '粘贴链接、上传稿件，或描述你想检查的内容'} rows={2} onPaste={pasteFiles} onChange={event => setDraft(event.target.value)} onKeyDown={event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} />
          <div className={s.composerToolbar}><div><button className={s.attachButton} type="button" aria-label="添加审核材料" title="添加 HTML、截图或规范 PDF" onClick={() => fileInput.current?.click()}><Icon name="plus" size={23} /></button><span>HTML · 截图 · 规范</span></div>{working ? <button type="button" className={s.send} aria-label="停止演示" onClick={cancelWork}><Icon name="stop" size={17} /></button> : <button type="submit" className={s.send} disabled={!draft.trim() && !attachments.length} aria-label="发送审核消息"><Icon name="arrow" size={21} /></button>}</div>
          <input ref={fileInput} type="file" accept=".html,.htm,.png,.jpg,.jpeg,.webp,.pdf" multiple hidden onChange={event => { if (event.target.files) addFiles(event.target.files); event.target.value = ''; }} />
        </form>
        {error ? <p className={s.error} role="alert">{error}</p> : null}
        {!active ? <div className={s.examples}>{examples.map(example => <button key={example.phase} onClick={() => runExample(example.phase)}><Icon name={example.icon} size={19} /><span>{example.title}<small>{example.description}</small></span><span className={s.exampleArrow}>↗</span></button>)}</div> : null}
        <p className={s.disclaimer}>交互演示，不发送文件或执行真实审核。{!active ? ' 可点击示例体验。' : ' 重要结论需结合证据确认。'}</p>
      </div>
    </main>
  </div>;
}
