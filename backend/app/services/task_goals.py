import re
from typing import Any


SPLIT_PATTERN = re.compile(r"\s*(?:,|，|、|;|；|/|和|以及)\s*")
QUOTED_PATTERN = re.compile(r"[“\"']([^”\"']{1,32})[”\"']")
GOAL_CHECKLIST_MARKER = "目标截图清单"


def _clean_label(value: str | None) -> str:
    if not value:
        return ""
    label = value.strip().strip(" .。,:：;；、，")
    return re.sub(r"\s+", "", label)


def _dedupe(labels: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for label in labels:
        cleaned = _clean_label(label)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _split_labels(text: str | None) -> list[str]:
    if not text:
        return []
    return _dedupe([part for part in SPLIT_PATTERN.split(text) if _clean_label(part)])


def _quoted_labels(text: str | None) -> list[str]:
    if not text:
        return []
    return _dedupe([match.group(1) for match in QUOTED_PATTERN.finditer(text)])


def build_target_goals(
    target_app: str | None,
    target_scenario: str | None,
    keywords: list[str] | None,
    description: str | None,
) -> list[dict[str, Any]]:
    labels = _split_labels(target_scenario)
    if len(labels) < 2:
        quoted = _quoted_labels(description)
        if len(quoted) >= 2:
            labels = quoted
    if not labels and target_scenario:
        labels = [_clean_label(target_scenario)]
    if not labels:
        labels = _dedupe(keywords or [])

    goals: list[dict[str, Any]] = []
    for label in labels:
        goals.append({
            "label": label,
            "type": "page",
            "required": True,
            "evidence_keywords": [label],
        })
    return goals


def append_target_goal_checklist(instruction: str, goals: list[dict[str, Any]] | None) -> str:
    if not instruction or not goals or GOAL_CHECKLIST_MARKER in instruction:
        return instruction

    lines = []
    for index, goal in enumerate(goals, start=1):
        label = _clean_label(str(goal.get("label") or ""))
        if label:
            lines.append(f"{index}. {label}")
    if not lines:
        return instruction

    checklist = "；".join(lines)
    return (
        f"{instruction}。"
        f"{GOAL_CHECKLIST_MARKER}：{checklist}。"
        "执行约束：必须逐一完成清单中的每个目标；"
        "只有当前页面标题或核心内容与当前目标一致时，才能认为该目标完成；"
        "不要把一个目标页面当成另一个目标；"
        "平台会在每一步自动截图并保存；"
        "完成所有目标页后立即结束任务。"
    )
