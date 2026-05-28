import { useState } from 'react';
import { createPortal } from 'react-dom';

export default function ImageCard({ result }: { result: any }) {
  const image = result.image;
  const analysis = result.analysis;
  const [open, setOpen] = useState(false);
  const statusLabel = analysis?.status === 'success' ? '已分析' :
    analysis?.status === 'partial' ? '部分分析' :
    analysis?.status === 'skipped' ? '已跳过' :
    analysis?.status === 'pending' ? '待分析' :
    analysis ? '失败' : '待分析';
  const statusColor = analysis?.status === 'success' ? 'rgba(48,209,88,0.9)' :
    analysis?.status === 'partial' ? 'rgba(255,159,10,0.9)' :
    analysis?.status === 'skipped' ? 'rgba(142,142,147,0.9)' :
    analysis?.status === 'pending' ? 'rgba(142,142,147,0.9)' :
    'rgba(255,69,58,0.9)';
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
          <img
            src={`/api/images/${image.id}/file`}
            alt="完整竞品截图"
            style={{
              maxWidth: '100%',
              maxHeight: '86vh',
              objectFit: 'contain',
              display: 'block',
            }}
          />
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
          <img
            src={`/api/images/${image.id}/file`}
            alt="竞品截图"
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
            onError={(e) => {
              (e.target as HTMLElement).style.display = 'none';
            }}
          />
          <div
            style={{
              position: 'absolute',
              top: 8,
              right: 8,
              padding: '2px 8px',
              borderRadius: 'var(--radius-pill)',
              fontSize: '0.75rem',
              fontWeight: 600,
              background: statusColor,
              color: '#fff',
            }}
          >
            {statusLabel}
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
