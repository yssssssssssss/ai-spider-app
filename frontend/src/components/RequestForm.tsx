import { useState } from 'react';
import { createRequest } from '../api';

export default function RequestForm() {
  const [targetApp, setTargetApp] = useState('');
  const [targetScenario, setTargetScenario] = useState('');
  const [keywords, setKeywords] = useState('');
  const [description, setDescription] = useState('');
  const [result, setResult] = useState<any>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const { data } = await createRequest({
      target_app: targetApp,
      target_scenario: targetScenario,
      keywords: keywords.split(',').map(k => k.trim()).filter(Boolean),
      description
    });
    setResult(data);
  };

  return (
    <div>
      <h2>提交竞品搜集需求</h2>
      <form onSubmit={handleSubmit}>
        <div><label>目标App: <input value={targetApp} onChange={e => setTargetApp(e.target.value)} /></label></div>
        <div><label>目标场景: <input value={targetScenario} onChange={e => setTargetScenario(e.target.value)} /></label></div>
        <div><label>关键词(逗号分隔): <input value={keywords} onChange={e => setKeywords(e.target.value)} /></label></div>
        <div><label>补充说明: <textarea value={description} onChange={e => setDescription(e.target.value)} /></label></div>
        <button type="submit">提交需求</button>
      </form>
      {result && <pre>需求ID: {result.id}, 状态: {result.status}</pre>}
    </div>
  );
}
