import { useState } from 'react';
import { searchImages } from '../api';
import ImageCard from './ImageCard';

const SEARCH_RESULT_LIMIT = 3;

export default function SearchBox() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  const searchMode = results.find(r => r.search_mode)?.search_mode;
  const modeLabel = searchMode === 'vector' ? '向量搜索' : searchMode === 'text' ? '文本兜底搜索' : null;

  const handleSearch = async () => {
    if (!query.trim()) return;
    setLoading(true);
    try {
      const { data } = await searchImages({ query, limit: SEARCH_RESULT_LIMIT });
      setResults(data);
    } finally {
      setLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSearch();
  };

  return (
    <div className="animate-fade-in">
      <div
        style={{
          maxWidth: 640,
          margin: '0 auto 40px',
          display: 'flex',
          gap: 12,
        }}
      >
        <div style={{ flex: 1, position: 'relative' }}>
          <svg
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            style={{
              position: 'absolute',
              left: 14,
              top: '50%',
              transform: 'translateY(-50%)',
              color: 'var(--text-tertiary)',
              pointerEvents: 'none',
            }}
          >
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.3-4.3" />
          </svg>
	          <input
	            aria-label="图片检索描述"
	            name="image-search-query"
	            autoComplete="off"
	            value={query}
	            onChange={e => setQuery(e.target.value)}
	            onKeyDown={handleKeyDown}
	            placeholder="输入描述，如红色大促弹窗设计…"
	            style={{ paddingLeft: 42 }}
	          />
	        </div>
        <button onClick={handleSearch} disabled={loading || !query.trim()}>
          {loading ? '搜索中...' : '搜索'}
        </button>
      </div>

      {results.length > 0 && (
        <div style={{ marginBottom: 16 }}>
	          <span style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
	            找到 {results.length} 条结果
	            {modeLabel ? ` · ${modeLabel}` : ''}
	          </span>
	        </div>
      )}

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
          gap: 20,
        }}
      >
        {results.map((r, i) => (
          <div
            key={i}
            className="animate-fade-in"
            style={{ animationDelay: `${i * 0.05}s` }}
          >
            <ImageCard result={r} />
          </div>
        ))}
      </div>

      {results.length === 0 && !loading && query && (
        <div
          style={{
            textAlign: 'center',
            padding: '80px 0',
            color: 'var(--text-tertiary)',
          }}
        >
          <svg
            width="48"
            height="48"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            style={{ marginBottom: 16, opacity: 0.5 }}
          >
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <circle cx="8.5" cy="8.5" r="1.5" />
            <path d="M21 15l-5-5L5 21" />
          </svg>
          <p>未找到相关结果</p>
        </div>
      )}
    </div>
  );
}
