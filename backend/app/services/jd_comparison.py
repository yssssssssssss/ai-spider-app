import re
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app import crud, models, schemas
from app.services.llm_analyzer import analyzer
from app.services.page_evidence import get_page_evidence, slot_match_from_evidence
from app.services.status_reconciler import reconcile_stale_statuses
from app.services.task_goals import append_target_goal_checklist, build_target_goals
from app.services.task_planner import _strip_manual_capture_instruction

JD_APP_NAME = "京东"
MAX_COMPARISON_SLOTS = 5
MIN_JD_INSTRUCTION_LENGTH = 20
MAX_JD_INSTRUCTION_LENGTH = 2000
HIGH_CONFIDENCE_THRESHOLD = 0.75
LOW_CONFIDENCE_THRESHOLD = 0.45

APP_SPLIT_PATTERN = re.compile(r"\s*(?:,|，|、|;|；|/|\n|和|以及)\s*")
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[。！？!?；;])")
SLOT_KEY_TOKEN_MAP = {
    "会": "hui",
    "場": "chang",
    "场": "chang",
    "首": "shou",
    "屏": "ping",
    "商": "shang",
    "品": "pin",
    "详": "xiang",
    "詳": "xiang",
    "情": "qing",
    "页": "ye",
    "頁": "ye",
    "搜": "sou",
    "索": "suo",
    "结": "jie",
    "結": "jie",
    "果": "guo",
    "弹": "tan",
    "彈": "tan",
    "窗": "chuang",
    "关": "guan",
    "關": "guan",
    "闭": "bi",
    "閉": "bi",
    "后": "hou",
    "後": "hou",
    "活": "huo",
    "动": "dong",
    "動": "dong",
    "入": "ru",
    "口": "kou",
}


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" ,，。;；")


def description_for_app(description: str | None, app_name: str) -> str | None:
    text = clean_text(description)
    if not text:
        return None
    known_apps = {JD_APP_NAME, "淘宝", "拼多多", "天猫", "抖音", "快手", "小红书"}
    parts = [part.strip() for part in SENTENCE_SPLIT_PATTERN.split(text) if part.strip()]
    kept = []
    for part in parts:
        mentioned = {app for app in known_apps if app in part}
        if not mentioned or app_name in mentioned:
            kept.append(part)
    return " ".join(kept) or None


def split_app_names(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = [str(item) for item in value]
    else:
        raw = [part for part in APP_SPLIT_PATTERN.split(str(value or "")) if part]
    apps: list[str] = []
    seen: set[str] = set()
    for item in raw:
        app = clean_text(item)
        if not app or app in seen:
            continue
        seen.add(app)
        apps.append(app)
    return apps


def slot_key_from_name(name: str, index: int = 0) -> str:
    parts: list[str] = []
    ascii_buffer: list[str] = []
    for char in clean_text(name):
        if char.isascii() and char.isalnum():
            ascii_buffer.append(char.lower())
            continue
        if ascii_buffer:
            parts.append("".join(ascii_buffer))
            ascii_buffer = []
        token = SLOT_KEY_TOKEN_MAP.get(char)
        if token:
            parts.append(token)
    if ascii_buffer:
        parts.append("".join(ascii_buffer))
    key = "_".join(part for part in parts if part)
    key = re.sub(r"_+", "_", key).strip("_")
    return key or f"slot_{index + 1}"


def default_comparison_slots(target_scenario: str | None = None, description: str | None = None) -> list[dict]:
    text = f"{target_scenario or ''} {description or ''}"
    slots = [
        {
            "slot_key": "promo_landing",
            "name": "会场首屏",
            "description": "进入目标活动或频道后看到的首屏画面，重点观察核心利益点、入口布局和首屏信息密度。",
            "required": True,
        }
    ]
    if any(marker in text for marker in ("商品", "详情", "详情页")):
        slots.append({
            "slot_key": "product_detail",
            "name": "商品详情首屏",
            "description": "从活动、频道或搜索结果进入目标商品详情页后看到的首屏画面。",
            "required": True,
        })
    if any(marker in text for marker in ("弹窗", "浮层", "广告", "关闭后")):
        slots.append({
            "slot_key": "popup_or_after_close",
            "name": "弹窗或关闭后页面",
            "description": "与本次目标相关的弹窗、浮层或关闭弹窗后的目标页面。",
            "required": False,
        })
    return slots[:MAX_COMPARISON_SLOTS]


def build_jd_instruction(target_scenario: str | None, keywords: list[str] | None, description: str | None = None) -> str:
    keyword_text = "、".join(k for k in (keywords or []) if k)
    parts = ["打开京东App"]
    if target_scenario:
        parts.append(f"进入与“{target_scenario}”等价的页面或活动入口")
    elif keyword_text:
        parts.append(f"找到与“{keyword_text}”相关的页面或活动入口")
    else:
        parts.append("进入与用户需求等价的页面")
    if description:
        parts.append("保持与原竞品任务相同的截图目标")
    parts.append("到达目标页面后停留并结束任务")
    return _strip_manual_capture_instruction("，".join(parts))


def enrich_interpret_result(result: dict[str, Any], natural_language: str | None = None) -> dict[str, Any]:
    target_app = result.get("target_app") or ""
    a_apps = result.get("a_apps") or [app for app in split_app_names(target_app) if app != JD_APP_NAME]
    keywords = result.get("keywords") or []
    if not isinstance(keywords, list):
        keywords = []
    target_scenario = result.get("target_scenario") or ""
    description = result.get("description") or natural_language or ""
    enriched = dict(result)
    enriched["a_apps"] = [app for app in split_app_names(a_apps) if app != JD_APP_NAME]
    if not enriched.get("comparison_slots"):
        enriched["comparison_slots"] = default_comparison_slots(target_scenario, description)
    if not enriched.get("jd_instruction"):
        enriched["jd_instruction"] = build_jd_instruction(target_scenario, keywords, description)
    return enriched


def normalize_comparison_config(config: dict | schemas.ComparisonConfigInput | None) -> dict:
    if hasattr(config, "model_dump"):
        raw = config.model_dump()
    else:
        raw = dict(config or {})
    a_apps = [app for app in split_app_names(raw.get("a_apps")) if app]
    if not a_apps:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one A-side app is required")
    if JD_APP_NAME in a_apps:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="A-side apps cannot include 京东")

    jd_instruction = clean_text(raw.get("jd_instruction"))
    if not (MIN_JD_INSTRUCTION_LENGTH <= len(jd_instruction) <= MAX_JD_INSTRUCTION_LENGTH):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="JD instruction length must be 20-2000 characters")

    raw_slots = raw.get("slots") or []
    if not (1 <= len(raw_slots) <= MAX_COMPARISON_SLOTS):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Comparison slots must contain 1-5 items")

    slots = []
    seen_keys: set[str] = set()
    for index, item in enumerate(raw_slots):
        slot = item.model_dump() if hasattr(item, "model_dump") else dict(item or {})
        name = clean_text(slot.get("name"))
        description = clean_text(slot.get("description"))
        if not name or not description:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Comparison slot name and description are required")
        slot_key = clean_text(slot.get("slot_key")) or slot_key_from_name(name, index)
        slot_key = re.sub(r"[^a-zA-Z0-9_]+", "_", slot_key).strip("_").lower() or f"slot_{index + 1}"
        base_key = slot_key
        suffix = 2
        while slot_key in seen_keys:
            slot_key = f"{base_key}_{suffix}"
            suffix += 1
        seen_keys.add(slot_key)
        slots.append({
            "slot_key": slot_key,
            "name": name,
            "description": description,
            "required": bool(slot.get("required", True)),
        })

    return {
        "a_apps": a_apps,
        "jd_instruction": jd_instruction,
        "slots": slots,
    }


def task_app_name(task: models.Task, group: models.ComparisonGroup | None = None) -> str:
    if group and group.jd_task_id == task.id:
        return JD_APP_NAME
    return task.target_app or ""


def _analysis_out(image: models.Image) -> dict | None:
    if not image.analysis:
        return None
    return schemas.AnalysisOut.model_validate(image.analysis).model_dump(mode="json")


def _match_payload(match: models.ComparisonSlotMatch | None) -> dict | None:
    if not match or not match.image:
        return None
    return {
        "image": schemas.ImageOut.model_validate(match.image).model_dump(mode="json"),
        "analysis": _analysis_out(match.image),
        "confidence": match.confidence,
        "reason": match.reason,
    }


def _pair_payload(pair: models.ComparisonPairAnalysis | None) -> dict | None:
    if not pair:
        return None
    return {
        "id": str(pair.id),
        "status": pair.status,
        "custom_analysis_json": pair.custom_analysis_json or {},
        "error": pair.error,
        "analyzed_at": pair.analyzed_at.isoformat() if pair.analyzed_at else None,
    }


def build_comparison_result(db: Session, group: models.ComparisonGroup) -> dict:
    slots = crud.list_comparison_slots(db, group.id)
    matches = crud.list_comparison_slot_matches(db, group.id)
    group_apps = crud.list_comparison_group_apps(db, group.id)
    matched_by_slot_app = {
        (match.slot_id, match.app_name): match
        for match in matches
        if match.status == "matched" and match.slot_id
    }
    unmatched_by_app: dict[str, list[models.ComparisonSlotMatch]] = {}
    for match in matches:
        if match.status in ("low_confidence", "unmatched"):
            unmatched_by_app.setdefault(match.app_name, []).append(match)

    apps = []
    for app in group_apps:
        slot_rows = []
        for slot in slots:
            a_match = matched_by_slot_app.get((slot.id, app.app_name))
            jd_match = matched_by_slot_app.get((slot.id, JD_APP_NAME))
            pair = crud.get_comparison_pair_analysis(db, app.id, slot.id)
            if a_match and jd_match:
                status_value = "analysis_failed" if pair and pair.status == "failed" else "paired"
            elif a_match:
                status_value = "missing_jd"
            elif jd_match:
                status_value = "missing_a"
            else:
                status_value = "unmatched"
            slot_rows.append({
                "slot_id": str(slot.id),
                "slot_key": slot.slot_key,
                "name": slot.name,
                "description": slot.description,
                "status": status_value,
                "a_match": _match_payload(a_match),
                "jd_match": _match_payload(jd_match),
                "pair_analysis": _pair_payload(pair),
            })

        apps.append({
            "id": str(app.id),
            "app_name": app.app_name,
            "task_id": str(app.task_id) if app.task_id else None,
            "status": app.status,
            "slots": slot_rows,
            "unmatched": [
                {
                    **(_match_payload(match) or {}),
                    "status": match.status,
                }
                for match in unmatched_by_app.get(app.app_name, [])
            ],
        })

    return {
        "group_id": str(group.id),
        "request_id": str(group.request_id),
        "baseline_app": group.baseline_app,
        "jd_task_id": str(group.jd_task_id) if group.jd_task_id else None,
        "status": group.status,
        "apps": apps,
    }


def comparison_context(group: models.ComparisonGroup, app_name: str | None = None, slot: models.ComparisonSlot | None = None) -> dict:
    req = group.request
    keywords = req.keywords if req and req.keywords else []
    focus = req.description if req else None
    if slot:
        focus = f"{focus or ''}\n对照槽位：{slot.name}。{slot.description}".strip()
    return {
        "target_app": f"{app_name} vs {JD_APP_NAME}" if app_name else group.baseline_app,
        "target_scenario": req.target_scenario if req else None,
        "keywords": keywords,
        "focus_question": focus,
    }


def _slot_dicts(slots: list[models.ComparisonSlot]) -> list[dict]:
    return [
        {
            "slot_key": slot.slot_key,
            "name": slot.name,
            "description": slot.description,
        }
        for slot in slots
    ]


def _match_status(confidence: float, slot: models.ComparisonSlot | None) -> str:
    if slot and confidence >= HIGH_CONFIDENCE_THRESHOLD:
        return "matched"
    if slot and confidence >= LOW_CONFIDENCE_THRESHOLD:
        return "low_confidence"
    return "unmatched"


async def process_image_for_comparison(image_id: UUID) -> None:
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        image = crud.get_image(db, image_id)
        if not image or not image.task_id or not image.analysis or image.analysis.status not in ("success", "partial"):
            return
        group = crud.get_comparison_group_by_task(db, image.task_id)
        if not group:
            return
        task = image.task or crud.get_task(db, image.task_id)
        app_name = task_app_name(task, group)
        slots = crud.list_comparison_slots(db, group.id)
        if not slots:
            return

        slot_by_key = {slot.slot_key: slot for slot in slots}
        evidence_match = slot_match_from_evidence(get_page_evidence(image.analysis), slots)
        if evidence_match:
            slot = evidence_match["slot"]
            confidence = evidence_match["confidence"]
            reason = f"页面证据匹配: {evidence_match['reason']}"
        else:
            try:
                match_result = await analyzer.match_comparison_slot(
                    image.file_path,
                    _slot_dicts(slots),
                    comparison_context(group, app_name),
                )
                confidence = float(match_result.get("confidence", 0) or 0)
                slot = slot_by_key.get(str(match_result.get("slot_key") or ""))
                reason = str(match_result.get("reason") or "")
            except Exception as exc:
                confidence = 0.0
                slot = None
                reason = f"槽位匹配失败: {exc}"

        status_value = _match_status(confidence, slot)
        match = crud.create_comparison_slot_match(
            db,
            group.id,
            slot.id if slot else None,
            app_name,
            task.id,
            image.id,
            confidence,
            status_value,
            reason,
        )
        if match.status == "matched" and match.slot_id:
            await trigger_pair_analyses(db, group, match.slot)
        reconcile_stale_statuses(db, apply=True, task_ids=[task.id])
    finally:
        db.close()


def _matched_image_for(db: Session, group_id: UUID, slot_id: UUID, app_name: str) -> models.Image | None:
    match = (
        db.query(models.ComparisonSlotMatch)
        .filter(models.ComparisonSlotMatch.comparison_group_id == group_id)
        .filter(models.ComparisonSlotMatch.slot_id == slot_id)
        .filter(models.ComparisonSlotMatch.app_name == app_name)
        .filter(models.ComparisonSlotMatch.status == "matched")
        .order_by(models.ComparisonSlotMatch.created_at.asc())
        .first()
    )
    return match.image if match else None


def _single_analysis_ready(image: models.Image | None) -> bool:
    return bool(image and image.analysis and image.analysis.status in ("success", "partial"))


async def trigger_pair_analyses(db: Session, group: models.ComparisonGroup, slot: models.ComparisonSlot) -> None:
    from app.services.llm_analyzer import analyzer

    jd_image = _matched_image_for(db, group.id, slot.id, JD_APP_NAME)
    if not _single_analysis_ready(jd_image):
        return

    for app in crud.list_comparison_group_apps(db, group.id):
        a_image = _matched_image_for(db, group.id, slot.id, app.app_name)
        if not _single_analysis_ready(a_image):
            continue
        existing = crud.get_comparison_pair_analysis(db, app.id, slot.id)
        if existing:
            continue
        pair = crud.create_comparison_pair_analysis(
            db,
            app.id,
            slot.id,
            a_image.id,
            jd_image.id,
            {},
            status="pending",
        )
        try:
            result = await analyzer.analyze_pair_with_skills(
                a_image.file_path,
                jd_image.file_path,
                group.request.analysis_skill_snapshots_json or [],
                context=comparison_context(group, app.app_name, slot),
            )
            crud.update_comparison_pair_analysis(
                db,
                pair.id,
                custom_analysis_json=result.get("custom_analysis_json") or {},
                status=result.get("status") or "failed",
            )
        except Exception as exc:
            crud.update_comparison_pair_analysis(db, pair.id, status="failed", error=str(exc))


def request_created_by(req: models.Request, fallback_user_id: UUID) -> UUID:
    try:
        return UUID(str(req.user_id))
    except (TypeError, ValueError):
        return fallback_user_id


async def create_comparison_for_request(
    db: Session,
    req: models.Request,
    *,
    mode: str,
    admin_id: str,
    approved_by: UUID,
    planner,
) -> tuple[models.ComparisonGroup, list[models.Task]]:
    config = normalize_comparison_config(req.comparison_config_json)
    existing = crud.get_comparison_group_by_request(db, req.id)
    if existing:
        tasks = [app.task for app in crud.list_comparison_group_apps(db, existing.id) if app.task]
        if existing.jd_task:
            tasks.append(existing.jd_task)
        return existing, tasks

    group = crud.create_comparison_group(
        db,
        request_id=req.id,
        baseline_app=JD_APP_NAME,
        jd_instruction=config["jd_instruction"],
        status="pending",
    )
    for index, slot in enumerate(config["slots"]):
        crud.create_comparison_slot(
            db,
            group.id,
            slot["slot_key"],
            slot["name"],
            slot["description"],
            bool(slot.get("required", True)),
            index,
        )

    created_by = request_created_by(req, approved_by)
    keywords = req.keywords or []
    tasks: list[models.Task] = []
    for app_name in config["a_apps"]:
        app_description = description_for_app(req.description, app_name)
        target_goals = build_target_goals(app_name, req.target_scenario, keywords, app_description)
        generated_instruction = await planner(
            target_app=app_name,
            target_scenario=req.target_scenario,
            keywords=keywords,
            description=app_description,
        )
        generated_instruction = append_target_goal_checklist(generated_instruction, target_goals)
        task = crud.create_task(
            db,
            name=f"{app_name} vs JD from request {req.id}",
            keyword=keywords[0] if keywords else "",
            target_app=app_name,
            target_scenario=req.target_scenario,
            request_id=req.id,
            admin_id=admin_id,
            mode=mode,
            created_by=created_by,
            approved_by=approved_by,
            target_goals_json=target_goals,
            analysis_skill_snapshots=req.analysis_skill_snapshots_json or [],
        )
        crud.update_task_instruction(db, task.id, generated_instruction)
        task = crud.get_task(db, task.id)
        crud.create_comparison_group_app(db, group.id, app_name, task.id)
        tasks.append(task)

    jd_goals = build_target_goals(JD_APP_NAME, req.target_scenario, keywords, req.description)
    jd_instruction = append_target_goal_checklist(_strip_manual_capture_instruction(config["jd_instruction"]), jd_goals)
    jd_task = crud.create_task(
        db,
        name=f"JD comparison from request {req.id}",
        keyword=keywords[0] if keywords else "",
        target_app=JD_APP_NAME,
        target_scenario=req.target_scenario,
        request_id=req.id,
        admin_id=admin_id,
        mode=mode,
        created_by=created_by,
        approved_by=approved_by,
        target_goals_json=jd_goals,
        analysis_skill_snapshots=req.analysis_skill_snapshots_json or [],
    )
    crud.update_task_instruction(db, jd_task.id, jd_instruction)
    jd_task = crud.get_task(db, jd_task.id)
    crud.update_comparison_group_jd_task(db, group.id, jd_task.id, status="running")
    tasks.append(jd_task)
    return crud.get_comparison_group_by_request(db, req.id), tasks
