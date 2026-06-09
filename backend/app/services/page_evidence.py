from typing import Any


MIN_PAGE_EVIDENCE_CONFIDENCE = 0.75
TERMINAL_PAGE_STATES = {"app_home", "target_page"}
NON_TERMINAL_PAGE_STATES = {"loading", "intermediate", "wrong_page"}


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _norm(value: Any) -> str:
    return "".join(str(value or "").lower().split())


def _texts(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    elif value:
        raw = [value]
    else:
        raw = []
    return [_clean(item) for item in raw if _clean(item)]


def _confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0)))
    except (TypeError, ValueError):
        return 0.0


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "是"}
    return bool(value)


def get_page_evidence(analysis: Any) -> dict[str, Any] | None:
    custom = _value(analysis, "custom_analysis_json", {})
    if not isinstance(custom, dict):
        return None
    evidence = custom.get("page_evidence")
    return evidence if isinstance(evidence, dict) else None


def evidence_is_usable(evidence: dict[str, Any] | None, min_confidence: float = MIN_PAGE_EVIDENCE_CONFIDENCE) -> bool:
    if not isinstance(evidence, dict):
        return False
    if _confidence(evidence.get("confidence")) < min_confidence:
        return False
    return not _texts(evidence.get("negative_evidence"))


def evidence_is_terminal(evidence: dict[str, Any] | None) -> bool:
    if not isinstance(evidence, dict):
        return False
    if _bool(evidence.get("needs_more_wait")):
        return False
    if "is_terminal_target" in evidence and not _bool(evidence.get("is_terminal_target")):
        return False
    page_state = _clean(evidence.get("page_state")).lower()
    if page_state in NON_TERMINAL_PAGE_STATES:
        return False
    if page_state:
        return page_state in TERMINAL_PAGE_STATES
    return True


def terminal_evidence_is_usable(
    evidence: dict[str, Any] | None,
    min_confidence: float = MIN_PAGE_EVIDENCE_CONFIDENCE,
) -> bool:
    return evidence_is_usable(evidence, min_confidence) and evidence_is_terminal(evidence)


def terminal_evidence_can_match_goal(
    evidence: dict[str, Any] | None,
    goal_label: str,
    min_confidence: float = MIN_PAGE_EVIDENCE_CONFIDENCE,
) -> bool:
    if not isinstance(evidence, dict):
        return False
    if _confidence(evidence.get("confidence")) < min_confidence:
        return False
    if not evidence_is_terminal(evidence):
        return False
    label = _norm(goal_label)
    if not label:
        return False
    for line in _texts(evidence.get("negative_evidence")):
        if label and label in _norm(line):
            return False
    return True


def evidence_matches_goal(
    evidence: dict[str, Any] | None,
    goal: dict[str, Any],
    min_confidence: float = MIN_PAGE_EVIDENCE_CONFIDENCE,
) -> bool:
    label = _norm(goal.get("label"))
    if not label:
        return False
    if not terminal_evidence_can_match_goal(evidence, label, min_confidence):
        return False
    matched_labels = {_norm(item) for item in _texts(evidence.get("matched_goal_labels"))}
    matched_names = {_norm(evidence.get("matched_target_name"))}
    return label in matched_labels or label in matched_names


def slot_match_from_evidence(
    evidence: dict[str, Any] | None,
    slots: list[Any],
    min_confidence: float = MIN_PAGE_EVIDENCE_CONFIDENCE,
) -> dict[str, Any] | None:
    if not terminal_evidence_is_usable(evidence, min_confidence):
        return None

    slot_by_key = {_clean(_value(slot, "slot_key")): slot for slot in slots if _clean(_value(slot, "slot_key"))}
    candidate_keys = [
        _clean(evidence.get("matched_target_key")),
        _clean(evidence.get("matched_slot_key")),
        _clean(evidence.get("slot_key")),
    ]
    for key in candidate_keys:
        if key in slot_by_key:
            return {
                "slot": slot_by_key[key],
                "confidence": _confidence(evidence.get("confidence")),
                "reason": _clean(evidence.get("reason")) or "命中页面证据",
            }

    candidate_names = {
        _norm(evidence.get("matched_target_name")),
        *{_norm(item) for item in _texts(evidence.get("matched_goal_labels"))},
    }
    for slot in slots:
        if _norm(_value(slot, "name")) in candidate_names:
            return {
                "slot": slot,
                "confidence": _confidence(evidence.get("confidence")),
                "reason": _clean(evidence.get("reason")) or "命中页面证据",
            }
    return None


def merge_page_evidence(custom_analysis_json: dict[str, Any] | None, evidence: dict[str, Any] | None) -> dict[str, Any]:
    custom = dict(custom_analysis_json or {})
    if isinstance(evidence, dict):
        custom["page_evidence"] = evidence
    return custom
