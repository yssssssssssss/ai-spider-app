import { useEffect, useMemo, useState } from 'react';
import { useLocation } from 'react-router-dom';
import AnalysisSkills from './AnalysisSkills';
import CompareSkills from './CompareSkills';

type SkillTab = 'analysis' | 'compare';

export default function SkillEditor() {
  const location = useLocation();
  const initialTab = useMemo<SkillTab>(() => {
    const params = new URLSearchParams(location.search);
    return params.get('tab') === 'compare' ? 'compare' : 'analysis';
  }, [location.search]);
  const [tab, setTab] = useState<SkillTab>(initialTab);

  useEffect(() => {
    setTab(initialTab);
  }, [initialTab]);

  return (
    <div className="animate-fade-in skill-editor-page">
      <div className="page-header">
        <h1>Skill 编辑</h1>
        <p>集中维护截图分析和对比分析使用的 Prompt/Skill</p>
      </div>

      <div className="admin-tabbar" role="tablist" aria-label="Skill 编辑类型">
        <button type="button" className={tab === 'analysis' ? 'active' : ''} onClick={() => setTab('analysis')}>
          截图分析 Skill
        </button>
        <button type="button" className={tab === 'compare' ? 'active' : ''} onClick={() => setTab('compare')}>
          对比分析 Skill
        </button>
      </div>

      {tab === 'analysis' ? <AnalysisSkills /> : <CompareSkills embedded />}
    </div>
  );
}
