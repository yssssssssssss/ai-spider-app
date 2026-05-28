import RequestForm from '../components/RequestForm';

export default function HomePage() {
  return (
    <div className="animate-fade-in">
      <div
        style={{
          textAlign: 'center',
          padding: '40px 0 60px',
          maxWidth: 720,
          margin: '0 auto',
        }}
      >
        <h1
          style={{
            fontSize: '3.5rem',
            fontWeight: 700,
            letterSpacing: '-0.04em',
            lineHeight: 1.1,
            marginBottom: 20,
            background: 'linear-gradient(135deg, #fff 0%, #a1a1a6 100%)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
          }}
        >
          竞品分析平台
        </h1>
        <p
          style={{
            fontSize: '1.25rem',
            color: '#a1a1a6',
            lineHeight: 1.6,
            maxWidth: 560,
            margin: '0 auto',
          }}
        >
          提交你的竞品搜集需求，AI 将自动帮你采集、分析并生成洞察报告
        </p>
      </div>
      <RequestForm />
    </div>
  );
}
