import json
import re
from typing import Any

from fastapi import HTTPException, status

from app.services.jd_comparison import enrich_interpret_result
from app.services.task_planner import _planner_client, planner_chat_completion_options


MAX_NATURAL_LANGUAGE_LENGTH = 4000
KNOWN_APPS = ("淘宝", "拼多多", "京东", "天猫", "抖音", "小红书", "快手", "美团", "得物")
KNOWN_KEYWORDS = ("百亿补贴", "百亿会场", "618", "双11", "双十一", "红包", "新人价", "新人券")
SPLIT_PATTERN = re.compile(r"\s*(?:,|，|、|;|；|/|\n|和|以及)\s*")
SCENE_PATTERN = re.compile(r"(?:进入|打开|访问|查看|找到|截取|采集)?([^，。；;,.、\n]{2,30}?(?:会场|页面|页|弹窗|频道|入口|详情页))")


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" ,，。;；")


def _normalize_keywords(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = [str(item) for item in value]
    elif isinstance(value, str):
        raw = [part for part in SPLIT_PATTERN.split(value) if part]
    else:
        raw = []
    seen: set[str] = set()
    keywords: list[str] = []
    for item in raw:
        keyword = _clean_text(item)
        if keyword and keyword not in seen:
            seen.add(keyword)
            keywords.append(keyword)
    return keywords[:12]


def _extract_json_object(text: str) -> dict[str, Any] | None:
    content = (text or "").strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?", "", content).strip()
        content = re.sub(r"```$", "", content).strip()
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        parsed = json.loads(content[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _normalize_result(parsed: dict[str, Any], natural_language: str) -> dict[str, Any]:
    normalized = {
        "target_app": _clean_text(parsed.get("target_app")),
        "target_scenario": _clean_text(parsed.get("target_scenario")),
        "keywords": _normalize_keywords(parsed.get("keywords")),
        "description": _clean_text(parsed.get("description")) or natural_language,
    }
    if isinstance(parsed.get("a_apps"), list):
        normalized["a_apps"] = [_clean_text(item) for item in parsed.get("a_apps") if _clean_text(item)]
    if isinstance(parsed.get("comparison_slots"), list):
        normalized["comparison_slots"] = parsed.get("comparison_slots")
    if parsed.get("jd_instruction"):
        normalized["jd_instruction"] = _clean_text(parsed.get("jd_instruction"))
    return normalized


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _extract_scene_terms(natural_language: str) -> list[str]:
    terms: list[str] = []
    if "百亿补贴" in natural_language:
        _append_unique(terms, "百亿补贴会场")
    if "百亿会场" in natural_language:
        _append_unique(terms, "百亿会场")
    for match in SCENE_PATTERN.finditer(natural_language):
        term = _clean_text(match.group(1)).removesuffix("截图").removesuffix("截屏")
        if term in KNOWN_APPS:
            continue
        if any(term.endswith(app) for app in KNOWN_APPS):
            continue
        _append_unique(terms, term)
    return terms[:6]


def _scene_for_apps(apps: list[str], scene_terms: list[str]) -> str:
    if not scene_terms:
        return ""
    if not apps:
        return "、".join(scene_terms)
    first_scene = scene_terms[0]
    return "、".join(
        scene if scene.startswith(app) else f"{app}{first_scene}"
        for app in apps
        for scene in [first_scene]
    )


def _fallback_interpret(natural_language: str) -> dict[str, Any]:
    apps = [app for app in KNOWN_APPS if app in natural_language]
    keywords = [keyword for keyword in KNOWN_KEYWORDS if keyword in natural_language]
    scene_terms = _extract_scene_terms(natural_language)
    for term in scene_terms:
        _append_unique(keywords, term)
    scene = _scene_for_apps(apps, scene_terms)
    return {
        "target_app": "、".join(apps),
        "target_scenario": scene,
        "keywords": keywords,
        "description": natural_language,
    }


def _merge_with_fallback(normalized: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    keywords = list(normalized.get("keywords") or fallback.get("keywords") or [])
    merged = {
        "target_app": normalized.get("target_app") or fallback.get("target_app") or "",
        "target_scenario": normalized.get("target_scenario") or fallback.get("target_scenario") or "",
        "keywords": keywords[:12],
        "description": normalized.get("description") or fallback.get("description") or "",
    }
    for field in ("a_apps", "comparison_slots", "jd_instruction"):
        if normalized.get(field):
            merged[field] = normalized[field]
        elif fallback.get(field):
            merged[field] = fallback[field]
    return enrich_interpret_result(merged)


async def interpret_request_text(natural_language: str) -> dict[str, Any]:
    text = (natural_language or "").strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Natural language requirement is required")
    if len(text) > MAX_NATURAL_LANGUAGE_LENGTH:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Natural language requirement is too long")

    system_prompt = """你是竞品截图采集需求的结构化转译器。请把用户的自然语言需求转换成现有表单字段，只输出JSON对象，不要解释。
JSON字段：
{
  "target_app": "目标App，多个App用、连接",
  "target_scenario": "目标场景，多个App/多个目标时写成清晰的目标清单，用、连接",
  "keywords": ["用于搜索、识别或关注的关键词"],
  "description": "给自动化执行和截图分析看的补充说明，必须保留用户要求的执行顺序、必须截图的目标和限制条件",
  "a_apps": ["用于和京东对照的A侧App，不要包含京东"],
  "comparison_slots": [
    {"slot_key": "稳定英文短key", "name": "对照槽位名称", "description": "如何判断截图命中该槽位", "required": true}
  ],
  "jd_instruction": "在京东App上执行等价操作的自然语言指令，结尾必须要求截图保存到本地"
}
规则：
1. 不要编造用户没有提到的App、会场、关键词。
2. 多个App要保留为多个目标，不要压缩成一个模糊目标。
3. 如果用户要求分别截图，description必须明确每个目标都要完成。
4. target_scenario应优先描述要进入的页面/会场/弹窗/详情页。
5. keywords只放短词，不要放长句。
6. comparison_slots只描述本次任务需要逐张对比的目标画面，数量1到5个。
7. jd_instruction允许用京东上的等价入口或等价活动，不要只机械替换App名。"""

    try:
        client, model = _planner_client()
        response = client.chat.completions.create(
            **planner_chat_completion_options(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                temperature=0.1,
                max_tokens=512,
            ),
        )
        content = response.choices[0].message.content or ""
        parsed = _extract_json_object(content)
        if parsed:
            normalized = _normalize_result(parsed, text)
            merged = _merge_with_fallback(normalized, _fallback_interpret(text))
            if merged["target_app"] or merged["target_scenario"] or merged["keywords"]:
                return merged
    except Exception as exc:
        print(f"⚠️ 自然语言需求转译失败，回退到规则解析: {exc}")
    return enrich_interpret_result(_fallback_interpret(text), text)
