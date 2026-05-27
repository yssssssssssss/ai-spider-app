export default function ImageCard({ result }: { result: any }) {
  return (
    <div style={{ border: '1px solid #ccc', borderRadius: 8, padding: 12 }}>
      <img src={`file://${result.image.file_path}`} alt="竞品截图" style={{ width: '100%', borderRadius: 4 }} />
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
