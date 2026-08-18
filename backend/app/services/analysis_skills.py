"""分析 skill 服务层 — 桥接新旧接口"""

from uuid import UUID

from sqlalchemy.orm import Session

from app import models
from app.services import llm_analyzer


# 内置 skill 定义（种子数据）
SYSTEM_SKILL_DEFAULTS = [
    {
        "name": "普通截图设计/策略分析",
        "description": "生成单张竞品截图的设计分析和策略分析。",
        "prompt": llm_analyzer.ANALYSIS_PROMPT,
        "profile": "default",
        "skill_type": "analysis",
        "is_system": True,
    },
    {
        "name": "持续观察截图分析",
        "description": "针对持续观察场景的截图分析。",
        "prompt": llm_analyzer.WATCH_ANALYSIS_PROMPT,
        "profile": "watch",
        "skill_type": "analysis",
        "is_system": True,
    },
]


def list_analysis_skills(db: Session, profile: str | None = None) -> list[models.AnalysisSkill]:
    """列出所有活跃的分析 skill"""
    q = db.query(models.AnalysisSkill).filter(models.AnalysisSkill.status == "active")
    if profile:
        q = q.filter(models.AnalysisSkill.profile == profile)
    return q.order_by(models.AnalysisSkill.updated_at.desc()).all()


def get_analysis_skill(db: Session, skill_id: UUID) -> models.AnalysisSkill | None:
    """获取单个分析 skill"""
    return db.query(models.AnalysisSkill).filter(
        models.AnalysisSkill.id == skill_id,
        models.AnalysisSkill.status == "active",
    ).first()


def analysis_prompt_overrides(db: Session, profile: str) -> dict[str, str]:
    """从 analysis_skills 表获取 prompt 覆盖（兼容旧接口）"""
    skills = list_analysis_skills(db, profile=profile)
    result: dict[str, str] = {}
    for skill in skills:
        if skill.skill_type == "analysis" and skill.is_system:
            result["analysis_prompt_override"] = skill.prompt
        elif skill.skill_type == "target" and skill.is_system:
            result["target_prompt_override"] = skill.prompt
    return result
