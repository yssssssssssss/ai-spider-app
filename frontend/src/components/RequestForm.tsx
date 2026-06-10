import { useEffect, useState } from 'react';
import { createRequest, parseLongImageIntent } from '../api';

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
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inputText) return;

    setLoading(true);
    try {
      const payload = longImageDetected
        ? {
          target_app: targetApp.trim() || inferApps(inputText) || inferApp(inputText),
          target_scenario: `${isProductDetailLongImage ? '商品详情页' : (targetScenario.trim() || inferScenario(inputText))}滚动${captureCount}屏并拼接长图`,
          keywords: splitKeywords(keywords || parsedIntent?.keyword || extractSearchKeyword(inputText)),
          description: [
            inputText,
            `长图采集：截图屏数${captureCount}；${isProductDetailLongImage ? `选择规则：第一个普通商品；排除入口：${excludedEntries.join('、') || '无'}；` : ''}自动裁切重复区域并生成长图，保留原始截图。`,
          ].join('\n'),
        }
        : buildPlainRequest(inputText);

      const { data } = await createRequest(payload);
      setResult(data);
      resetForm();
    } finally {
      setLoading(false);
    }
  };

  const submitLabel = loading ? '提交中...' : '提交需求';

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
      <p style={{ marginBottom: 28, color: 'var(--text-secondary)' }}>
        直接描述你想采集的页面和目标
      </p>

      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <span style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', fontWeight: 500 }}>需求输入</span>
          <textarea
            value={naturalInput}
            onChange={event => setNaturalInput(event.target.value)}
            placeholder="例如：打开淘宝和拼多多，搜索‘美的M60冰箱520’，点击第一个商品，针对商详截取10屏并拼成长图"
            style={{ minHeight: 132 }}
            autoFocus
          />
        </label>

        {longImageDetected && (
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

        <button
          type="submit"
          disabled={loading || !inputText}
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
            需求已提交
          </div>
          <div style={{ fontSize: '0.9375rem', fontWeight: 500 }}>
            ID: {result.id?.slice(0, 8)} · 状态: {result.status}
          </div>
        </div>
      )}
    </div>
  );
}
