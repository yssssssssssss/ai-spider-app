import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { imageFileUrl } from '../api';

function analysisBlocks(analysis: any) {
  const results = analysis?.custom_analysis_json?.results;
  if (Array.isArray(results) && results.length > 0) {
    return results
      .filter((row: any) => row?.analysis)
      .map((row: any) => ({ title: row.skill_name || '分析维度', text: row.analysis }));
  }
  const blocks = [];
  if (analysis?.design_analysis) blocks.push({ title: '设计分析', text: analysis.design_analysis });
  if (analysis?.ops_analysis) blocks.push({ title: '运营分析', text: analysis.ops_analysis });
  return blocks;
}

export default function ImageCard({ result, imageUrl }: { result: any; imageUrl?: string }) {
  const image = result.image;
  const analysis = result.analysis;
  const blocks = analysisBlocks(analysis);
  const [open, setOpen] = useState(false);
  const [imageError, setImageError] = useState(false);
  useEffect(() => {
    setImageError(false);
  }, [image.id]);
  useEffect(() => {
    if (!open) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open]);
  const statusLabel = analysis?.status === 'success' ? '已分析' :
    analysis?.status === 'partial' ? '部分分析' :
    analysis?.status === 'skipped' ? '已跳过' :
    analysis?.status === 'pending' ? '待分析' :
    analysis ? '失败' : '待分析';
  const statusColor = analysis?.status === 'success' ? 'rgba(48,209,88,0.9)' :
    analysis?.status === 'partial' ? 'rgba(255,159,10,0.9)' :
    analysis?.status === 'failed' ? 'rgba(255,69,58,0.9)' :
    analysis?.status === 'skipped' ? 'rgba(142,142,147,0.9)' :
    analysis?.status === 'pending' ? 'rgba(142,142,147,0.9)' :
    'rgba(142,142,147,0.9)';
  const embeddingStatus = analysis?.embedding_status;
  const embeddingLabel = embeddingStatus === 'success' ? '已向量化' :
    embeddingStatus === 'failed' ? '向量化失败' :
    '待向量化';
  const embeddingColor = embeddingStatus === 'success' ? 'rgba(48,209,88,0.9)' :
    embeddingStatus === 'failed' ? 'rgba(255,69,58,0.9)' :
    'rgba(142,142,147,0.9)';
  const src = imageUrl || imageFileUrl(image.id);
  const missingImagePlaceholder = (
    <div
      style={{
        width: '100%',
        height: '100%',
        minHeight: 220,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 8,
        color: 'var(--text-tertiary)',
        textAlign: 'center',
        padding: 24,
      }}
    >
      <span style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>图片暂不可预览</span>
      <small>文件缺失或路径不可访问</small>
    </div>
  );
  const detailDialog = open ? (
    <div
      role="dialog"
      aria-modal="true"
      onClick={() => setOpen(false)}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1000,
        background: 'rgba(0, 0, 0, 0.78)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
      }}
    >
      <div
        className="image-detail-dialog"
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 'min(1180px, 100%)',
          maxHeight: '92vh',
          display: 'grid',
          gap: 0,
          background: 'var(--bg-secondary)',
          border: '1px solid var(--border-hover)',
          borderRadius: 'var(--radius-lg)',
          overflow: 'hidden',
          boxShadow: 'var(--shadow-lg)',
        }}
      >
        <div
          style={{
            minHeight: 420,
            maxHeight: '92vh',
            background: '#050505',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: 20,
            overflow: 'auto',
          }}
        >
          {imageError ? missingImagePlaceholder : (
            <img
              src={src}
              alt="完整竞品截图"
              width={image.width || 1080}
              height={image.height || 1920}
              style={{
                maxWidth: '100%',
                maxHeight: '86vh',
                objectFit: 'contain',
                display: 'block',
              }}
              onError={() => setImageError(true)}
            />
          )}
        </div>
        <div style={{ padding: 28, overflow: 'auto', maxHeight: '92vh' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-start', marginBottom: 24 }}>
            <div>
              <div style={{ display: 'flex', gap: 8, marginBottom: 10 }}>
                <span style={{ fontSize: '0.8125rem', fontWeight: 600, background: 'var(--bg-tertiary)', padding: '4px 10px', borderRadius: 'var(--radius-pill)' }}>
                  {image.source_app || '未知来源'}
                </span>
                <span style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', padding: '4px 0' }}>
                  {image.scenario || '未标注场景'}
                </span>
              </div>
              <h3>截图分析</h3>
            </div>
            <button type="button" className="btn-secondary btn-sm" onClick={() => setOpen(false)}>
              关闭
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
            {blocks.length === 0 ? (
              <section>
                <div style={{ color: 'var(--text-secondary)', fontWeight: 600, marginBottom: 8 }}>分析结果</div>
                <p style={{ lineHeight: 1.8 }}>暂无分析结果</p>
              </section>
            ) : blocks.map((block, index) => (
              <section key={`${block.title}-${index}`}>
                <div style={{ color: index === 0 ? 'var(--accent)' : '#0a84ff', fontWeight: 600, marginBottom: 8 }}>{block.title}</div>
                <p style={{ lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>
                  {block.text}
                </p>
              </section>
            ))}
          </div>
        </div>
      </div>
    </div>
  ) : null;

  return (
    <>
      <div
        role="button"
        tabIndex={0}
        onClick={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') setOpen(true);
        }}
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-lg)',
          overflow: 'hidden',
          transition: 'all var(--transition-base)',
          cursor: 'pointer',
        }}
        onMouseEnter={(e) => {
          const el = e.currentTarget;
          el.style.borderColor = 'var(--border-hover)';
          el.style.background = 'var(--bg-card-hover)';
          el.style.transform = 'translateY(-4px)';
          el.style.boxShadow = 'var(--shadow-lg)';
        }}
        onMouseLeave={(e) => {
          const el = e.currentTarget;
          el.style.borderColor = 'var(--border)';
          el.style.background = 'var(--bg-card)';
          el.style.transform = 'translateY(0)';
          el.style.boxShadow = 'none';
        }}
      >
        <div
          style={{
            position: 'relative',
            overflow: 'hidden',
            aspectRatio: '1 / 1',
            background: 'var(--bg-tertiary)',
          }}
        >
          {imageError ? missingImagePlaceholder : (
            <img
              src={src}
              alt="竞品截图"
              width={image.width || 360}
              height={image.height || 360}
              loading="lazy"
              style={{
                width: '100%',
                height: '100%',
                objectFit: 'contain',
                display: 'block',
                transition: 'transform var(--transition-slow)',
              }}
              onMouseEnter={(e) => {
                (e.target as HTMLElement).style.transform = 'scale(1.03)';
              }}
              onMouseLeave={(e) => {
                (e.target as HTMLElement).style.transform = 'scale(1)';
              }}
              onError={() => setImageError(true)}
            />
          )}
          <div
            style={{
              position: 'absolute',
              top: 8,
              right: 8,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'flex-end',
              gap: 6,
            }}
          >
            <span
              style={{
                padding: '2px 8px',
                borderRadius: 'var(--radius-pill)',
                fontSize: '0.75rem',
                fontWeight: 600,
                background: statusColor,
                color: '#fff',
              }}
            >
              {statusLabel}
            </span>
            <span
              title={analysis?.embedding_error || embeddingLabel}
              style={{
                padding: '2px 8px',
                borderRadius: 'var(--radius-pill)',
                fontSize: '0.75rem',
                fontWeight: 600,
                background: embeddingColor,
                color: '#fff',
              }}
            >
              {embeddingLabel}
            </span>
          </div>
        </div>

        <div style={{ padding: 20 }}>
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              marginBottom: 12,
            }}
          >
            <span
              style={{
                fontSize: '0.8125rem',
                fontWeight: 600,
                color: 'var(--text-primary)',
                background: 'var(--bg-tertiary)',
                padding: '4px 10px',
                borderRadius: 'var(--radius-pill)',
              }}
            >
              {image.source_app}
            </span>
            <span
              style={{
                fontSize: '0.8125rem',
                color: 'var(--text-secondary)',
              }}
            >
              {image.scenario}
            </span>
          </div>

          {analysis?.embedding_status === 'failed' && (
            <p
              title={analysis.embedding_error || ''}
              style={{
                fontSize: '0.8125rem',
                lineHeight: 1.5,
                color: '#ff453a',
                marginBottom: 12,
              }}
            >
              {analysis.embedding_error ? `向量化失败：${analysis.embedding_error.slice(0, 80)}` : '向量化失败'}
            </p>
          )}

          {analysis && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {blocks.map((block, index) => (
                <div key={`${block.title}-${index}`}>
                  <div
                    style={{
                      fontSize: '0.75rem',
                      fontWeight: 500,
                      textTransform: 'uppercase',
                      letterSpacing: '0.08em',
                      color: index === 0 ? 'var(--accent)' : '#0a84ff',
                      marginBottom: 4,
                    }}
                  >
                    {block.title}
                  </div>
                  <p style={{ fontSize: '0.875rem', lineHeight: 1.6 }}>
                    {block.text.slice(0, 120)}
                    {block.text.length > 120 ? '...' : ''}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {detailDialog && createPortal(detailDialog, document.body)}
    </>
  );
}
