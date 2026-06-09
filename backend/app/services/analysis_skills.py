from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import crud, models

MAX_SKILL_MARKDOWN_LENGTH = 20_000
DEFAULT_SKILL_NAMES = {"设计维度", "运营维度"}
DEFAULT_SKILL_ORDER = ("设计维度", "运营维度")
VALID_SKILL_STATUSES = {"active", "disabled"}


def parse_skill_markdown(content: str, fallback_name: str | None = None) -> dict:
    raw = content or ""
    if len(raw) > MAX_SKILL_MARKDOWN_LENGTH:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Skill markdown is too long")
    instruction_md = raw.strip()
    if not instruction_md:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Skill markdown is required")

    first_line = instruction_md.splitlines()[0].strip()
    name = first_line[2:].strip() if first_line.startswith("# ") else (fallback_name or "").strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Skill name is required")
    return {"name": name, "instruction_md": instruction_md}


def validate_skill_status(value: str) -> str:
    status_value = (value or "").strip()
    if status_value not in VALID_SKILL_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid analysis skill status")
    return status_value


def prepare_skill_update(
    *,
    current_name: str,
    current_instruction_md: str,
    name: str | None = None,
    instruction_md: str | None = None,
    status_value: str | None = None,
) -> dict:
    updates = {}
    if name is not None and not name.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Skill name is required")
    if name is not None or instruction_md is not None:
        parsed = parse_skill_markdown(
            instruction_md if instruction_md is not None else current_instruction_md,
            fallback_name=name if name is not None else current_name,
        )
        updates.update(parsed)
    if status_value is not None:
        updates["status"] = validate_skill_status(status_value)
    return updates


def is_custom_skill_snapshot(snapshot: dict) -> bool:
    return not snapshot.get("is_official") and snapshot.get("name") not in DEFAULT_SKILL_NAMES


def validate_skill_selection(snapshots: list[dict]) -> None:
    if not snapshots:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one analysis skill is required")


def build_skill_snapshots(db: Session, skill_ids: list, user: models.User) -> list[dict]:
    if not skill_ids:
        visible = crud.list_visible_analysis_skills(db, user)
        official = [skill for skill in visible if skill.is_official]
        skills = sorted(
            official,
            key=lambda skill: (
                DEFAULT_SKILL_ORDER.index(skill.name) if skill.name in DEFAULT_SKILL_ORDER else len(DEFAULT_SKILL_ORDER),
                skill.name,
            ),
        )
    else:
        skills = crud.get_selectable_analysis_skills(db, skill_ids, user)
    if skill_ids:
        by_id = {skill.id: skill for skill in skills}
        missing_ids = [skill_id for skill_id in skill_ids if skill_id not in by_id]
        if missing_ids:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Analysis skill is unavailable")
        ordered_skills = [by_id[skill_id] for skill_id in skill_ids]
    else:
        ordered_skills = skills

    snapshots = [
        {
            "skill_id": str(skill.id),
            "name": skill.name,
            "instruction_md": skill.instruction_md,
            "is_official": skill.is_official,
        }
        for skill in ordered_skills
    ]
    validate_skill_selection(snapshots)
    return snapshots
