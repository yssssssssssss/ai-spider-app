import { useEffect, useState } from 'react';
import { createRequest, listAnalysisSkills, parseLongImageIntent } from '../api';

const knownApps = ['淘宝', '天猫', '拼多多', '京东'];
const productDetailMarkers = ['商详', '商品详情', '商品页'];
const longImageMarkers = [...productDetailMarkers, '长图', '长截图', '拼长图', '滚动截图', '全页截图', '整页截图', '多屏', '多页'];
const countedCapturePattern = /(?:截取|截屏|截图|滚动|采集)?\s*\d{1,2}\s*(?:屏|页|张)/;

type LongImageIntent = {
  intent: string;
  confidence: number;
  scene_type: string;
  apps?: string[];
  keyword?: string;
  capture_count?: number;
};

type ScrollPromoConfig = {
  target_app: '京东';
  target_tab: string;
  page_wait_seconds: number;
  static_frame_count: number;
  static_scroll_distance_px: number;
  static_confidence_threshold: number;
  dynamic_swipe_duration_seconds: number;
  motion_window_offset_seconds: number;
  motion_window_duration_seconds: number;
  fps: number;
  max_frames: number;
  collapse_width_ratio: number;
};

const defaultScrollPromoConfig: ScrollPromoConfig = {
  target_app: '京东',
  target_tab: '新品',
  page_wait_seconds: 5,
  static_frame_count: 3,
  static_scroll_distance_px: 600,
  static_confidence_threshold: 0.75,
  dynamic_swipe_duration_seconds: 2,
  motion_window_offset_seconds: 0.5,
  motion_window_duration_seconds: 1,
  fps: 10,
  max_frames: 6,
  collapse_width_ratio: 2 / 3,
};

const scrollPromoPreset = `打开京东 App，点击“新品”Tab并等待页面加载；如果画面中间出现弹窗则关闭。

静态检测：截取 3 张静态帧，相邻帧之间上滑 600px；逐张判断右下角促销贴片及其正下方关闭按钮。

动态检测：执行 2 秒上滑，从真实运动开始后 0.5 秒起截取 1 秒，按 10 FPS 得到 10 张候选帧，最多分析 6 张。

判断规则：静态帧置信度达到 75% 才计入汇总；使用有效静态帧最大贴片宽度作为基准，过程帧宽度小于基准的 2/3 时判定为收起态。

输出静态帧、过程帧、红框图和独立报告，不执行设计/运营分析 Skill，不自动点击关闭按钮。`;

const jdNewFloorAuditPreset = `打开京东 App，点击顶部导航“新品”，等待 5 秒并关闭中央遮挡弹窗。

第一部分“腰部楼层巡查”：页面保持不动，截取一张原始全屏截图。以原图左上角为原点，将全宽且 y=510~1090 的水平带标为 X 区域；将 (0,510)、(540,510)、(0,1090)、(540,1090) 围成的矩形标为 Y 区域。

检查 X 区域上下是否分别为导航栏和 Tab 栏，并判断楼层属于“组合型楼层”还是“一行一爆品”。检查 Y 区域的封面图、底部渐变蒙层、首焦栏目标题、底部信息容器、小标题及 icon、利益点及箭头/按钮/图片。

步骤 4 检查 X 区域是否符合“封面图+首焦栏目标题”，并检查 X 区域下方是否紧接“一行 4 个商品”楼层：两项都为真时格式错误，条件 1 为真且条件 2 为假时格式正确，条件 1 为假时格式错误。步骤 5 至 7 均以 X 区域为识别对象，继续按原规则检查右侧双入口、三入口的标签/商品/价格/CTA，以及“超级明星福利”的模块、换一换按钮和栏目纯净度。

第二部分“二级tab组件巡查”：点击“新奇集市”按钮并等待 8 秒；识别文本为“推荐”且文字呈红色的横向 Tab 行，将该行的全宽区域动态定义为 z1；手指向上滑动 800px 使页面向下滚动后，将全宽 y=450~525 定义为 z2；再用手指向下滑动 400px 使页面向上回退，将全宽 y=450~525 定义为 z3。

检查 z1 中红色文本选中态与灰色文本非选中态的组数，并输出选中态、非选中态和背景的 HEX 色值；分别从整体视觉判断它们是否与目标色 #FF0F23、#3D414D、#F2F3F5 一致。第二个 Tab 按钮作为独立特殊态，不计入选中/非选中数量；单独检查其文字色是否与目标色 #E63FAF 视觉一致。

z2 与 z1 内容一致时显示“正确”，不一致时显示“错误”；z3 与 z1 内容一致时显示“错误”，不一致时显示“正确”。检查 z1、z2 是否始终保持单行，是否均只有一个选中态且选中内容一致。

分别在 z1、z2 中左滑 400px，保存横滑前后整屏截图；仅当区域内内容发生变化且区域外主要内容不变时判定可横向滑动。所有检查项均展示带区域框的证据裁图；同一原图允许被多个检查项复用。

一次手机操作完成全部采集，统一生成包含上述两部分的报告。`;

function isLongImageCandidate(text: string) {
  return longImageMarkers.some(marker => text.includes(marker)) || countedCapturePattern.test(text);
}

function splitKeywords(value: string) {
  return value.split(/[,，、]/).map(keyword => keyword.trim()).filter(Boolean);
}

function clampCaptureCount(value: number) {
  return Math.min(30, Math.max(1, value || 10));
}

function extractCaptureCount(text: string) {
  const match = text.match(/(\d{1,2})\s*(?:屏|页|张)/);
  return clampCaptureCount(match ? Number(match[1]) : 10);
}

function inferApp(text: string) {
  return knownApps.find(app => text.includes(app)) || '';
}

function inferApps(text: string) {
  return knownApps.filter(app => text.includes(app)).join('、');
}

function extractSearchKeyword(text: string) {
  const quoted = text.match(/搜索[“"'‘]([^”"'’，。,\n]+)[”"'’]/);
  if (quoted) return quoted[1].trim();
  const plain = text.match(/搜索\s*([^，。,\n]+?)(?:，|。|,|\n|然后|点击|进入|针对|并|$)/);
  return plain ? plain[1].trim() : '';
}

function inferScenario(text: string) {
  if (productDetailMarkers.some(marker => text.includes(marker))) return '商品详情页';
  if (text.includes('搜索') || text.includes('结果页')) return '搜索结果页';
  if (text.includes('弹窗') || text.includes('浮层')) return '弹窗';
  return '自然语言需求';
}

function buildPlainRequest(text: string) {
  const keyword = extractSearchKeyword(text);
  return {
    target_app: inferApps(text) || inferApp(text),
    target_scenario: inferScenario(text),
    keywords: keyword ? [keyword] : [],
    description: text,
  };
}

export default function RequestForm() {
  const [naturalInput, setNaturalInput] = useState('');
  const [targetApp, setTargetApp] = useState('');
  const [targetScenario, setTargetScenario] = useState('');
  const [keywords, setKeywords] = useState('');
  const [captureCount, setCaptureCount] = useState(10);
  const [excludeLive, setExcludeLive] = useState(true);
  const [excludeAds, setExcludeAds] = useState(true);
  const [excludeService, setExcludeService] = useState(true);
  const [result, setResult] = useState<any>(null);
  const [parsedIntent, setParsedIntent] = useState<LongImageIntent | null>(null);
  const [parsingIntent, setParsingIntent] = useState(false);
  const [loading, setLoading] = useState(false);
  const [scrollPromoMode, setScrollPromoMode] = useState(false);
  const [floorAuditMode, setFloorAuditMode] = useState(false);
  const [scrollPromoConfig, setScrollPromoConfig] = useState<ScrollPromoConfig>(defaultScrollPromoConfig);
  const [templateFeedback, setTemplateFeedback] = useState('');
  const [availableSkills, setAvailableSkills] = useState<any[]>([]);
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);

  const inputText = naturalInput.trim();
  const localLongImageCandidate = isLongImageCandidate(inputText);
  const backendLongImageDetected = Boolean(
    parsedIntent && (parsedIntent.intent === 'long_image_capture' || parsedIntent.scene_type === 'product_detail')
  );
  const longImageDetected = Boolean(
    localLongImageCandidate || backendLongImageDetected
  );
  const isProductDetailLongImage = longImageDetected && (
    parsedIntent?.scene_type === 'product_detail' || productDetailMarkers.some(marker => inputText.includes(marker))
  );
  const excludedEntries = [
    excludeLive ? '直播' : '',
    excludeAds ? '广告' : '',
    excludeService ? '客服' : '',
  ].filter(Boolean);

  useEffect(() => {
    listAnalysisSkills({ profile: 'default' }).then(({ data }) => {
      setAvailableSkills(data.filter((s: any) => s.status === 'active'));
    }).catch(() => setAvailableSkills([]));
  }, []);

  useEffect(() => {
    setParsedIntent(null);

    if (!inputText || !localLongImageCandidate) {
      setParsingIntent(false);
      return;
    }

    setTargetApp(inferApps(inputText) || inferApp(inputText));
    setTargetScenario(inferScenario(inputText));
    setKeywords(extractSearchKeyword(inputText));
    setCaptureCount(extractCaptureCount(inputText));

    let cancelled = false;
    const timer = window.setTimeout(async () => {
      setParsingIntent(true);
      try {
        const { data } = await parseLongImageIntent({ text: inputText });
        if (cancelled) return;
        setParsedIntent(data);

        if (data.intent === 'long_image_capture' || data.scene_type === 'product_detail') {
          setTargetApp(data.apps?.length ? data.apps.join('、') : (inferApps(inputText) || inferApp(inputText)));
          setTargetScenario(data.scene_type === 'product_detail' ? '商品详情页' : inferScenario(inputText));
          setKeywords(data.keyword || extractSearchKeyword(inputText));
          setCaptureCount(clampCaptureCount(data.capture_count || 10));
        }
      } catch {
        return;
      } finally {
        if (!cancelled) setParsingIntent(false);
      }
    }, 600);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [inputText, localLongImageCandidate]);

  const resetForm = () => {
    setNaturalInput('');
    setTargetApp('');
    setTargetScenario('');
    setKeywords('');
    setCaptureCount(10);
    setExcludeLive(true);
    setExcludeAds(true);
    setExcludeService(true);
    setParsedIntent(null);
    setSelectedSkillIds([]);
    setScrollPromoMode(false);
    setFloorAuditMode(false);
    setScrollPromoConfig(defaultScrollPromoConfig);
    setTemplateFeedback('');
  };

  const handleCreateScrollPromo = () => {
    setScrollPromoMode(true);
    setFloorAuditMode(false);
    setScrollPromoConfig(defaultScrollPromoConfig);
    setNaturalInput(scrollPromoPreset);
    setTargetApp('京东');
    setTargetScenario('新品Tab滑动过程右下角促销贴片');
    setKeywords('新品, 促销贴片');
    setSelectedSkillIds([]);
    setTemplateFeedback('滑动贴片模板已载入，请检查说明和执行参数后提交。');
    window.requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('textarea[name="naturalInput"]')?.focus());
  };

  const handleCreateFloorAudit = () => {
    setFloorAuditMode(true);
    setScrollPromoMode(false);
    setNaturalInput(jdNewFloorAuditPreset);
    setTargetApp('京东');
    setTargetScenario('新品楼层规范检查');
    setKeywords('新品, 楼层规范');
    setSelectedSkillIds([]);
    setTemplateFeedback('新品楼层检查模板已载入，请核对说明后提交。');
    window.requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('textarea[name="naturalInput"]')?.focus());
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputText) return;

    setLoading(true);
    try {
      const payload = floorAuditMode
        ? {
          target_app: '京东',
          target_scenario: '新品楼层规范检查',
          keywords: ['新品', '楼层规范'],
          description: inputText,
          analysis_skill_ids: [],
        }
        : scrollPromoMode
        ? {
          target_app: scrollPromoConfig.target_app,
          target_scenario: `${scrollPromoConfig.target_tab}Tab滑动过程右下角促销贴片`,
          keywords: ['新品', '促销贴片'],
          description: inputText,
          analysis_skill_ids: [],
          scroll_promo_config_json: scrollPromoConfig,
        }
        : longImageDetected
        ? {
          target_app: targetApp.trim() || inferApps(inputText) || inferApp(inputText),
          target_scenario: `${isProductDetailLongImage ? '商品详情页' : (targetScenario.trim() || inferScenario(inputText))}滚动${captureCount}屏并拼接长图`,
          keywords: splitKeywords(keywords || parsedIntent?.keyword || extractSearchKeyword(inputText)),
          description: [
            inputText,
            `长图采集：截图屏数${captureCount}；${isProductDetailLongImage ? `选择规则：第一个普通商品；排除入口：${excludedEntries.join('、') || '无'}；` : ''}自动裁切重复区域并生成长图，保留原始截图。`,
          ].join('\n'),
          analysis_skill_ids: selectedSkillIds.length > 0 ? selectedSkillIds : undefined,
        }
        : { ...buildPlainRequest(inputText), analysis_skill_ids: selectedSkillIds.length > 0 ? selectedSkillIds : undefined };

      const { data } = await createRequest(payload);
      setResult(data);
      resetForm();
    } finally {
      setLoading(false);
    }
  };

  const updateScrollPromoConfig = (key: keyof ScrollPromoConfig, value: string | number) => {
    setScrollPromoConfig(current => ({ ...current, [key]: value }));
  };
  const scrollPromoCandidateCount = Math.round(scrollPromoConfig.motion_window_duration_seconds * scrollPromoConfig.fps);
  const scrollPromoConfigValid = !scrollPromoMode || (
    scrollPromoConfig.motion_window_offset_seconds + scrollPromoConfig.motion_window_duration_seconds <= scrollPromoConfig.dynamic_swipe_duration_seconds
    && scrollPromoCandidateCount >= scrollPromoConfig.max_frames
  );
  const submitLabel = loading
    ? '提交中...'
    : floorAuditMode
      ? '提交新品楼层检查'
      : scrollPromoMode
        ? '提交滑动贴片任务'
        : '提交需求';

  return (
    <div
      className="animate-fade-in-scale"
      style={{
        maxWidth: 720,
        margin: '0 auto',
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-lg)',
        padding: 40,
      }}
    >
      <h2 style={{ marginBottom: 8 }}>提交需求</h2>
      <p style={{ marginBottom: 20, color: 'var(--text-secondary)' }}>
        直接描述你想采集的页面和目标
      </p>

      <div className="scroll-promo-entry" style={{ marginBottom: 24, padding: 18, border: '1px solid rgba(239, 68, 68, 0.35)', borderRadius: 'var(--radius-md)', background: 'rgba(239, 68, 68, 0.06)' }}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>滑动贴片专项任务</div>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', lineHeight: 1.6, marginBottom: 12 }}>
          打开京东“新品”Tab，分析滑动前贴片和关闭按钮，并从滑动过程帧判断贴片是否收起。
        </p>
        <button type="button" className="btn-sm" style={{ background: '#dc2626' }} onClick={handleCreateScrollPromo}>
          {scrollPromoMode ? '✓ 滑动贴片模板已载入' : '载入滑动贴片任务模板'}
        </button>
        <span style={{ marginLeft: 10, color: 'var(--text-tertiary)', fontSize: '0.8125rem' }}>检查后再提交，不会立即创建需求</span>
      </div>

      <div className="floor-audit-entry" style={{ marginBottom: 24, padding: 18, border: '1px solid rgba(255, 159, 10, 0.35)', borderRadius: 'var(--radius-md)', background: 'rgba(255, 159, 10, 0.06)' }}>
        <div style={{ fontWeight: 600, marginBottom: 6 }}>新品楼层规范检查</div>
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', lineHeight: 1.6, marginBottom: 12 }}>
          一次进入京东“新品”页，报告分为“腰部楼层巡查”和“二级tab组件巡查”，分别展示原 3.3 至 3.9 检查及新增滚动、颜色、单行和横滑证据。
        </p>
        <button type="button" className="btn-sm" style={{ background: '#c96f00' }} onClick={handleCreateFloorAudit}>
          {floorAuditMode ? '✓ 新品楼层模板已载入' : '载入新品楼层检查模板'}
        </button>
        <span style={{ marginLeft: 10, color: 'var(--text-tertiary)', fontSize: '0.8125rem' }}>检查后再提交，不会立即创建需求</span>
      </div>

      {templateFeedback && <p role="status" style={{ margin: '-12px 0 24px', color: '#34c759', fontSize: '0.875rem' }}>{templateFeedback}</p>}

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', fontWeight: 500 }}>需求输入</span>
          <textarea
            name="naturalInput"
            value={naturalInput}
            onChange={event => setNaturalInput(event.target.value)}
            placeholder="例如：打开淘宝和拼多多，搜索‘美的M60冰箱520’，点击第一个商品，针对商详截取10屏并拼成长图"
            style={{ minHeight: 132 }}
            autoFocus
          />
        </label>

        {scrollPromoMode && (
          <div className="scroll-promo-config-panel">
            <div>
              <strong>执行参数</strong>
              <p>只有这些结构化参数会改变实际执行，需求文字作为补充说明保存。</p>
            </div>
            <div className="scroll-promo-config-grid">
              <label><span>目标 App</span><input value="京东" disabled /></label>
              <label><span>目标 Tab</span><input value={scrollPromoConfig.target_tab} onChange={e => updateScrollPromoConfig('target_tab', e.target.value)} /></label>
              <label><span>页面等待（秒）</span><input type="number" min="0" max="30" step="0.5" value={scrollPromoConfig.page_wait_seconds} onChange={e => updateScrollPromoConfig('page_wait_seconds', Number(e.target.value))} /></label>
              <label><span>静态帧数量</span><input type="number" min="1" max="5" value={scrollPromoConfig.static_frame_count} onChange={e => updateScrollPromoConfig('static_frame_count', Number(e.target.value))} /></label>
              <label><span>静态上滑距离（px）</span><input type="number" min="50" max="1200" step="50" value={scrollPromoConfig.static_scroll_distance_px} onChange={e => updateScrollPromoConfig('static_scroll_distance_px', Number(e.target.value))} /></label>
              <label><span>静态置信度阈值</span><input type="number" min="0.5" max="0.99" step="0.01" value={scrollPromoConfig.static_confidence_threshold} onChange={e => updateScrollPromoConfig('static_confidence_threshold', Number(e.target.value))} /></label>
              <label><span>动态上滑时长（秒）</span><input type="number" min="0.5" max="5" step="0.5" value={scrollPromoConfig.dynamic_swipe_duration_seconds} onChange={e => updateScrollPromoConfig('dynamic_swipe_duration_seconds', Number(e.target.value))} /></label>
              <label><span>运动窗口起点（秒）</span><input type="number" min="0" max="4" step="0.1" value={scrollPromoConfig.motion_window_offset_seconds} onChange={e => updateScrollPromoConfig('motion_window_offset_seconds', Number(e.target.value))} /></label>
              <label><span>运动窗口时长（秒）</span><input type="number" min="0.2" max="3" step="0.1" value={scrollPromoConfig.motion_window_duration_seconds} onChange={e => updateScrollPromoConfig('motion_window_duration_seconds', Number(e.target.value))} /></label>
              <label><span>提取 FPS</span><input type="number" min="1" max="20" value={scrollPromoConfig.fps} onChange={e => updateScrollPromoConfig('fps', Number(e.target.value))} /></label>
              <label><span>最多分析帧</span><input type="number" min="1" max="10" value={scrollPromoConfig.max_frames} onChange={e => updateScrollPromoConfig('max_frames', Number(e.target.value))} /></label>
              <label><span>收起宽度比例</span><input type="number" min="0.01" max="0.99" step="0.01" value={scrollPromoConfig.collapse_width_ratio} onChange={e => updateScrollPromoConfig('collapse_width_ratio', Number(e.target.value))} /></label>
            </div>
            <div className={`scroll-promo-plan ${scrollPromoConfigValid ? '' : 'invalid'}`}>
              <strong>最终执行计划</strong>
              <p>
                {scrollPromoConfig.static_frame_count} 张静态帧，相邻上滑 {scrollPromoConfig.static_scroll_distance_px}px；
                置信度 ≥ {Math.round(scrollPromoConfig.static_confidence_threshold * 100)}%；
                动态上滑 {scrollPromoConfig.dynamic_swipe_duration_seconds} 秒；
                从 +{scrollPromoConfig.motion_window_offset_seconds} 秒起截取 {scrollPromoConfig.motion_window_duration_seconds} 秒；
                {scrollPromoConfig.fps} FPS 生成约 {scrollPromoCandidateCount} 张候选帧，最多分析 {scrollPromoConfig.max_frames} 张；
                收起阈值 &lt; 静态最大宽度的 {(scrollPromoConfig.collapse_width_ratio * 100).toFixed(1)}%。
              </p>
              {!scrollPromoConfigValid && <p>参数无效：运动窗口必须位于动态滑动时间内，且候选帧数量不能少于最终分析帧。</p>}
            </div>
          </div>
        )}

        {longImageDetected && !scrollPromoMode && !floorAuditMode && (
          <div
            className="long-image-panel"
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: 16,
              padding: 18,
              border: '1px solid var(--border-hover)',
              borderRadius: 'var(--radius-md)',
              background: 'rgba(255, 255, 255, 0.04)',
            }}
          >
            <div>
              <div style={{ fontWeight: 600, marginBottom: 4 }}>补充长图细节</div>
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', lineHeight: 1.6 }}>
                已识别：{isProductDetailLongImage ? '商品详情页长图' : '通用页面长图'} · {captureCount}屏
                {parsingIntent ? ' · 正在补全字段' : ''}
              </p>
            </div>

            <label style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', fontWeight: 500 }}>目标 App</span>
              <input
                value={targetApp}
                onChange={event => setTargetApp(event.target.value)}
                placeholder="例如：淘宝、拼多多"
              />
            </label>

            <label style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', fontWeight: 500 }}>
                {isProductDetailLongImage ? '搜索词' : '关键词 / 关注点'}
              </span>
              <input
                value={keywords}
                onChange={event => setKeywords(event.target.value)}
                placeholder="例如：美的M60冰箱520"
              />
            </label>

            {!isProductDetailLongImage && (
              <label style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', fontWeight: 500 }}>目标页面</span>
                <input
                  value={targetScenario}
                  onChange={event => setTargetScenario(event.target.value)}
                  placeholder="例如：搜索结果页、活动详情页"
                />
              </label>
            )}

            <label style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', fontWeight: 500 }}>截图屏数</span>
              <input
                type="number"
                min={1}
                max={30}
                value={captureCount}
                onChange={event => setCaptureCount(clampCaptureCount(Number(event.target.value)))}
              />
            </label>

            {isProductDetailLongImage && (
              <div>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', fontWeight: 500, marginBottom: 8 }}>
                  排除入口
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
                  <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <input style={{ width: 'auto' }} type="checkbox" checked={excludeLive} onChange={event => setExcludeLive(event.target.checked)} />
                    <span>直播</span>
                  </label>
                  <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <input style={{ width: 'auto' }} type="checkbox" checked={excludeAds} onChange={event => setExcludeAds(event.target.checked)} />
                    <span>广告</span>
                  </label>
                  <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <input style={{ width: 'auto' }} type="checkbox" checked={excludeService} onChange={event => setExcludeService(event.target.checked)} />
                    <span>客服</span>
                  </label>
                </div>
              </div>
            )}
          </div>
        )}

        {/* 分析 Skill 多选 */}
        {!scrollPromoMode && !floorAuditMode && availableSkills.length > 0 && (
          <div>
            <div style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', fontWeight: 500, marginBottom: 8 }}>
              分析技能（可选）
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
              {availableSkills.map(skill => (
                <label key={skill.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                  <input
                    style={{ width: 'auto' }}
                    type="checkbox"
                    checked={selectedSkillIds.includes(skill.id)}
                    onChange={e => {
                      if (e.target.checked) {
                        setSelectedSkillIds([...selectedSkillIds, skill.id]);
                      } else {
                        setSelectedSkillIds(selectedSkillIds.filter(id => id !== skill.id));
                      }
                    }}
                  />
                  <span>{skill.name}</span>
                </label>
              ))}
            </div>
          </div>
        )}

        <button
          type="submit"
          disabled={loading || !inputText || !scrollPromoConfigValid}
          style={{ marginTop: 4, width: 'fit-content' }}
        >
          {submitLabel}
        </button>
      </form>

      {result && (
        <div
          className="animate-fade-in"
          style={{
            marginTop: 24,
            padding: 20,
            background: 'var(--accent-light)',
            borderRadius: 'var(--radius-md)',
            border: '1px solid rgba(168, 85, 247, 0.2)',
          }}
        >
          <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)', marginBottom: 4 }}>
            {result.scroll_promo_config_json
              ? '滑动贴片需求已创建'
              : result.target_scenario === '新品楼层规范检查'
                ? '新品楼层检查需求已创建'
                : '需求已提交'}
          </div>
          <div style={{ fontSize: '0.9375rem', fontWeight: 500 }}>
            ID: {result.id?.slice(0, 8)} · 状态: {result.status}
          </div>
          {result.scroll_promo_config_json && (
            <div style={{ marginTop: 12, color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
              下一步：管理员在“审核管理”中点击“滑动贴片”。
              <a className="link-button btn-sm" style={{ marginLeft: 10 }} href="/admin/tasks?tab=requests">前往审核管理</a>
            </div>
          )}
          {result.target_scenario === '新品楼层规范检查' && (
            <div style={{ marginTop: 12, color: 'var(--text-secondary)', fontSize: '0.875rem' }}>
              下一步：管理员在“审核管理”中点击“楼层检查”。
              <a className="link-button btn-sm" style={{ marginLeft: 10 }} href="/admin/tasks?tab=requests">前往审核管理</a>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
