import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import { listAnalysisSkills } from '../api';

type AnalysisSkill = {
  id: string;
  name: string;
  instruction_md: string;
  is_official: boolean;
  status: string;
};

const defaultSkillNames = new Set(['设计维度', '运营维度']);

function isValidSelection(skills: AnalysisSkill[], selectedIds: string[]) {
  if (selectedIds.length === 0) return false;
  const selected = new Set(selectedIds);
  const selectedCustom = skills.some(skill => !skill.is_official && selected.has(skill.id));
  const selectedDefault = skills.some(skill => defaultSkillNames.has(skill.name) && selected.has(skill.id));
  return selectedCustom || selectedDefault;
}

export default function AnalysisSkillSelector({ value, onChange }: { value: string[]; onChange: (ids: string[]) => void }) {
  const [skills, setSkills] = useState<AnalysisSkill[]>([]);
  const [loading, setLoading] = useState(true);
  const [warning, setWarning] = useState('');
  const [libraryOpen, setLibraryOpen] = useState(false);
  const activeSkills = useMemo(() => skills.filter(skill => skill.status === 'active'), [skills]);
  const official = useMemo(() => activeSkills.filter(skill => skill.is_official), [activeSkills]);
  const custom = useMemo(() => activeSkills.filter(skill => !skill.is_official), [activeSkills]);
  const orderedSkills = useMemo(() => [...official, ...custom], [official, custom]);
  const selectedSkills = useMemo(() => {
    const selected = new Set(value);
    return orderedSkills.filter(skill => selected.has(skill.id));
  }, [orderedSkills, value]);

  useEffect(() => {
    let ignore = false;
    setLoading(true);
    listAnalysisSkills()
      .then(({ data }) => {
        if (ignore) return;
        setSkills(data);
        if (value.length === 0) {
          const officialIds = data
            .filter((skill: AnalysisSkill) => skill.is_official && skill.status === 'active')
            .map((skill: AnalysisSkill) => skill.id);
          if (officialIds.length > 0) onChange(officialIds);
        }
      })
      .catch(() => {
        if (!ignore) setSkills([]);
      })
      .finally(() => {
        if (!ignore) setLoading(false);
      });
    return () => {
      ignore = true;
    };
  }, []);

  useEffect(() => {
    if (official.length > 0 && value.length === 0) {
      onChange(official.map(skill => skill.id));
    }
  }, [official, onChange, value.length]);

  useEffect(() => {
    if (!libraryOpen) return undefined;
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setLibraryOpen(false);
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [libraryOpen]);

  const toggle = (id: string) => {
    const next = value.includes(id) ? value.filter(item => item !== id) : [...value, id];
    if (!isValidSelection(activeSkills, next)) {
      setWarning('至少选择一个自定义 skill，或保留设计维度/运营维度中的一个');
      return;
    }
    setWarning('');
    onChange(next);
  };

  const skillLibrary = libraryOpen ? createPortal(
    <div className="analysis-skill-modal-layer" role="presentation" onClick={() => setLibraryOpen(false)}>
      <div
        className="analysis-skill-modal analysis-skill-library-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="analysis-skill-library-title"
        onClick={event => event.stopPropagation()}
      >
        <div className="analysis-skill-modal-head">
          <div>
            <h2 id="analysis-skill-library-title">skill 库</h2>
            <p>选择后会应用到本次需求提交</p>
          </div>
          <button type="button" className="btn-secondary btn-sm" onClick={() => setLibraryOpen(false)}>
            完成
          </button>
        </div>
        <div className="analysis-skill-library-grid">
          {orderedSkills.map(skill => {
            const selected = value.includes(skill.id);
            return (
              <button
                key={skill.id}
                type="button"
                className={`analysis-skill-library-card${selected ? ' is-selected' : ''}`}
                aria-pressed={selected}
                onClick={() => toggle(skill.id)}
              >
                <span className="analysis-skill-card-topline">
                  <strong>{skill.name}</strong>
                  {skill.is_official && <em>官方</em>}
                </span>
                <span className="analysis-skill-card-body">{skill.instruction_md}</span>
                <span className="analysis-skill-card-check">{selected ? '已选择' : '选择'}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>,
    document.body,
  ) : null;

  return (
    <section className="analysis-skill-selector">
      <div className="analysis-skill-selector-head">
        <span>分析 skill</span>
        <button
          type="button"
          className="btn-secondary btn-sm"
          onClick={() => setLibraryOpen(true)}
          disabled={loading || activeSkills.length === 0}
        >
          skill 库
        </button>
      </div>
      {warning && <small className="analysis-skill-warning">{warning}</small>}
      {loading ? (
        <div className="skeleton" style={{ height: 42 }} />
      ) : activeSkills.length === 0 ? (
        <p>暂无可用分析 skill</p>
      ) : (
        selectedSkills.length === 0 ? (
          <p>暂无已选 skill</p>
        ) : (
          <div className="analysis-skill-selected-list">
            {selectedSkills.map(skill => (
              <div key={skill.id} className="analysis-skill-selected-card">
                <div>
                  <strong>{skill.name}</strong>
                  {skill.is_official && <em>官方</em>}
                </div>
                <p>{skill.instruction_md}</p>
                <button type="button" className="btn-secondary btn-sm" onClick={() => toggle(skill.id)}>
                  移除
                </button>
              </div>
            ))}
          </div>
        )
      )}
      {skillLibrary}
    </section>
  );
}
