import os
from typing import Any
from uuid import UUID

from app.services.page_evidence import evidence_matches_goal, get_page_evidence


FINAL_ANALYSIS_STATUSES = {"success", "partial", "skipped", "failed"}
EVIDENCE_ANALYSIS_STATUSES = {"success", "partial"}
NEGATIVE_MARKERS = ("未出现", "未见", "没有", "不包含", "不是", "缺少", "无法确认", "未找到")
GOAL_FAILURE_MARKERS = ("缺少目标页截图", "目标页截图顺序不正确")


def _is_visible_image(image) -> bool:
    return not os.path.basename(image.file_path).startswith("_temp_")


def _image_order_key(image) -> tuple[Any, Any, str]:
    return (
        getattr(image, "captured_at", None) or getattr(image, "created_at", None),
        getattr(image, "created_at", None),
        str(getattr(image, "id", "")),
    )


def _goal_keywords(goal: dict[str, Any]) -> list[str]:
    keywords = goal.get("evidence_keywords") or []
    label = goal.get("label")
    values = [str(item).strip() for item in keywords if str(item).strip()]
    if label and str(label).strip() not in values:
        values.append(str(label).strip())
    return values


def _analysis_text(image) -> str:
    analysis = getattr(image, "analysis", None)
    if not analysis or analysis.status not in EVIDENCE_ANALYSIS_STATUSES:
        return ""
    custom = analysis.custom_analysis_json if isinstance(analysis.custom_analysis_json, dict) else {}
    dynamic = "\n".join(
        row.get("analysis", "")
        for row in custom.get("results", [])
        if isinstance(row, dict) and row.get("analysis")
    ).strip()
    legacy = "\n".join(part for part in [analysis.design_analysis, analysis.ops_analysis] if part)
    return "\n".join(part for part in [dynamic, legacy] if part)


def _page_evidence(image) -> dict[str, Any] | None:
    analysis = getattr(image, "analysis", None)
    if not analysis or analysis.status not in EVIDENCE_ANALYSIS_STATUSES:
        return None
    return get_page_evidence(analysis)


def _is_negative_mention(line: str, needle: str) -> bool:
    keyword_index = line.find(needle)
    if keyword_index < 0:
        return False
    for marker in NEGATIVE_MARKERS:
        marker_index = line.find(marker)
        if marker_index >= 0 and abs(keyword_index - marker_index) <= 12:
            return True
    return False


def _contains_any(texts: list[str], needles: list[str]) -> bool:
    for raw_line in "\n".join(texts).splitlines():
        line = raw_line.strip().lower()
        for needle in [item.lower() for item in needles if item]:
            if needle in line and not _is_negative_mention(line, needle):
                return True
    return False


def validate_task_run_goals(task, images) -> dict[str, Any] | None:
    raw_goals = getattr(task, "target_goals_json", None) or []
    goals = [goal for goal in raw_goals if isinstance(goal, dict) and goal.get("label")]
    if not goals:
        return None

    visible_images = sorted((image for image in images if _is_visible_image(image)), key=_image_order_key)
    pending_count = sum(
        1
        for image in visible_images
        if not image.analysis or image.analysis.status not in FINAL_ANALYSIS_STATUSES
    )
    evidence_texts = [text for image in visible_images if (text := _analysis_text(image))]
    page_evidences = [evidence for image in visible_images if (evidence := _page_evidence(image))]

    goal_results: list[dict[str, Any]] = []
    matched: list[str] = []
    missing: list[str] = []
    matched_positions: dict[str, list[int]] = {}

    if not visible_images:
        status = "uncertain"
        reason = "尚未采集到截图"
    elif pending_count:
        status = "uncertain"
        reason = "仍有截图待分析"
    elif not evidence_texts and not page_evidences:
        status = "uncertain"
        reason = "没有可用于目标校验的分析证据"
    else:
        status = "matched"
        reason = None

    for goal_index, goal in enumerate(goals):
        label = str(goal["label"])
        required = bool(goal.get("required", True))
        keywords = _goal_keywords(goal)
        if status == "uncertain":
            goal_status = "uncertain"
        elif any(evidence_matches_goal(evidence, goal) for evidence in page_evidences):
            goal_status = "matched"
            matched.append(label)
            matched_positions[label] = [
                index
                for index, image in enumerate(visible_images)
                if evidence_matches_goal(_page_evidence(image), goal)
            ]
        elif not page_evidences and _contains_any(evidence_texts, keywords):
            goal_status = "matched"
            matched.append(label)
            matched_positions[label] = [goal_index]
        else:
            goal_status = "missing"
            if required:
                missing.append(label)
        goal_results.append({
            "label": label,
            "type": goal.get("type") or "page",
            "required": required,
            "status": goal_status,
            "evidence_keywords": keywords,
        })

    order_error = False
    previous_position = -1
    if status != "uncertain":
        for goal in goals:
            label = str(goal["label"])
            positions = matched_positions.get(label) or []
            if not positions:
                continue
            position = next((item for item in positions if item > previous_position), None)
            if position is None:
                order_error = True
                if label not in missing and bool(goal.get("required", True)):
                    missing.append(label)
                for item in goal_results:
                    if item["label"] == label:
                        item["status"] = "missing"
                        break
                continue
            previous_position = position

    if missing:
        status = "missing"
        if order_error:
            reason = f"目标页截图顺序不正确：{'、'.join(missing)}"
        else:
            reason = f"缺少目标页截图：{'、'.join(missing)}"

    return {
        "status": status,
        "reason": reason,
        "matched": matched,
        "missing": missing,
        "order_error": order_error,
        "pending_count": pending_count,
        "image_count": len(visible_images),
        "goals": goal_results,
    }


def missing_goal_failure_reason(validation: dict[str, Any] | None) -> str | None:
    if not validation or validation.get("status") != "missing":
        return None
    missing = validation.get("missing") or []
    if not missing:
        return validation.get("reason") or "缺少目标页截图"
    return f"缺少目标页截图：{'、'.join(missing)}"


def refresh_task_run_goal_validation(db, task_id: UUID, run_id: UUID | None):
    from app import crud

    task = crud.get_task(db, task_id)
    if not task:
        return None
    images = [image for image in task.images if run_id is None or image.task_run_id == run_id]
    validation = validate_task_run_goals(task, images)
    if not validation or not run_id:
        return validation

    run = crud.get_task_run(db, run_id)
    if not run:
        return validation

    was_completed = run.status == "completed"
    update_kwargs: dict[str, Any] = {"goal_validation_json": validation}
    failure_reason = missing_goal_failure_reason(validation)
    if was_completed and failure_reason:
        update_kwargs["status"] = "failed"
        update_kwargs["failure_reason"] = failure_reason
    elif (
        run.status == "failed"
        and validation.get("status") == "matched"
        and any(marker in (run.failure_reason or "") for marker in GOAL_FAILURE_MARKERS)
    ):
        update_kwargs["status"] = "completed"
        update_kwargs["failure_reason"] = ""
    crud.update_task_run(db, run_id, **update_kwargs)
    if was_completed and failure_reason:
        crud.update_task_status(db, task_id, "failed")
    elif update_kwargs.get("status") == "completed":
        crud.update_task_status(db, task_id, "completed")
    return validation
