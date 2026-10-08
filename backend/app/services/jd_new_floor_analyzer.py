from __future__ import annotations

import asyncio
import base64
import json
import math
import re
from dataclasses import asdict, dataclass
from io import BytesIO
from typing import Any, Protocol

from PIL import Image, UnidentifiedImageError

from app.services.llm_analyzer import MAX_VLM_IMAGE_SIDE, analyzer


X_REGION_PROMPT = """你是京东 App“新品”频道 X 区域楼层视觉检查器。第1张图片是原始全屏截图，第2张图片是原图 X 区域裁图。
请只依据图片中的可见内容返回一个 JSON 对象，不要 Markdown，也不要给总体合规结论：
{
  "navigation_bar_above": {"present": true, "bbox_full_norm": [x1,y1,x2,y2], "evidence": ""},
  "tab_bar_below": {"present": true, "bbox_full_norm": [x1,y1,x2,y2], "evidence": ""},
  "floor": {"type": "combination|one_row_one_hit|uncertain", "bbox_norm": [x1,y1,x2,y2], "evidence": ""},
  "cover_title_floor": {
    "cover_image_present": true,
    "primary_focus_title_present": true,
    "bbox_norm": [x1,y1,x2,y2],
    "evidence": ""
  },
  "following_four_product_floor": {
    "present": true,
    "immediately_below_x": true,
    "bbox_full_norm": [x1,y1,x2,y2],
    "evidence": ""
  },
  "right_side": {
    "entry_count": 3,
    "entries_vertical": true,
    "bbox_norm": [x1,y1,x2,y2],
    "evidence": "",
    "entries": [
      {
        "bbox_norm": [x1,y1,x2,y2],
        "tag_bar_present": true,
        "tag_text": "标签文字",
        "product_thumbnail_present": true,
        "product_name_present": true,
        "product_name_single_line": true,
        "price_row_present": true,
        "main_price_present": true,
        "cta_present": true,
        "cta_text": "抢"
      }
    ]
  },
  "superstar_benefits": {
    "title_present": true,
    "title_bbox_norm": [x1,y1,x2,y2],
    "star_module_count": 2,
    "star_modules_vertical": true,
    "star_modules": [{"bbox_norm": [x1,y1,x2,y2]}],
    "refresh_button_present": true,
    "refresh_button_bbox_norm": [x1,y1,x2,y2],
    "other_section_present": false,
    "other_section_bbox_norm": null,
    "evidence": ""
  }
}
用第1张全屏图判断 X 区域上方是否是导航栏、下方是否是 Tab 栏；这两个 bbox_full_norm 相对第1张全屏图。
用第2张裁图判断楼层类型、X 区域是否同时具有封面图和首焦栏目标题、右侧入口及超级明星福利；这些 bbox_norm 均相对第2张 X 区域裁图。
following_four_product_floor 仅判断 X 区域下方是否紧接着出现“一行4个商品”楼层：present 表示该楼层存在，immediately_below_x 表示它与 X 区域直接相邻、没有其他楼层或模块插入；bbox_full_norm 相对第1张全屏图。
right_side.entry_count 是 X 区域右侧入口数，entries 按从上到下顺序逐个报告。
superstar_benefits.title_present 仅判断 X 区域内是否出现“超级明星福利”标题；若出现，再描述该区域，其中 other_section_present 表示明星福利区域内部是否混入爆品等其他栏目。
所有归一化坐标均使用0到1000；看不清时布尔值返回null、数量返回null、type返回uncertain、bbox返回null。"""


Y_REGION_PROMPT = """你是京东 App“新品”频道 Y 区域首焦组件视觉检查器。当前图片仅包含原图的 Y 区域。
请只依据图片中的可见内容返回一个 JSON 对象，不要 Markdown，也不要给总体合规结论：
{
  "cover_image": {"present": true, "bbox_norm": [x1,y1,x2,y2], "evidence": ""},
  "gradient_overlay": {"present": true, "supports_white_text": true, "bbox_norm": [x1,y1,x2,y2], "evidence": ""},
  "primary_focus_title": {"present": true, "bbox_norm": [x1,y1,x2,y2], "evidence": ""},
  "bottom_info_container": {"present": true, "bbox_norm": [x1,y1,x2,y2], "evidence": ""},
  "subtitle": {"present": true, "text": "小标题文字", "icon_present": true, "bbox_norm": [x1,y1,x2,y2], "evidence": ""},
  "benefit": {"present": true, "presentation": "arrow|button|image|none|uncertain", "bbox_norm": [x1,y1,x2,y2], "evidence": ""}
}
subtitle 与 benefit 不要求同时出现，缺失其中一项不算问题，但底部信息容器内至少要出现一项；若两项都出现，则两项都必须分别满足各自规范。
subtitle 只指底部信息容器内的小标题；封面顶部或角落的角标、标签（例如“新发布+”）不是小标题，此时 subtitle.present 必须返回false，不得返回其bbox。subtitle的icon是可选观察项。
supports_white_text 表示渐变蒙层是否足以承托白色标题和利益点，避免浅色遮罩造成不可读。各组件bbox需精确圈定，系统会据此校验渐变蒙层位于封面图底部，以及标题和利益点是否处于蒙层承托范围。
所有bbox都相对当前Y区域裁图，使用0到1000的坐标；无法确认时布尔值返回null、bbox返回null。"""


ALLOWED_STATUSES = {"pass", "fail", "not_applicable", "uncertain"}
X_REGION_TOP = 510
X_REGION_BOTTOM = 1090
Y_REGION_RIGHT = 540
REGION_HEIGHT = X_REGION_BOTTOM - X_REGION_TOP
Y_REGION_BOX = (0, X_REGION_TOP, Y_REGION_RIGHT, X_REGION_BOTTOM)
REGION_ANALYSIS_ATTEMPTS = 2
REGION_ANALYSIS_MAX_TOKENS = 4096


class ImageCompletion(Protocol):
    providers: list

    async def complete_images(
        self,
        prompt: str,
        images: list[str],
        preferred_provider: str | None = None,
        max_tokens: int = 2048,
    ) -> str: ...


@dataclass(frozen=True)
class JdNewFloorAnalysis:
    report_type: str
    schema_version: int
    capture: dict[str, Any]
    regions: dict[str, dict[str, Any]]
    checks: dict[str, dict[str, Any]]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JdNewFloorAnalyzer:
    """Analyze the fixed JD New floor regions and derive compliance server-side."""

    def __init__(self, image_completion: ImageCompletion = analyzer):
        self.image_completion = image_completion

    async def analyze_png(self, content: bytes) -> JdNewFloorAnalysis:
        full_image, x_image, y_image, width, height = self._prepare_crops(content)
        if not getattr(self.image_completion, "providers", []):
            raise RuntimeError("No image-capable LLM provider configured")

        # Each prompt and every normalized bbox belongs to one crop only. Retry an
        # empty or malformed model response once; providers can occasionally
        # return an empty content field after spending the token budget on reasoning.
        x_payload, y_payload = await asyncio.gather(
            self._analyze_region(
                X_REGION_PROMPT,
                [full_image, x_image],
                "x",
            ),
            self._analyze_region(
                Y_REGION_PROMPT,
                [y_image],
                "y",
            ),
        )

        regions = {
            "x": {
                "label": "x区域",
                "bbox_px": [0, X_REGION_TOP, width, X_REGION_BOTTOM],
                "width_px": width,
                "height_px": REGION_HEIGHT,
            },
            "y": {
                "label": "y区域",
                "bbox_px": list(Y_REGION_BOX),
                "width_px": Y_REGION_RIGHT,
                "height_px": REGION_HEIGHT,
            },
        }
        checks = self._build_checks(x_payload, y_payload, regions, [0, 0, width, height])
        return JdNewFloorAnalysis(
            report_type="jd_new_floor_audit",
            schema_version=1,
            capture={"format": "PNG", "width": width, "height": height},
            regions=regions,
            checks=checks,
            summary=self._summarize(checks),
        )

    async def _analyze_region(self, prompt: str, images: list[str], region: str) -> dict[str, Any]:
        for attempt in range(REGION_ANALYSIS_ATTEMPTS):
            response = await self.image_completion.complete_images(
                prompt,
                images,
                preferred_provider="openai",
                max_tokens=REGION_ANALYSIS_MAX_TOKENS,
            )
            try:
                return self._parse_json(response, region)
            except ValueError:
                if attempt + 1 == REGION_ANALYSIS_ATTEMPTS:
                    raise
        raise AssertionError("unreachable")

    def _prepare_crops(self, content: bytes) -> tuple[str, str, str, int, int]:
        if not content:
            raise ValueError("Image content is empty")
        try:
            with Image.open(BytesIO(content)) as image:
                if image.format != "PNG":
                    raise ValueError("Image content must be PNG")
                image.load()
                width, height = image.size
                if width < Y_REGION_RIGHT or height < X_REGION_BOTTOM:
                    raise ValueError(
                        f"Image must be at least {Y_REGION_RIGHT}x{X_REGION_BOTTOM} pixels"
                    )
                rgb = image.convert("RGB")
                full_image = self._encode_image(rgb)
                x_image = self._encode_image(
                    rgb.crop((0, X_REGION_TOP, width, X_REGION_BOTTOM))
                )
                y_image = self._encode_image(rgb.crop(Y_REGION_BOX))
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("Unsupported image content") from exc
        return full_image, x_image, y_image, width, height

    def _encode_image(self, image: Image.Image) -> str:
        if max(image.size) > MAX_VLM_IMAGE_SIDE:
            ratio = MAX_VLM_IMAGE_SIDE / max(image.size)
            image = image.resize(
                (max(1, round(image.width * ratio)), max(1, round(image.height * ratio))),
                Image.Resampling.LANCZOS,
            )
        buffer = BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def _parse_json(self, text: str, region: str) -> dict[str, Any]:
        candidate = text.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", candidate, re.DOTALL | re.IGNORECASE)
        if fenced:
            candidate = fenced.group(1)
        else:
            start, end = candidate.find("{"), candidate.rfind("}")
            if start >= 0 and end > start:
                candidate = candidate[start : end + 1]
        try:
            payload = json.loads(candidate)
        except (json.JSONDecodeError, TypeError, AttributeError) as exc:
            raise ValueError(f"JD new floor analyzer returned invalid JSON for {region} region") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"JD new floor analyzer result for {region} region must be an object")
        return payload

    def _build_checks(
        self,
        x_payload: dict[str, Any],
        y_payload: dict[str, Any],
        regions: dict[str, dict[str, Any]],
        full_box: list[int],
    ) -> dict[str, dict[str, Any]]:
        x_box = regions["x"]["bbox_px"]
        y_box = regions["y"]["bbox_px"]
        checks: dict[str, dict[str, Any]] = {}

        navigation = self._object(x_payload.get("navigation_bar_above"))
        tab_bar = self._object(x_payload.get("tab_bar_below"))
        navigation_present = self._optional_bool(navigation.get("present"))
        tab_present = self._optional_bool(tab_bar.get("present"))
        navigation_bbox_available = (
            self._bbox_available(navigation.get("bbox_full_norm")) if navigation_present is True else None
        )
        tab_bbox_available = self._bbox_available(tab_bar.get("bbox_full_norm")) if tab_present is True else None
        status_facts = [navigation_present, tab_present]
        if navigation_present is True:
            status_facts.append(navigation_bbox_available)
        if tab_present is True:
            status_facts.append(tab_bbox_available)
        status = self._required_status(status_facts)
        conclusion = self._presence_conclusion(navigation_present, tab_present)
        if status == "uncertain" and navigation_present is True and tab_present is True:
            conclusion = "已识别导航栏和Tab栏，但缺少完整标注坐标"
        checks["3.3"] = self._check(
            "3.3",
            "x区域上下栏位",
            "x",
            status,
            conclusion,
            {
                "navigation_bar_above": navigation_present,
                "tab_bar_below": tab_present,
                "navigation_annotation_available": navigation_bbox_available,
                "tab_annotation_available": tab_bbox_available,
                "navigation_evidence": self._text(navigation.get("evidence")),
                "tab_evidence": self._text(tab_bar.get("evidence")),
            },
            self._annotations(
                (
                    "导航栏",
                    navigation.get("bbox_full_norm") if navigation_present is True else None,
                    full_box,
                ),
                (
                    "Tab栏",
                    tab_bar.get("bbox_full_norm") if tab_present is True else None,
                    full_box,
                ),
            ),
        )

        floor = self._object(x_payload.get("floor"))
        floor_type = self._floor_type(floor.get("type"))
        floor_status = "pass" if floor_type != "uncertain" else "uncertain"
        floor_names = {
            "combination": "组合型楼层",
            "one_row_one_hit": "一行一爆品楼层",
            "uncertain": "无法确认楼层类型",
        }
        checks["3.4"] = self._check(
            "3.4",
            "x区域楼层类型",
            "x",
            floor_status,
            floor_names[floor_type],
            {"floor_type": floor_type, "evidence": self._text(floor.get("evidence"))},
            self._annotations((floor_names[floor_type], floor.get("bbox_norm"), x_box)),
        )

        cover = self._object(y_payload.get("cover_image"))
        overlay = self._object(y_payload.get("gradient_overlay"))
        focus_title = self._object(y_payload.get("primary_focus_title"))
        info = self._object(y_payload.get("bottom_info_container"))
        subtitle = self._object(y_payload.get("subtitle"))
        benefit = self._object(y_payload.get("benefit"))
        cover_present = self._present(cover)
        overlay_present = self._present(overlay)
        focus_title_present = self._present(focus_title)
        info_present = self._present(info)
        subtitle_reported_present = self._present(subtitle)
        reported_subtitle_text = self._text_or_none(subtitle.get("text"))
        subtitle_rejected_as_badge = (
            subtitle_reported_present is True and self._is_subtitle_badge(reported_subtitle_text)
        )
        subtitle_present = False if subtitle_rejected_as_badge else subtitle_reported_present
        subtitle_text = reported_subtitle_text if subtitle_present is True else None
        benefit_present = self._present(benefit)
        benefit_presentation = self._benefit_presentation(benefit.get("presentation"))
        subtitle_inside_info = (
            self._bbox_contains(info.get("bbox_norm"), subtitle.get("bbox_norm"))
            if info_present is True and subtitle_present is True
            else None
        )
        benefit_inside_info = (
            self._bbox_contains(info.get("bbox_norm"), benefit.get("bbox_norm"))
            if info_present is True and benefit_present is True
            else None
        )
        overlay_at_cover_bottom = (
            self._bbox_at_bottom(cover.get("bbox_norm"), overlay.get("bbox_norm"))
            if cover_present is True and overlay_present is True
            else None
        )
        title_supported_by_overlay = (
            self._bbox_contains(overlay.get("bbox_norm"), focus_title.get("bbox_norm"))
            if overlay_present is True and focus_title_present is True
            else None
        )
        benefit_supported_by_overlay = (
            self._bbox_contains(overlay.get("bbox_norm"), benefit.get("bbox_norm"))
            if overlay_present is True and benefit_present is True
            else None
        )
        benefit_presentation_valid = (
            benefit_presentation in {"arrow", "button", "image"}
            if benefit_presentation != "uncertain"
            else None
        )
        subtitle_valid = self._valid_optional_component(
            subtitle_present,
            [subtitle_inside_info],
        )
        benefit_valid = self._valid_optional_component(
            benefit_present,
            [
                benefit_presentation_valid,
                benefit_inside_info,
                benefit_supported_by_overlay,
            ],
        )
        bottom_info_content_present = self._at_least_one_true(
            [subtitle_present, benefit_present]
        )
        subtitle_valid_when_present = (
            True if subtitle_present is False else subtitle_valid
        )
        benefit_valid_when_present = True if benefit_present is False else benefit_valid
        components = {
            "cover_image_present": cover_present,
            "gradient_overlay_present": overlay_present,
            "overlay_supports_white_text": self._optional_bool(overlay.get("supports_white_text")),
            "overlay_at_cover_bottom": overlay_at_cover_bottom,
            "primary_focus_title_present": focus_title_present,
            "primary_focus_title_supported_by_overlay": title_supported_by_overlay,
            "bottom_info_container_present": info_present,
            "subtitle_present": subtitle_present,
            "subtitle_text": subtitle_text,
            "subtitle_icon_present": (
                self._optional_bool(subtitle.get("icon_present"))
                if subtitle_present is True
                else None
            ),
            "subtitle_inside_bottom_info_container": subtitle_inside_info,
            "subtitle_rejected_as_badge": subtitle_rejected_as_badge,
            "subtitle_valid": subtitle_valid,
            "benefit_present": benefit_present,
            "benefit_presentation": benefit_presentation,
            "benefit_presentation_valid": benefit_presentation_valid,
            "benefit_inside_bottom_info_container": benefit_inside_info,
            "benefit_supported_by_overlay": benefit_supported_by_overlay,
            "benefit_valid": benefit_valid,
            "bottom_info_has_subtitle_or_benefit": bottom_info_content_present,
            "subtitle_valid_when_present": subtitle_valid_when_present,
            "benefit_valid_when_present": benefit_valid_when_present,
        }
        component_status = self._required_status(
            [
                components["cover_image_present"],
                components["gradient_overlay_present"],
                components["overlay_supports_white_text"],
                components["overlay_at_cover_bottom"],
                components["primary_focus_title_present"],
                components["primary_focus_title_supported_by_overlay"],
                components["bottom_info_container_present"],
                components["bottom_info_has_subtitle_or_benefit"],
                components["subtitle_valid_when_present"],
                components["benefit_valid_when_present"],
            ]
        )
        checks["3.5"] = self._check(
            "3.5",
            "y区域首焦组件规范",
            "y",
            component_status,
            self._component_conclusion(component_status, components),
            components,
            self._annotations(
                ("封面图", cover.get("bbox_norm") if cover_present is True else None, y_box),
                (
                    "渐变蒙层",
                    overlay.get("bbox_norm") if overlay_present is True else None,
                    y_box,
                ),
                (
                    "首焦栏目标题",
                    focus_title.get("bbox_norm") if focus_title_present is True else None,
                    y_box,
                ),
                (
                    "底部信息容器",
                    info.get("bbox_norm") if info_present is True else None,
                    y_box,
                ),
                (
                    "小标题",
                    subtitle.get("bbox_norm") if subtitle_present is True else None,
                    y_box,
                ),
                (
                    "利益点",
                    benefit.get("bbox_norm") if benefit_present is True else None,
                    y_box,
                ),
            ),
        )

        cover_title_floor = self._object(x_payload.get("cover_title_floor"))
        cover_in_x = self._optional_bool(cover_title_floor.get("cover_image_present"))
        title_in_x = self._optional_bool(cover_title_floor.get("primary_focus_title_present"))
        condition_1 = self._and_optional([cover_in_x, title_in_x])
        condition_1_bbox = (
            self._bbox_available(cover_title_floor.get("bbox_norm"))
            if condition_1 is True
            else None
        )

        following_floor = self._object(x_payload.get("following_four_product_floor"))
        following_present = self._optional_bool(following_floor.get("present"))
        immediately_below = self._optional_bool(following_floor.get("immediately_below_x"))
        condition_2 = self._and_optional([following_present, immediately_below])
        condition_2_bbox = (
            self._bbox_available(following_floor.get("bbox_full_norm"))
            if condition_2 is True
            else None
        )

        if condition_1 is None or (condition_1 is True and condition_1_bbox is not True):
            format_status = "uncertain"
            format_conclusion = "待确认"
        elif condition_1 is False:
            format_status = "fail"
            format_conclusion = "格式错误"
        elif condition_2 is None or (condition_2 is True and condition_2_bbox is not True):
            format_status = "uncertain"
            format_conclusion = "待确认"
        elif condition_2 is True:
            format_status = "fail"
            format_conclusion = "格式错误"
        else:
            format_status = "pass"
            format_conclusion = "格式正确"

        checks["3.6"] = self._check(
            "3.6",
            "X区域楼层衔接格式",
            "x",
            format_status,
            format_conclusion,
            {
                "condition_1_cover_title_floor": condition_1,
                "condition_2_four_product_floor_immediately_below": condition_2,
                "cover_image_present_in_x": cover_in_x,
                "primary_focus_title_present_in_x": title_in_x,
                "cover_title_floor_annotation_available": condition_1_bbox,
                "following_four_product_floor_present": following_present,
                "following_floor_immediately_below_x": immediately_below,
                "four_product_floor_annotation_available": condition_2_bbox,
                "condition_1_evidence": self._text(cover_title_floor.get("evidence")),
                "condition_2_evidence": self._text(following_floor.get("evidence")),
            },
            self._annotations(
                (
                    "X区域封面图+首焦栏目标题",
                    cover_title_floor.get("bbox_norm") if condition_1 is True else None,
                    x_box,
                ),
                (
                    "X区域下方紧接一行4个商品楼层",
                    following_floor.get("bbox_full_norm") if condition_2 is True else None,
                    full_box,
                ),
            ),
        )

        right_side = self._object(x_payload.get("right_side"))
        entries = right_side.get("entries") if isinstance(right_side.get("entries"), list) else []
        entry_count = self._optional_count(right_side.get("entry_count"))
        if entry_count is None and isinstance(right_side.get("entries"), list):
            entry_count = len(entries)
        entries_vertical = self._optional_bool(right_side.get("entries_vertical"))
        if entry_count is None:
            right_status = "uncertain"
            right_conclusion = "无法确认右侧入口数量"
        elif entry_count != 2:
            right_status = "not_applicable"
            right_conclusion = f"右侧不是2个入口（检测为{entry_count}个）"
        else:
            right_status = self._required_status([entries_vertical])
            right_conclusion = (
                "右侧有2个入口，且为上下排列"
                if entries_vertical is True
                else "右侧有2个入口，但不是上下排列"
                if entries_vertical is False
                else "右侧有2个入口，无法确认是否上下排列"
            )
        right_annotations = []
        if entry_count == 2:
            right_annotations = self._annotations(("右侧入口区", right_side.get("bbox_norm"), x_box))
            right_annotations.extend(self._entry_annotations(entries, x_box, "右侧入口"))
        checks["3.7"] = self._check(
            "3.7",
            "X区域右侧双入口排列",
            "x",
            right_status,
            right_conclusion,
            {"entry_count": entry_count, "entries_vertical": entries_vertical},
            right_annotations,
        )

        checks["3.8"] = self._three_entry_check(entry_count, entries, x_box)

        superstar = self._object(x_payload.get("superstar_benefits"))
        checks["3.9"] = self._superstar_check(superstar, x_box)
        return checks

    def _three_entry_check(
        self,
        entry_count: int | None,
        entries: list[Any],
        region_box: list[int],
    ) -> dict[str, Any]:
        if entry_count is None:
            return self._check(
                "3.8",
                "X区域右侧三入口组件规范",
                "x",
                "uncertain",
                "无法确认右侧入口数量",
                {"entry_count": None, "entries": []},
                [],
            )
        if entry_count != 3:
            return self._check(
                "3.8",
                "X区域右侧三入口组件规范",
                "x",
                "not_applicable",
                f"右侧入口数为{entry_count}，三入口规范不适用",
                {"entry_count": entry_count, "entries": []},
                [],
            )

        entry_results: list[dict[str, Any]] = []
        statuses: list[str] = []
        for index, raw_entry in enumerate(entries):
            entry = self._object(raw_entry)
            tag_text = self._text_or_none(entry.get("tag_text"))
            cta_text = self._text_or_none(entry.get("cta_text"))
            facts = {
                "annotation_available": self._bbox_available(entry.get("bbox_norm")),
                "tag_bar_present": self._optional_bool(entry.get("tag_bar_present")),
                "tag_text": tag_text,
                "tag_text_within_6_chars": self._text_length_valid(tag_text, 6),
                "product_thumbnail_present": self._optional_bool(entry.get("product_thumbnail_present")),
                "product_name_present": self._optional_bool(entry.get("product_name_present")),
                "product_name_single_line": self._optional_bool(entry.get("product_name_single_line")),
                "price_row_present": self._optional_bool(entry.get("price_row_present")),
                "main_price_present": self._optional_bool(entry.get("main_price_present")),
                "cta_present": self._optional_bool(entry.get("cta_present")),
                "cta_text": cta_text,
                "cta_text_within_2_chars": self._text_length_valid(cta_text, 2),
            }
            entry_status = self._required_status(
                [value for key, value in facts.items() if key not in {"tag_text", "cta_text"}]
            )
            statuses.append(entry_status)
            entry_results.append({"index": index + 1, "status": entry_status, **facts})

        if len(entries) != 3:
            status = "fail"
        elif "fail" in statuses:
            status = "fail"
        elif "uncertain" in statuses:
            status = "uncertain"
        else:
            status = "pass"
        conclusion = {
            "pass": "3个右侧入口均符合标签、商品、价格和CTA规范",
            "fail": "3个右侧入口中存在组件缺失或字数/行数不合规",
            "uncertain": "3个右侧入口存在无法确认的必备项",
        }[status]
        return self._check(
            "3.8",
            "X区域右侧三入口组件规范",
            "x",
            status,
            conclusion,
            {"entry_count": entry_count, "entries": entry_results},
            self._entry_annotations(entries, region_box, "三入口组件"),
        )

    def _superstar_check(
        self,
        superstar: dict[str, Any],
        region_box: list[int],
    ) -> dict[str, Any]:
        title_present = self._optional_bool(superstar.get("title_present"))
        modules = superstar.get("star_modules") if isinstance(superstar.get("star_modules"), list) else []
        module_count = self._optional_count(superstar.get("star_module_count"))
        if module_count is None and isinstance(superstar.get("star_modules"), list):
            module_count = len(modules)
        vertical = self._optional_bool(superstar.get("star_modules_vertical"))
        refresh = self._optional_bool(superstar.get("refresh_button_present"))
        other_section = self._optional_bool(superstar.get("other_section_present"))
        details = {
            "superstar_benefits": {
                "title_present": title_present,
                "star_module_count": module_count,
                "star_modules_vertical": vertical,
                "refresh_button_present": refresh,
                "other_section_present": other_section,
            },
        }
        if title_present is False:
            return self._check(
                "3.9",
                "X区域超级明星福利规范",
                "x",
                "not_applicable",
                "右侧未出现“超级明星福利”标题，本项不适用",
                details,
                [],
            )
        if title_present is None:
            return self._check(
                "3.9",
                "X区域超级明星福利规范",
                "x",
                "uncertain",
                "无法确认右侧是否出现“超级明星福利”标题",
                details,
                [],
            )

        annotations = self._annotations(
            ("超级明星福利标题", superstar.get("title_bbox_norm"), region_box),
            (
                "换一换按钮",
                superstar.get("refresh_button_bbox_norm") if refresh is True else None,
                region_box,
            ),
            (
                "其他栏目",
                superstar.get("other_section_bbox_norm") if other_section is True else None,
                region_box,
            ),
        )
        if module_count is not None and module_count > 0:
            annotations.extend(self._entry_annotations(modules, region_box, "明星模块"))

        count_is_two = module_count == 2 if module_count is not None else None
        no_other_section = not other_section if other_section is not None else None
        status = self._required_status([count_is_two, vertical, refresh, no_other_section])
        conclusion = {
            "pass": "区域仅含2个纵向明星模块和1个“换一换”按钮",
            "fail": "超级明星福利区域的模块数量、排列、按钮或栏目内容不合规",
            "uncertain": "超级明星福利区域存在无法确认的必备项",
        }[status]
        return self._check(
            "3.9",
            "X区域超级明星福利规范",
            "x",
            status,
            conclusion,
            details,
            annotations,
        )

    def _check(
        self,
        check_id: str,
        title: str,
        region: str,
        status: str,
        conclusion: str,
        details: dict[str, Any],
        annotations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if status not in ALLOWED_STATUSES:
            raise ValueError(f"Unsupported check status: {status}")
        return {
            "id": check_id,
            "title": title,
            "region": region,
            "status": status,
            "conclusion": conclusion,
            "details": details,
            "annotations": annotations,
        }

    def _annotations(self, *items: tuple[str, Any, list[int]]) -> list[dict[str, Any]]:
        annotations = []
        for label, raw_bbox, region_box in items:
            bbox_norm = self._normalize_bbox(raw_bbox)
            if bbox_norm is None:
                continue
            annotations.append(
                {
                    "label": label,
                    "bbox_norm": bbox_norm,
                    "bbox_px": self._map_bbox(bbox_norm, region_box),
                }
            )
        return annotations

    def _entry_annotations(
        self,
        entries: list[Any],
        region_box: list[int],
        label: str,
    ) -> list[dict[str, Any]]:
        return self._annotations(
            *((f"{label}{index + 1}", self._object(entry).get("bbox_norm"), region_box) for index, entry in enumerate(entries))
        )

    def _normalize_bbox(self, value: Any) -> list[int] | None:
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            return None
        normalized = []
        for item in value:
            if isinstance(item, bool):
                return None
            try:
                number = float(item)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(number):
                return None
            normalized.append(round(max(0.0, min(1000.0, number))))
        x1, y1, x2, y2 = normalized
        if x2 <= x1 or y2 <= y1:
            return None
        return normalized

    def _map_bbox(self, bbox: list[int], region_box: list[int]) -> list[int]:
        left, top, right, bottom = region_box
        width, height = right - left, bottom - top
        x1, y1, x2, y2 = bbox
        return [
            left + round(x1 * width / 1000),
            top + round(y1 * height / 1000),
            left + round(x2 * width / 1000),
            top + round(y2 * height / 1000),
        ]

    def _bbox_contains(self, container_value: Any, child_value: Any, tolerance: int = 30) -> bool | None:
        container = self._normalize_bbox(container_value)
        child = self._normalize_bbox(child_value)
        if container is None or child is None:
            return None
        return (
            container[0] - tolerance <= child[0]
            and container[1] - tolerance <= child[1]
            and container[2] + tolerance >= child[2]
            and container[3] + tolerance >= child[3]
        )

    def _bbox_available(self, value: Any) -> bool | None:
        return True if self._normalize_bbox(value) is not None else None

    def _bbox_at_bottom(self, container_value: Any, child_value: Any, tolerance: int = 50) -> bool | None:
        container = self._normalize_bbox(container_value)
        child = self._normalize_bbox(child_value)
        if container is None or child is None:
            return None
        return self._bbox_contains(container, child, tolerance) is True and abs(container[3] - child[3]) <= tolerance

    def _required_status(self, values: list[bool | None]) -> str:
        if any(value is False for value in values):
            return "fail"
        if values and all(value is True for value in values):
            return "pass"
        return "uncertain"

    def _valid_optional_component(
        self,
        present: bool | None,
        requirements: list[bool | None],
    ) -> bool | None:
        if present is not True:
            return None
        if any(requirement is False for requirement in requirements):
            return False
        if all(requirement is True for requirement in requirements):
            return True
        return None

    def _and_optional(self, values: list[bool | None]) -> bool | None:
        if any(value is False for value in values):
            return False
        if values and all(value is True for value in values):
            return True
        return None

    def _at_least_one_true(self, values: list[bool | None]) -> bool | None:
        if any(value is True for value in values):
            return True
        if values and all(value is False for value in values):
            return False
        return None

    def _optional_bool(self, value: Any) -> bool | None:
        return value if isinstance(value, bool) else None

    def _optional_count(self, value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if not math.isfinite(float(value)) or value < 0 or int(value) != value:
            return None
        return int(value)

    def _object(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _present(self, value: dict[str, Any]) -> bool | None:
        return self._optional_bool(value.get("present"))

    def _text(self, value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    def _text_or_none(self, value: Any) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        return value.strip()

    def _text_length_valid(self, value: str | None, maximum: int) -> bool | None:
        return len(value) <= maximum if value is not None else None

    def _floor_type(self, value: Any) -> str:
        if not isinstance(value, str):
            return "uncertain"
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in {"combination", "composite", "组合型楼层", "组合型"}:
            return "combination"
        if normalized in {"one_row_one_hit", "一行一爆品", "一行一爆品楼层"}:
            return "one_row_one_hit"
        return "uncertain"

    def _benefit_presentation(self, value: Any) -> str:
        if not isinstance(value, str):
            return "uncertain"
        normalized = value.strip().lower()
        aliases = {"箭头": "arrow", "按钮": "button", "图片": "image", "无": "none"}
        normalized = aliases.get(normalized, normalized)
        return normalized if normalized in {"arrow", "button", "image", "none"} else "uncertain"

    def _is_subtitle_badge(self, text: str | None) -> bool:
        if text is None:
            return False
        compact = re.sub(r"\s+", "", text)
        return re.fullmatch(r"新发布[+＋]?", compact) is not None

    def _presence_conclusion(self, navigation: bool | None, tab: bool | None) -> str:
        if navigation is True and tab is True:
            return "x区域上方是导航栏，下方是Tab栏"
        if navigation is None or tab is None:
            return "无法完整确认x区域上下栏位"
        missing = []
        if navigation is False:
            missing.append("上方导航栏")
        if tab is False:
            missing.append("下方Tab栏")
        return "未检测到" + "、".join(missing)

    def _component_conclusion(self, status: str, components: dict[str, Any]) -> str:
        if status == "pass":
            return "首焦组件齐全，底部信息容器内至少有一个有效的小标题或利益点"
        if status == "uncertain":
            return "首焦组件存在无法确认的必备项"
        labels = {
            "cover_image_present": "封面图",
            "gradient_overlay_present": "渐变蒙层",
            "overlay_supports_white_text": "可读性足够的蒙层",
            "overlay_at_cover_bottom": "叠加在封面底部的蒙层",
            "primary_focus_title_present": "首焦栏目标题",
            "primary_focus_title_supported_by_overlay": "由蒙层承托的首焦栏目标题",
            "bottom_info_container_present": "底部信息容器",
            "bottom_info_has_subtitle_or_benefit": "信息容器内的小标题或利益点",
            "subtitle_valid_when_present": "符合规范的小标题",
            "benefit_valid_when_present": "符合规范的利益点",
        }
        missing = [labels[key] for key in labels if components.get(key) is False]
        return "缺失或不合规：" + "、".join(missing)

    def _summarize(self, checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
        counts = {status: 0 for status in ("pass", "fail", "not_applicable", "uncertain")}
        for check in checks.values():
            counts[check["status"]] += 1
        status = "fail" if counts["fail"] else "uncertain" if counts["uncertain"] else "pass"
        conclusion = {
            "pass": "所有适用且可确认的检查项均通过",
            "fail": f"发现{counts['fail']}项不合规",
            "uncertain": f"有{counts['uncertain']}项无法确认",
        }[status]
        return {"status": status, "counts": counts, "conclusion": conclusion}


# Keep both spellings available to callers; Python class names in this project
# usually use ``Jd``, while integrations may naturally spell the brand ``JD``.
JDNewFloorAnalysis = JdNewFloorAnalysis
JDNewFloorAnalyzer = JdNewFloorAnalyzer

jd_new_floor_analyzer = JdNewFloorAnalyzer()
