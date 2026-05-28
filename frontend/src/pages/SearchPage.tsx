import SearchBox from '../components/SearchBox';

export default function SearchPage() {
  return (
    <div className="animate-fade-in">
      <div
        style={{
          textAlign: 'center',
          padding: '40px 0 48px',
          maxWidth: 640,
          margin: '0 auto',
        }}
      >
        <h1
          style={{
            fontSize: '2.75rem',
            fontWeight: 700,
            letterSpacing: '-0.03em',
            marginBottom: 16,
          }}
        >
          图片检索
        </h1>
        <p
          style={{
            fontSize: '1.125rem',
            color: '#a1a1a6',
            lineHeight: 1.6,
          }}
        >
          使用自然语言描述，快速检索已采集的竞品截图
        </p>
      </div>
      <SearchBox />
    </div>
  );
}
