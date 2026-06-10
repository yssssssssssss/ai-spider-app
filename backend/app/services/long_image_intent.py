import re
import json
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI
from app.config import settings


KNOWN_APPS = ("淘宝", "天猫", "拼多多", "京东")
LONG_IMAGE_MARKERS = ("长图", "长截图", "拼长图", "滚动截图", "全页截图", "整页截图", "多屏", "多页")
COUNTED_CAPTURE_PATTERN = re.compile(r"(?:截取|截屏|截图|滚动|采集)?\s*\d{1,2}\s*(?:屏|页|张)")
PRODUCT_DETAIL_MARKERS = ("商详", "商品详情", "商品页")
POST_CAPTURE_TERMS = ("逐屏截图", "拼接", "拼长图", "裁切", "重复区域", "长图")
DEFAULT_EXCLUDE_ENTRY_TYPES = ["live", "ad", "customer_service"]


@dataclass
class LongImageIntent:
    intent: str
    confidence: float
    scene_type: str
    apps: list[str] = field(default_factory=list)
    keyword: str = ""
    capture_count: int = 10
    selection_rule: str = "first_normal_product"
    exclude_entry_types: list[str] = field(default_factory=lambda: DEFAULT_EXCLUDE_ENTRY_TYPES.copy())
    dedupe_overlap: bool = True
    stitch: bool = True
    keep_raw_images: bool = True
    missing_fields: list[str] = field(default_factory=list)


def _text_from_parts(*parts: Any) -> str:
    return " ".join(str(part or "") for part in parts)


def _extract_apps(text: str) -> list[str]:
    return [app for app in KNOWN_APPS if app in text]


def _extract_keyword(text: str) -> str:
    quoted = re.search(r"搜索[“\"'‘]([^”\"'’，。,\n]+)[”\"'’]", text)
    if quoted:
        return quoted.group(1).strip()
    plain = re.search(r"搜索\s*([^，。,\n]+?)(?:，|。|,|\n|然后|点击|进入|针对|并|$)", text)
    if plain:
        return plain.group(1).strip(" “”\"'‘’")
    return ""


def _extract_capture_count(text: str) -> int:
    match = re.search(r"(\d{1,2})\s*(?:屏|页|张)", text)
    if not match:
        return 10
    return max(1, min(int(match.group(1)), 30))


def _scene_type(text: str) -> str:
    if any(marker in text for marker in PRODUCT_DETAIL_MARKERS):
        return "product_detail"
    return "custom_page"


def is_long_image_candidate(*parts: Any) -> bool:
    text = _text_from_parts(*parts)
    return any(marker in text for marker in LONG_IMAGE_MARKERS) or bool(COUNTED_CAPTURE_PATTERN.search(text))


def parse_long_image_intent(text: str) -> LongImageIntent:
    apps = _extract_apps(text)
    keyword = _extract_keyword(text)
    scene_type = _scene_type(text)
    missing_fields: list[str] = []
    if not apps:
        missing_fields.append("apps")
    if scene_type == "product_detail" and not keyword:
        missing_fields.append("keyword")

    return LongImageIntent(
        intent="long_image_capture" if is_long_image_candidate(text) else "unknown",
        confidence=0.92 if is_long_image_candidate(text) else 0.0,
        scene_type=scene_type,
        apps=apps,
        keyword=keyword,
        capture_count=_extract_capture_count(text),
        missing_fields=missing_fields,
    )


def _model_client() -> tuple[OpenAI, str] | None:
    if settings.VLM_API_KEY:
        return OpenAI(api_key=settings.VLM_API_KEY, base_url=settings.VLM_BASE_URL), settings.VLM_MODEL
    if settings.OPENAI_API_KEY:
        return OpenAI(api_key=settings.OPENAI_API_KEY, base_url=settings.OPENAI_BASE_URL), settings.VLM_MODEL
    if settings.PHONE_AGENT_API_KEY and settings.PHONE_AGENT_BASE_URL and settings.PHONE_AGENT_MODEL:
        return OpenAI(api_key=settings.PHONE_AGENT_API_KEY, base_url=settings.PHONE_AGENT_BASE_URL), settings.PHONE_AGENT_MODEL
    return None


def _intent_from_payload(payload: dict[str, Any], fallback: LongImageIntent) -> LongImageIntent:
    apps = [str(app).strip() for app in payload.get("apps", []) if str(app).strip()]
    apps = [app for app in apps if app in KNOWN_APPS]
    if not apps:
        apps = fallback.apps
    keyword = str(payload.get("keyword") or fallback.keyword).strip()
    scene_type = str(payload.get("scene_type") or fallback.scene_type).strip() or "custom_page"
    capture_count = payload.get("capture_count", fallback.capture_count)
    try:
        capture_count = max(1, min(int(capture_count), 30))
    except (TypeError, ValueError):
        capture_count = fallback.capture_count
    missing_fields: list[str] = []
    if not apps:
        missing_fields.append("apps")
    if scene_type == "product_detail" and not keyword:
        missing_fields.append("keyword")
    return LongImageIntent(
        intent=str(payload.get("intent") or fallback.intent),
        confidence=float(payload.get("confidence") or fallback.confidence),
        scene_type=scene_type,
        apps=apps,
        keyword=keyword,
        capture_count=capture_count,
        selection_rule=str(payload.get("selection_rule") or fallback.selection_rule),
        exclude_entry_types=payload.get("exclude_entry_types") or fallback.exclude_entry_types,
        dedupe_overlap=bool(payload.get("dedupe_overlap", fallback.dedupe_overlap)),
        stitch=bool(payload.get("stitch", fallback.stitch)),
        keep_raw_images=bool(payload.get("keep_raw_images", fallback.keep_raw_images)),
        missing_fields=missing_fields,
    )


def parse_long_image_intent_with_llm(text: str) -> LongImageIntent:
    fallback = parse_long_image_intent(text)
    client_config = _model_client()
    if not client_config:
        return fallback

    client, model = client_config
    system_prompt = """你是移动端自动化任务意图解析器。将用户输入解析为严格 JSON，不要输出解释。
JSON 字段：
intent: long_image_capture 或 unknown
confidence: 0到1
scene_type: product_detail/search_results/activity_page/shop_home/custom_page
apps: 平台数组，仅允许 淘宝、天猫、拼多多、京东
keyword: 搜索词，没有则空字符串
capture_count: 1到30的整数，未说明默认10
selection_rule: first_normal_product 或 target_page
exclude_entry_types: 可包含 live、ad、customer_service、video
dedupe_overlap: boolean
stitch: boolean
keep_raw_images: boolean
missing_fields: 缺失字段数组"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
            temperature=0,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        return _intent_from_payload(payload, fallback)
    except Exception as exc:
        print(f"⚠️ 长图意图 LLM 解析失败，回退到本地解析: {exc}")
        return fallback


def _task_text(task: Any, prompt: str | None) -> str:
    request = getattr(task, "request", None)
    return _text_from_parts(
        getattr(task, "target_app", ""),
        getattr(task, "keyword", ""),
        getattr(task, "target_scenario", ""),
        getattr(task, "generated_instruction", ""),
        getattr(request, "description", "") if request else "",
        prompt or "",
    )


def _task_app(task: Any, intent: LongImageIntent) -> str:
    app = str(getattr(task, "target_app", "") or "").strip()
    if app:
        return app
    return intent.apps[0] if intent.apps else "目标"


def _task_keyword(task: Any, intent: LongImageIntent) -> str:
    keyword = str(getattr(task, "keyword", "") or "").strip()
    if keyword:
        return keyword
    return intent.keyword


def _task_scenario(task: Any) -> str:
    scenario = str(getattr(task, "target_scenario", "") or "").strip()
    scenario = re.sub(r"(?:滚动|截取|截屏|截图|采集)?\s*\d{1,2}\s*(?:屏|页|张)", "", scenario)
    for term in POST_CAPTURE_TERMS:
        scenario = scenario.replace(term, "")
    scenario = re.sub(r"(?:并|和|及)+$", "", scenario.strip(" ，。,.；;"))
    return scenario or "目标页面"


def build_long_image_navigation_prompt(task: Any, prompt: str | None = None) -> str:
    intent = parse_long_image_intent(_task_text(task, prompt))
    app = _task_app(task, intent)
    keyword = _task_keyword(task, intent)

    if intent.scene_type == "product_detail":
        keyword_part = f"，在搜索框输入“{keyword}”后点击“搜索”按钮" if keyword else ""
        return (
            f"打开{app}App{keyword_part}，点击搜索结果中的第一个普通商品，"
            "避开直播、广告、客服入口，进入商品详情页首屏后立即结束。"
            "不要滚动，不要打开其他应用。"
        )

    scenario = _task_scenario(task)
    keyword_part = f"，在搜索框输入“{keyword}”后点击“搜索”按钮" if keyword else ""
    return f"打开{app}App{keyword_part}，进入{scenario}首屏后立即结束。不要滚动，不要打开其他应用。"
