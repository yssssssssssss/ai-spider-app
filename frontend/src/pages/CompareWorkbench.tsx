import { ReactNode, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  clearComparisonBasket,
  comparisonAssetFileUrl,
  createComparisonReport,
  deleteComparisonBasketItem,
  listComparisonAssets,
  listComparisonBasket,
  listComparisonReports,
  listComparisonSkills,
  uploadComparisonAsset,
} from '../api';
import { useToast } from '../components/Toast';

function AssetThumb({ asset, selected, onToggle }: { asset: any; selected: boolean; onToggle: () => void }) {
  return (
    <button type="button" className={`compare-asset-tile ${selected ? 'selected' : ''}`} onClick={onToggle}>
      <img src={comparisonAssetFileUrl(asset.id)} alt={asset.display_name} loading="lazy" />
      <span>{asset.display_name}</span>
      <small>{asset.source_app || '未知来源'} · {asset.scenario || '未标注场景'}</small>
    </button>
  );
}

function stripMarkdownFence(markdown: string) {
  return markdown
    .replace(/^```(?:markdown|md)?\s*/i, '')
    .replace(/\s*```$/i, '')
    .trim();
}

function parseInline(text: string) {
  const parts = text.split(/(\*\*[^*]+\*\*)/g);
  return parts.map((part, index) => {
    if (part.startsWith('**') && part.endsWith('**')) {
      return <strong key={index}>{part.slice(2, -2)}</strong>;
    }
    return <span key={index}>{part}</span>;
  });
}

function MarkdownReport({ value }: { value: string }) {
  const lines = stripMarkdownFence(value).split('\n');
  const nodes: ReactNode[] = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index].trim();
    if (!line) {
      index += 1;
      continue;
    }
    if (line.startsWith('|')) {
      const tableRows: string[][] = [];
      while (index < lines.length && lines[index].trim().startsWith('|')) {
        const row = lines[index].trim();
        if (!/^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(row)) {
          tableRows.push(row.replace(/^\||\|$/g, '').split('|').map(cell => cell.trim()));
        }
        index += 1;
      }
      const [head, ...body] = tableRows;
      nodes.push(
        <table key={nodes.length} className="markdown-table">
          {head && <thead><tr>{head.map((cell, cellIndex) => <th key={cellIndex}>{parseInline(cell)}</th>)}</tr></thead>}
          <tbody>
            {body.map((row, rowIndex) => (
              <tr key={rowIndex}>{row.map((cell, cellIndex) => <td key={cellIndex}>{parseInline(cell)}</td>)}</tr>
            ))}
          </tbody>
        </table>
      );
      continue;
    }
    if (line.startsWith('### ')) {
      nodes.push(<h4 key={nodes.length}>{parseInline(line.slice(4))}</h4>);
    } else if (line.startsWith('## ')) {
      nodes.push(<h3 key={nodes.length}>{parseInline(line.slice(3))}</h3>);
    } else if (line.startsWith('# ')) {
      nodes.push(<h2 key={nodes.length}>{parseInline(line.slice(2))}</h2>);
    } else if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (index < lines.length && /^[-*]\s+/.test(lines[index].trim())) {
        items.push(lines[index].trim().replace(/^[-*]\s+/, ''));
        index += 1;
      }
      nodes.push(<ul key={nodes.length}>{items.map((item, itemIndex) => <li key={itemIndex}>{parseInline(item)}</li>)}</ul>);
      continue;
    } else {
      nodes.push(<p key={nodes.length}>{parseInline(line)}</p>);
    }
    index += 1;
  }

  return <div className="compare-report-content markdown-report">{nodes}</div>;
}

export default function CompareWorkbench() {
  const { showToast } = useToast();
  const [basket, setBasket] = useState<any[]>([]);
  const [assets, setAssets] = useState<any[]>([]);
  const [skills, setSkills] = useState<any[]>([]);
  const [selectedAssetIds, setSelectedAssetIds] = useState<string[]>([]);
  const [skillId, setSkillId] = useState('');
  const [focusQuestion, setFocusQuestion] = useState('');
  const [uploading, setUploading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [reports, setReports] = useState<any[]>([]);
  const [currentReport, setCurrentReport] = useState<any | null>(null);

  const load = async () => {
    const [{ data: basketRows }, { data: assetRows }, { data: skillRows }, { data: reportRows }] = await Promise.all([
      listComparisonBasket(),
      listComparisonAssets(),
      listComparisonSkills(),
      listComparisonReports(),
    ]);
    setBasket(basketRows);
    setAssets(assetRows);
    setSkills(skillRows.filter((skill: any) => skill.status === 'active'));
    setReports(reportRows);
    setCurrentReport((prev: any | null) => prev || reportRows[0] || null);
    setSkillId((prev: string) => {
      if (prev) return prev;
      const firstActive = skillRows.find((skill: any) => skill.status === 'active');
      return firstActive?.id || '';
    });
  };

  useEffect(() => {
    load().catch(() => undefined);
  }, []);

  const toggleAsset = (id: string) => {
    setSelectedAssetIds(prev => prev.includes(id) ? prev.filter(item => item !== id) : [...prev, id]);
  };

  const handleUpload = async (file?: File | null) => {
    if (!file) return;
    const form = new FormData();
    form.append('file', file);
    setUploading(true);
    try {
      await uploadComparisonAsset(form);
      showToast('图片已上传到对比图片库', 'success');
      await load();
    } catch {
      // api 拦截器已弹出错误 Toast
    } finally {
      setUploading(false);
    }
  };

  const removeBasketItem = async (id: string) => {
    await deleteComparisonBasketItem(id);
    await load();
  };

  const clearBasket = async () => {
    await clearComparisonBasket();
    setSelectedAssetIds([]);
    await load();
  };

  const handleGenerateReport = async () => {
    if (!selectedAssetIds.length || !skillId) return;
    setGenerating(true);
    try {
      const { data } = await createComparisonReport({
        asset_ids: selectedAssetIds,
        skill_id: skillId,
        focus_question: focusQuestion.trim() || null,
      });
      setCurrentReport(data);
      await load();
      showToast(data.status === 'success' ? '对比报告已生成' : '对比报告生成失败', data.status === 'success' ? 'success' : 'error');
    } catch {
      // api 拦截器已弹出错误 Toast
    } finally {
      setGenerating(false);
    }
  };

  const selectedSkill = skills.find(skill => skill.id === skillId);
  const basketAssets = basket.map(item => item.asset);
  const mergedAssets = [
    ...basketAssets,
    ...assets.filter(asset => !basketAssets.some(row => row.id === asset.id)),
  ];

  return (
    <div className="animate-fade-in compare-page">
      <div className="page-header compare-header">
        <div>
          <h1>对比分析工作台</h1>
          <p>选择收藏截图或上传图片，配置分析 Skill 后进入报告生成流程</p>
        </div>
        <Link className="btn-secondary btn-sm link-button" to="/skills?tab=compare">Skill 管理</Link>
      </div>

      <div className="compare-workbench-grid">
        <section className="compare-panel">
          <div className="compare-panel-head">
            <h2>图片样本</h2>
            <label className="upload-inline-button">
              {uploading ? '上传中...' : '上传图片'}
              <input type="file" accept="image/png,image/jpeg,image/webp" onChange={(event) => handleUpload(event.target.files?.[0])} />
            </label>
          </div>

          <div className="compare-basket-strip">
            <div>
              <strong>对比篮</strong>
              <span>{basket.length} 张</span>
            </div>
            <button type="button" className="btn-secondary btn-sm" onClick={clearBasket} disabled={!basket.length}>清空</button>
          </div>
          {basket.length > 0 && (
            <div className="compare-basket-list">
              {basket.map(item => (
                <span key={item.id}>
                  {item.asset.display_name}
                  <button type="button" onClick={() => removeBasketItem(item.id)}>移除</button>
                </span>
              ))}
            </div>
          )}

          <div className="compare-asset-grid">
            {mergedAssets.map(asset => (
              <AssetThumb
                key={asset.id}
                asset={asset}
                selected={selectedAssetIds.includes(asset.id)}
                onToggle={() => toggleAsset(asset.id)}
              />
            ))}
          </div>
        </section>

        <section className="compare-panel">
          <h2>分析配置</h2>
          <label>
            <span>分析 Skill</span>
            <select value={skillId} onChange={(event) => setSkillId(event.target.value)}>
              <option value="">请选择 Skill</option>
              {skills.map(skill => (
                <option key={skill.id} value={skill.id}>{skill.name} v{skill.version}</option>
              ))}
            </select>
          </label>
          {selectedSkill && (
            <div className="compare-skill-summary">
              <strong>{selectedSkill.name}</strong>
              <p>{selectedSkill.description || '暂无描述'}</p>
            </div>
          )}
          <label>
            <span>关注问题</span>
            <textarea
              value={focusQuestion}
              onChange={(event) => setFocusQuestion(event.target.value)}
              placeholder="例如：重点比较首屏卖点、价格表达和转化路径"
            />
          </label>
          <div className="compare-config-footer">
            <span>已选 {selectedAssetIds.length} 张图片</span>
            <button type="button" disabled={!selectedAssetIds.length || !skillId || generating} onClick={handleGenerateReport}>
              {generating ? '生成中...' : '生成报告'}
            </button>
          </div>
        </section>

        <section className="compare-panel compare-report-preview">
          <h2>报告预览</h2>
          {currentReport ? (
            <>
              <div className="compare-report-meta">
                <span>{currentReport.skill_name} v{currentReport.skill_version}</span>
                <span>{currentReport.status === 'success' ? '已完成' : currentReport.status === 'failed' ? '失败' : '生成中'}</span>
              </div>
              {currentReport.status === 'failed' ? (
                <div className="compare-report-error">{currentReport.error || '报告生成失败'}</div>
              ) : (
                <MarkdownReport value={currentReport.report || '报告生成中...'} />
              )}
            </>
          ) : (
            <>
              <p>选择图片和 Skill 后，可生成结构化对比报告。</p>
              <div className="compare-report-placeholder">
                <strong>待生成</strong>
                <span>报告会保留最近 20 条记录</span>
              </div>
            </>
          )}
          {reports.length > 0 && (
            <div className="compare-report-history">
              <strong>最近报告</strong>
              {reports.slice(0, 5).map(report => (
                <button type="button" className="btn-secondary btn-sm" key={report.id} onClick={() => setCurrentReport(report)}>
                  {report.skill_name} · {report.status === 'success' ? '已完成' : report.status === 'failed' ? '失败' : '生成中'}
                </button>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
