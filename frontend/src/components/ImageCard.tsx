import { useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import { imageFileUrl } from '../api';

export default function ImageCard({ result }: { result: any }) {
  const image = result.image;
  const analysis = result.analysis;
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
  const src = imageFileUrl(image.id);
  const fallbackDownloadName = `screenshot-${image.id}.png`;
  const downloadFilename = typeof image.file_path === 'string' && image.file_path.trim()
    ? image.file_path.split(/[\\/]/).pop() || fallbackDownloadName
    : fallbackDownloadName;
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
          className="image-detail-preview-pane"
        >
          <div className="image-detail-preview-scroll">
            {imageError ? missingImagePlaceholder : (
              <img
                className="image-detail-image"
                src={src}
                alt="完整竞品截图"
                width={image.width || 1080}
                height={image.height || 1920}
                onError={() => setImageError(true)}
              />
            )}
          </div>
        </div>
        <div className="image-detail-analysis-pane">
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
            <div className="image-detail-actions">
              <a className="link-button btn-secondary btn-sm" href={src} download={downloadFilename}>
                下载图片
              </a>
              <button type="button" className="btn-secondary btn-sm" onClick={() => setOpen(false)}>
                关闭
              </button>
            </div>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: 22 }}>
            <section>
              <div style={{ color: 'var(--accent)', fontWeight: 600, marginBottom: 8 }}>设计分析</div>
              <p style={{ lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>
                {analysis?.design_analysis || '暂无设计分析'}
              </p>
            </section>
            <section>
              <div style={{ color: '#0a84ff', fontWeight: 600, marginBottom: 8 }}>运营分析</div>
              <p style={{ lineHeight: 1.8, whiteSpace: 'pre-wrap' }}>
                {analysis?.ops_analysis || '暂无运营分析'}
              </p>
            </section>
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
              {analysis.design_analysis && (
                <div>
                  <div
                    style={{
                      fontSize: '0.75rem',
                      fontWeight: 500,
                      textTransform: 'uppercase',
                      letterSpacing: '0.08em',
                      color: 'var(--accent)',
                      marginBottom: 4,
                    }}
                  >
                    设计分析
                  </div>
                  <p style={{ fontSize: '0.875rem', lineHeight: 1.6 }}>
                    {analysis.design_analysis.slice(0, 120)}
                    {analysis.design_analysis.length > 120 ? '...' : ''}
                  </p>
                </div>
              )}
              {analysis.ops_analysis && (
                <div>
                  <div
                    style={{
                      fontSize: '0.75rem',
                      fontWeight: 500,
                      textTransform: 'uppercase',
                      letterSpacing: '0.08em',
                      color: '#0a84ff',
                      marginBottom: 4,
                    }}
                  >
                    运营分析
                  </div>
                  <p style={{ fontSize: '0.875rem', lineHeight: 1.6 }}>
                    {analysis.ops_analysis.slice(0, 120)}
                    {analysis.ops_analysis.length > 120 ? '...' : ''}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {detailDialog && createPortal(detailDialog, document.body)}
    </>
  );
}
