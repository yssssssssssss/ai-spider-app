export default function ImageCard({ result }: { result: any }) {
  // 将本地文件路径转换为后端静态文件URL
  const imageUrl = result.image.file_path.startsWith('/')
    ? `/static${result.image.file_path}`
    : `/static/${result.image.file_path}`;

  return (
    <div style={{ border: '1px solid #ccc', borderRadius: 8, padding: 12 }}>
      <img src={imageUrl} alt="竞品截图" style={{ width: '100%', borderRadius: 4 }} />
      <div><strong>App:</strong> {result.image.source_app} | <strong>场景:</strong> {result.image.scenario}</div>
      {result.analysis && (
        <>
          <div><strong>设计分析:</strong> {result.analysis.design_analysis?.slice(0, 200)}...</div>
          <div><strong>运营分析:</strong> {result.analysis.ops_analysis?.slice(0, 200)}...</div>
        </>
      )}
    </div>
  );
}
