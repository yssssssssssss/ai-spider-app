import re
from typing import Any


SPLIT_PATTERN = re.compile(r"\s*(?:,|，|、|;|；|/|和|以及)\s*")
QUOTED_PATTERN = re.compile(r"[“\"']([^”\"']{1,32})[”\"']")
GOAL_CHECKLIST_MARKER = "目标页面顺序"
HOME_LABELS = {"首页", "主页", "app首页", "应用首页"}
BUSINESS_MODULE_MARKERS = ("会场", "活动", "频道", "补贴", "特价", "秒杀", "领券")


def _norm(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "").strip()).lower()


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


def _home_evidence_keywords(target_app: str | None) -> list[str]:
    app = _norm(target_app)
    if "淘宝" in app:
        return ["首页", "底部主导航", "顶部分类Tab选中推荐"]
    if "京东" in app or app == "jd":
        return ["首页", "底部主导航", "顶部分类Tab选中首页"]
    return ["首页", "底部主导航"]


def _goal_evidence_keywords(target_app: str | None, label: str) -> list[str]:
    if _norm(label) in HOME_LABELS:
        return _home_evidence_keywords(target_app)
    return [label]


def _accepts_business_module(label: str) -> bool:
    normalized = _norm(label)
    return any(marker in normalized for marker in BUSINESS_MODULE_MARKERS)


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
            "evidence_keywords": _goal_evidence_keywords(target_app, label),
            "accepts_business_module": _accepts_business_module(label),
        })
    return goals


def append_target_goal_checklist(instruction: str, goals: list[dict[str, Any]] | None) -> str:
    if not instruction or not goals or GOAL_CHECKLIST_MARKER in instruction:
        return instruction

    lines = []
    for index, goal in enumerate(goals, start=1):
        label = _clean_label(str(goal.get("label") or ""))
        if label:
            keywords = _dedupe([
                _clean_label(str(keyword or ""))
                for keyword in goal.get("evidence_keywords", [])
            ])
            evidence = f"（判定条件：{'、'.join(keywords)}）" if keywords else ""
            if goal.get("accepts_business_module"):
                evidence += "（可接受终态：独立会场/频道页，或当前页面中完整露出与目标等价的业务模块；若已看到模块标题、多个商品/权益和核心利益点，停留结束，不要继续点击“更多”；单个入口按钮不算）"
            lines.append(f"{index}. {label}{evidence}")
    if not lines:
        return instruction

    checklist = "；".join(lines)
    return (
        f"{instruction}。目标页面顺序：{checklist}。"
        "必须按顺序逐页完成；当前页面只满足后续目标时，不算完成前序目标；"
        "不要把“从首页来访”等来源文案当作首页已完成证据。"
        "到达最后一个目标页面后停留并结束任务。"
    )
