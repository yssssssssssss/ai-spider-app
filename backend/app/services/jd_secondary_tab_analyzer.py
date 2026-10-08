from __future__ import annotations

import asyncio
import base64
import json
import math
import re
from collections import Counter
from dataclasses import asdict, dataclass
from io import BytesIO
from typing import Any, Protocol

from PIL import Image, UnidentifiedImageError

from app.services.llm_analyzer import MAX_VLM_IMAGE_SIDE, analyzer


Z23_TOP = 450
Z23_BOTTOM = 525
SECONDARY_ANCHOR_TEXT = "推荐"
FRAME_KEYS = (
    "z1_before",
    "z1_after_left",
    "z2_before",
    "z2_after_left",
    "z3_before",
)
FRAME_FILENAMES = {
    "z1_before": "secondary_tab_z1_before.png",
    "z1_after_left": "secondary_tab_z1_after_left.png",
    "z2_before": "secondary_tab_z2_before.png",
    "z2_after_left": "secondary_tab_z2_after_left.png",
    "z3_before": "secondary_tab_z3_before.png",
}
BASELINE_FRAMES = {"z1": "z1_before", "z2": "z2_before", "z3": "z3_before"}
ANALYSIS_ATTEMPTS = 2
ANALYSIS_MAX_TOKENS = 4096
ALLOWED_STATUSES = {"pass", "fail", "uncertain"}


Z1_LOCATOR_PROMPT = """你是京东 App“新品 > 新奇集市”页面的组件定位器。当前图片是1080x2400比例的完整手机截图。
请定位一个横向二级Tab行，其中必须包含文本“推荐”，并且“推荐”文字本身呈红色；同一行通常还有“新奇AI、新奇数码、新奇种草、新奇潮玩”等灰色文本。
不要把顶部主频道、商品标题、红色图标、按钮或其他“推荐”文案当作目标。
只返回JSON，不要Markdown：
{
  "present": true,
  "anchor_text": "推荐",
  "anchor_color": "red",
  "anchor_bbox_norm": [x1,y1,x2,y2],
  "tab_row_bbox_norm": [x1,y1,x2,y2],
  "visible_texts": ["推荐"],
  "evidence": "简短依据"
}
坐标相对整张截图，范围0~1000。tab_row_bbox_norm应覆盖整行Tab的完整高度和左右范围。无法确认则present返回false、bbox返回null。"""


BASELINE_PROMPT = """你是京东 App“新品”页中“新奇集市”二级 Tab 组件视觉检查器。页面已先点击“新奇集市”。依次给你三张仅包含目标二级 Tab 水平带的裁图：
第1张=z1（页面未纵向移动，由红色“推荐”锚点动态定位）；第2张=z2（页面向下滚动800px后，原图 y=450~525）；第3张=z3（随后页面向上回退400px后，原图 y=450~525）。

每个可见的二级 Tab 文本项算一组，items 必须按从左到右顺序返回。文本呈选中红色时标记 selected，呈普通灰色时标记 unselected；第二个按钮无论实际颜色是否合规都固定标记 special，不计入 selected 或 unselected，并单独判断其文字色是否接近 #E63FAF。不要把红色图标、角标、下划线或商品内容误判为选中态。判断文本是否始终保持单行，不要求像素级一致。

请只依据可见内容返回一个 JSON 对象，不要 Markdown：
{
  "regions": {
    "z1": {
      "items": [{"text": "文字", "state": "selected|unselected|special|uncertain", "single_line": true, "bbox_norm": [x1,y1,x2,y2]}],
      "all_single_line": true,
      "selected_color_hex": "#RRGGBB",
      "unselected_color_hex": "#RRGGBB",
      "background_color_hex": "#RRGGBB",
      "second_button_color_hex": "#RRGGBB",
      "selected_matches_target_FF0F23": true,
      "unselected_matches_target_3D414D": true,
      "background_matches_target_F2F3F5": true,
      "second_button_matches_target_E63FAF": true,
      "evidence": "简短依据"
    },
    "z2": {"items": [], "all_single_line": true, "evidence": "简短依据"},
    "z3": {"items": [], "all_single_line": true, "evidence": "简短依据"}
  },
  "comparisons": {
    "z2_matches_z1": true,
    "z2_evidence": "从组件整体、文本内容与顺序判断，不比较像素",
    "z3_matches_z1": true,
    "z3_evidence": "从组件整体、文本内容与顺序判断，不比较像素",
    "selected_content_consistent": true,
    "selected_content_evidence": "仅判断z1和z2的选中态文字是否一致"
  }
}

bbox_norm 相对各自裁图，坐标范围0~1000。只统计裁图内可辨认的二级 Tab 文本；看不清时布尔值返回 null、state 返回 uncertain、颜色返回 null、bbox 返回 null。颜色只需给出视觉上最接近的 HEX，不要求严格色值。对四个目标色的匹配都按整体视觉判断，不做严格逐通道相等比较；第二个按钮目标文字色为 #E63FAF。"""


HORIZONTAL_PROMPT = """你是移动端二级 Tab 横向滑动验证器。依次给你四张1080x2400同尺寸全屏截图，按前后配对：
第1、2张=z1区域左滑400px前、后，z1由红色“推荐”锚点动态定位；第3、4张=z2区域左滑400px前、后，z2为原图y=450~525。

请分别判断：1）对应区域内的二级 Tab 内容是否确实发生水平位移或显示范围变化；2）除该区域外的主要页面内容是否保持不变。只认可 Tab 文本/项目的水平变化，不要把页面动画、闪烁、状态栏时间或微小渲染差异算作区域外变化。

只返回 JSON，不要 Markdown：
{
  "regions": {
    "z1": {"content_moved_horizontally": true, "outside_region_unchanged": true, "before_texts": [""], "after_texts": [""], "evidence": "简短依据"},
    "z2": {"content_moved_horizontally": true, "outside_region_unchanged": true, "before_texts": [""], "after_texts": [""], "evidence": "简短依据"}
  }
}
无法确认时对应布尔值返回 null。"""


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
class JdSecondaryTabAnalysis:
    report_type: str
    schema_version: int
    capture: dict[str, Any]
    regions: dict[str, dict[str, Any]]
    frames: dict[str, dict[str, Any]]
    checks: dict[str, dict[str, Any]]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class JdSecondaryTabAnalyzer:
    """Analyze fixed secondary-Tab regions without changing the floor analyzer."""

    def __init__(self, image_completion: ImageCompletion = analyzer):
        self.image_completion = image_completion

    async def locate_z1_png(self, content: bytes) -> dict[str, Any]:
        if not getattr(self.image_completion, "providers", []):
            raise RuntimeError("No image-capable LLM provider configured")
        image = self._load_png(content, "z1 locator")
        payload = await self._analyze(
            Z1_LOCATOR_PROMPT,
            [self._encode_image(image)],
            "z1 locator",
        )
        if self._optional_bool(payload.get("present")) is not True:
            raise ValueError("Red recommendation secondary Tab was not found")
        if self._normalize_text(self._text(payload.get("anchor_text"))) != SECONDARY_ANCHOR_TEXT:
            raise ValueError("Secondary Tab locator did not identify the recommendation anchor")
        if self._text(payload.get("anchor_color")).lower() != "red":
            raise ValueError("Secondary Tab recommendation anchor is not red")
        anchor_norm = self._normalize_bbox(payload.get("anchor_bbox_norm"))
        row_norm = self._normalize_bbox(payload.get("tab_row_bbox_norm"))
        if anchor_norm is None or row_norm is None:
            raise ValueError("Secondary Tab locator returned incomplete bounds")
        full_box = [0, 0, image.width, image.height]
        anchor_bbox = self._map_bbox(anchor_norm, full_box)
        row_bbox = self._map_bbox(row_norm, full_box)
        if not self._has_red_pixels(image, anchor_bbox):
            raise ValueError("Recommendation anchor pixels are not visually red")
        return {
            "report_type": "jd_secondary_tab_locator",
            "anchor_text": SECONDARY_ANCHOR_TEXT,
            "anchor_color": "red",
            "anchor_bbox_px": anchor_bbox,
            "bbox_px": [0, row_bbox[1], image.width, row_bbox[3]],
            "visible_texts": self._texts(payload.get("visible_texts")),
            "evidence": self._text(payload.get("evidence")),
        }

    async def analyze_pngs(
        self,
        contents: dict[str, bytes],
        z1_top: int,
        z1_bottom: int,
    ) -> JdSecondaryTabAnalysis:
        crops, full_images, width, height = self._prepare_crops(contents, z1_top, z1_bottom)
        if not getattr(self.image_completion, "providers", []):
            raise RuntimeError("No image-capable LLM provider configured")

        baseline_payload, horizontal_payload = await asyncio.gather(
            self._analyze(
                f"本次动态识别出的z1区域为原图y={z1_top}~{z1_bottom}。\n" + BASELINE_PROMPT,
                [crops[BASELINE_FRAMES[region]] for region in ("z1", "z2", "z3")],
                "baseline",
            ),
            self._analyze(
                f"本次动态识别出的z1区域为原图y={z1_top}~{z1_bottom}。\n" + HORIZONTAL_PROMPT,
                [self._encode_image(full_images[key]) for key in FRAME_KEYS[:4]],
                "horizontal",
            ),
        )

        regions = self._regions(width, z1_top, z1_bottom)
        frames = self._frames(regions, width, height)
        checks = self._build_checks(
            baseline_payload,
            horizontal_payload,
            full_images["z1_before"],
            regions,
        )
        return JdSecondaryTabAnalysis(
            report_type="jd_secondary_tab_audit",
            schema_version=1,
            capture={"format": "PNG", "width": width, "height": height},
            regions=regions,
            frames=frames,
            checks=checks,
            summary=self._summarize(checks),
        )

    async def _analyze(self, prompt: str, images: list[str], label: str) -> dict[str, Any]:
        for attempt in range(ANALYSIS_ATTEMPTS):
            response = await self.image_completion.complete_images(
                prompt,
                images,
                preferred_provider="openai",
                max_tokens=ANALYSIS_MAX_TOKENS,
            )
            try:
                return self._parse_json(response, label)
            except ValueError:
                if attempt + 1 == ANALYSIS_ATTEMPTS:
                    raise
        raise AssertionError("unreachable")

    def _load_png(self, content: bytes, label: str) -> Image.Image:
        if not content:
            raise ValueError(f"Image content is empty for {label}")
        try:
            with Image.open(BytesIO(content)) as image:
                if image.format != "PNG":
                    raise ValueError(f"{label} must be PNG")
                image.load()
                return image.convert("RGB")
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError(f"Unsupported image content for {label}") from exc

    def _prepare_crops(
        self,
        contents: dict[str, bytes],
        z1_top: int,
        z1_bottom: int,
    ) -> tuple[dict[str, str], dict[str, Image.Image], int, int]:
        if z1_top < 0 or z1_bottom <= z1_top:
            raise ValueError(f"Invalid detected z1 bounds: {z1_top}~{z1_bottom}")
        missing = [key for key in FRAME_KEYS if not contents.get(key)]
        if missing:
            raise ValueError("Missing secondary Tab frames: " + ", ".join(missing))

        crops: dict[str, str] = {}
        full_images: dict[str, Image.Image] = {}
        expected_size: tuple[int, int] | None = None
        for key in FRAME_KEYS:
            try:
                with Image.open(BytesIO(contents[key])) as image:
                    if image.format != "PNG":
                        raise ValueError(f"{key} must be PNG")
                    image.load()
                    if expected_size is None:
                        expected_size = image.size
                    elif image.size != expected_size:
                        raise ValueError("All secondary Tab screenshots must have the same dimensions")
                    rgb = image.convert("RGB")
                    width, height = rgb.size
                    region_box = self._region_box(self._frame_region(key), width, z1_top, z1_bottom)
                    if height < region_box[3]:
                        raise ValueError(f"{key} is too short for its configured region")
                    full_images[key] = rgb.copy()
                    crops[key] = self._encode_image(rgb.crop(region_box))
            except (UnidentifiedImageError, OSError) as exc:
                raise ValueError(f"Unsupported image content for {key}") from exc

        if expected_size is None:
            raise ValueError("No secondary Tab screenshots supplied")
        return crops, full_images, expected_size[0], expected_size[1]

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

    def _parse_json(self, text: str, label: str) -> dict[str, Any]:
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
            raise ValueError(f"JD secondary Tab analyzer returned invalid JSON for {label}") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"JD secondary Tab analyzer result for {label} must be an object")
        return payload

    def _regions(self, width: int, z1_top: int, z1_bottom: int) -> dict[str, dict[str, Any]]:
        return {
            "z1": {"label": "z1区域", "bbox_px": [0, z1_top, width, z1_bottom], "width_px": width, "height_px": z1_bottom - z1_top},
            "z2": {"label": "z2区域", "bbox_px": [0, Z23_TOP, width, Z23_BOTTOM], "width_px": width, "height_px": Z23_BOTTOM - Z23_TOP},
            "z3": {"label": "z3区域", "bbox_px": [0, Z23_TOP, width, Z23_BOTTOM], "width_px": width, "height_px": Z23_BOTTOM - Z23_TOP},
        }

    def _frames(self, regions: dict[str, dict[str, Any]], width: int, height: int) -> dict[str, dict[str, Any]]:
        labels = {
            "z1_before": "z1 横滑前",
            "z1_after_left": "z1 左滑400px后",
            "z2_before": "z2 横滑前",
            "z2_after_left": "z2 左滑400px后",
            "z3_before": "z3 页面回退400px后",
        }
        return {
            key: {
                "label": labels[key],
                "filename": FRAME_FILENAMES[key],
                "region": self._frame_region(key),
                "bbox_px": list(regions[self._frame_region(key)]["bbox_px"]),
                "image_width": width,
                "image_height": height,
            }
            for key in FRAME_KEYS
        }

    def _build_checks(
        self,
        baseline_payload: dict[str, Any],
        horizontal_payload: dict[str, Any],
        z1_image: Image.Image,
        regions: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        payload_regions = self._object(baseline_payload.get("regions"))
        facts: dict[str, dict[str, Any]] = {}
        for region in ("z1", "z2", "z3"):
            raw = self._object(payload_regions.get(region))
            items = self._items(raw.get("items"), regions[region]["bbox_px"])
            if len(items) > 1:
                items[1]["state"] = "special"
            selected = [item for item in items if item["state"] == "selected"]
            unselected = [item for item in items if item["state"] == "unselected"]
            special = [item for item in items if item["state"] == "special"]
            all_single_line = self._optional_bool(raw.get("all_single_line"))
            if all_single_line is None and items and all(item["single_line"] is not None for item in items):
                all_single_line = all(item["single_line"] is True for item in items)
            facts[region] = {
                "items": items,
                "selected_count": len(selected),
                "unselected_count": len(unselected),
                "special_count": len(special),
                "uncertain_count": len(items) - len(selected) - len(unselected) - len(special),
                "selected_texts": [item["text"] for item in selected if item["text"]],
                "all_single_line": all_single_line,
                "evidence": self._text(raw.get("evidence")),
                "model_colors": {
                    "selected": self._hex(raw.get("selected_color_hex")),
                    "unselected": self._hex(raw.get("unselected_color_hex")),
                    "background": self._hex(raw.get("background_color_hex")),
                    "second_button": self._hex(raw.get("second_button_color_hex")),
                },
            }

        z1_colors = self._sample_z1_colors(z1_image, facts["z1"], regions["z1"]["bbox_px"])
        facts["z1"].update(
            {
                "selected_color_hex": z1_colors["selected"] or facts["z1"]["model_colors"]["selected"],
                "unselected_color_hex": z1_colors["unselected"] or facts["z1"]["model_colors"]["unselected"],
                "background_color_hex": z1_colors["background"] or facts["z1"]["model_colors"]["background"],
                "second_button_color_hex": z1_colors["second_button"] or facts["z1"]["model_colors"]["second_button"],
                "color_source": "截图像素采样（近似主色）" if z1_colors["sampled"] else "视觉模型近似值",
            }
        )

        z1 = facts["z1"]
        z1_model = self._object(payload_regions.get("z1"))
        selected_matches_target = self._optional_bool(z1_model.get("selected_matches_target_FF0F23"))
        unselected_matches_target = self._optional_bool(z1_model.get("unselected_matches_target_3D414D"))
        background_matches_target = self._optional_bool(z1_model.get("background_matches_target_F2F3F5"))
        second_button_matches_target = self._optional_bool(z1_model.get("second_button_matches_target_E63FAF"))
        second_button = z1["items"][1] if len(z1["items"]) > 1 else None
        z1.update(
            {
                "selected_target_hex": "#FF0F23",
                "selected_color_matches_target": selected_matches_target,
                "unselected_target_hex": "#3D414D",
                "unselected_color_matches_target": unselected_matches_target,
                "background_target_hex": "#F2F3F5",
                "background_color_matches_target": background_matches_target,
                "second_button_text": second_button.get("text") if second_button else None,
                "second_button_target_hex": "#E63FAF",
                "second_button_color_matches_target": second_button_matches_target,
            }
        )
        color_matches = [
            selected_matches_target,
            unselected_matches_target,
            background_matches_target,
            second_button_matches_target,
        ]
        if not z1["items"] or len(z1["items"]) < 2 or z1["selected_count"] < 1 or z1["unselected_count"] < 1:
            check1_status = "fail"
        elif any(value is False for value in color_matches):
            check1_status = "fail"
        elif z1["uncertain_count"] or not all(
            z1.get(key)
            for key in (
                "selected_color_hex",
                "unselected_color_hex",
                "background_color_hex",
                "second_button_color_hex",
            )
        ) or any(value is None for value in color_matches):
            check1_status = "uncertain"
        else:
            check1_status = "pass"
        check1_conclusion = (
            f"有{z1['selected_count']}组选中态，{z1['unselected_count']}组非选中态；"
            f"选中态色值为{z1.get('selected_color_hex') or '待确认'}，和目标色值#FF0F23{self._match_text(selected_matches_target)}；"
            f"非选中态色值为{z1.get('unselected_color_hex') or '待确认'}，和目标色值#3D414D{self._match_text(unselected_matches_target)}；"
            f"背景色值为{z1.get('background_color_hex') or '待确认'}，和目标色值#F2F3F5{self._match_text(background_matches_target)}；"
            f"第二个按钮“{z1.get('second_button_text') or '待确认'}”文字色值为{z1.get('second_button_color_hex') or '待确认'}，"
            f"和目标色值#E63FAF{self._match_text(second_button_matches_target)}"
        )

        comparisons = self._object(baseline_payload.get("comparisons"))
        z2_matches = self._optional_bool(comparisons.get("z2_matches_z1"))
        z3_matches = self._optional_bool(comparisons.get("z3_matches_z1"))
        selected_consistent = self._optional_bool(comparisons.get("selected_content_consistent"))
        if selected_consistent is None:
            selected_consistent = self._selected_texts_consistent(facts)

        horizontal_regions = self._object(horizontal_payload.get("regions"))
        horizontal_facts: dict[str, dict[str, Any]] = {}
        for region in ("z1", "z2"):
            raw = self._object(horizontal_regions.get(region))
            moved = self._optional_bool(raw.get("content_moved_horizontally"))
            if not facts[region]["items"]:
                moved = False
            horizontal_facts[region] = {
                "content_moved_horizontally": moved,
                "outside_region_unchanged": self._optional_bool(raw.get("outside_region_unchanged")),
                "before_texts": self._texts(raw.get("before_texts")),
                "after_texts": self._texts(raw.get("after_texts")),
                "evidence": self._text(raw.get("evidence")),
            }

        z2_result = z2_matches if facts["z1"]["items"] and facts["z2"]["items"] else False
        check2_status = self._status_from_bool(z2_result)
        if not facts["z1"]["items"]:
            check3_status = "fail"
            check3_conclusion = "错误"
        else:
            check3_status = self._inverted_status_from_bool(z3_matches)
            check3_conclusion = self._correct_error_text(z3_matches, inverted=True)
        check4_status = self._required_status(
            [
                bool(facts["z1"]["items"]),
                bool(facts["z2"]["items"]),
                facts["z1"]["all_single_line"],
                facts["z2"]["all_single_line"],
            ]
        )
        exactly_one_selected = {
            region: facts[region]["selected_count"] == 1 if facts[region]["items"] else False
            for region in ("z1", "z2")
        }
        check5_status = self._required_status(
            [exactly_one_selected["z1"], exactly_one_selected["z2"], selected_consistent]
        )
        check6_status = self._required_status(
            [
                horizontal_facts[region][fact]
                for region in ("z1", "z2")
                for fact in ("content_moved_horizontally", "outside_region_unchanged")
            ]
        )

        return {
            "1": self._check(
                "1",
                "z1 选中态、非选中态与颜色",
                check1_status,
                check1_conclusion,
                z1,
                self._evidence(["z1_before"], facts, regions),
            ),
            "2": self._check(
                "2",
                "z2 与 z1 内容一致性",
                check2_status,
                self._correct_error_text(z2_result),
                {
                    "matches_z1": z2_matches,
                    "z1_texts": [item["text"] for item in facts["z1"]["items"]],
                    "z2_texts": [item["text"] for item in facts["z2"]["items"]],
                    "evidence": self._text(comparisons.get("z2_evidence")),
                },
                self._evidence(["z1_before", "z2_before"], facts, regions),
            ),
            "3": self._check(
                "3",
                "z3 与 z1 内容差异性",
                check3_status,
                check3_conclusion,
                {
                    "matches_z1": z3_matches,
                    "expected_to_differ": True,
                    "z1_texts": [item["text"] for item in facts["z1"]["items"]],
                    "z3_texts": [item["text"] for item in facts["z3"]["items"]],
                    "evidence": self._text(comparisons.get("z3_evidence")),
                },
                self._evidence(["z1_before", "z3_before"], facts, regions),
            ),
            "4": self._check(
                "4",
                "z1、z2 内容保持单行",
                check4_status,
                self._check4_conclusion(check4_status),
                {
                    "regions": {
                        region: {
                            "all_single_line": facts[region]["all_single_line"],
                            "texts": [item["text"] for item in facts[region]["items"]],
                        }
                        for region in ("z1", "z2")
                    }
                },
                self._evidence(["z1_before", "z2_before"], facts, regions),
            ),
            "5": self._check(
                "5",
                "z1、z2 唯一选中态及内容一致性",
                check5_status,
                self._check5_conclusion(check5_status),
                {
                    "regions": {
                        region: {
                            "selected_count": facts[region]["selected_count"],
                            "selected_texts": facts[region]["selected_texts"],
                            "exactly_one_selected": exactly_one_selected[region],
                        }
                        for region in ("z1", "z2")
                    },
                    "selected_content_consistent": selected_consistent,
                    "evidence": self._text(comparisons.get("selected_content_evidence")),
                },
                self._evidence(["z1_before", "z2_before"], facts, regions),
            ),
            "6": self._check(
                "6",
                "z1、z2 横向滑动及区域外稳定性",
                check6_status,
                self._check6_conclusion(check6_status, horizontal_facts),
                {
                    "swipe_direction": "left",
                    "swipe_distance_px": 400,
                    "regions": horizontal_facts,
                },
                self._evidence(
                    ["z1_before", "z1_after_left", "z2_before", "z2_after_left"],
                    facts,
                    regions,
                    full_frame=True,
                    image_height=z1_image.height,
                ),
            ),
        }

    def _items(self, value: Any, region_box: list[int]) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            return []
        items = []
        for raw_item in value:
            raw = self._object(raw_item)
            state = str(raw.get("state") or "uncertain").strip().lower()
            if state not in {"selected", "unselected", "special", "uncertain"}:
                state = "uncertain"
            bbox_norm = self._normalize_bbox(raw.get("bbox_norm"))
            items.append(
                {
                    "text": self._text(raw.get("text")),
                    "state": state,
                    "single_line": self._optional_bool(raw.get("single_line")),
                    "bbox_norm": bbox_norm,
                    "bbox_px": self._map_bbox(bbox_norm, region_box) if bbox_norm else None,
                }
            )
        return items

    def _evidence(
        self,
        frame_keys: list[str],
        facts: dict[str, dict[str, Any]],
        regions: dict[str, dict[str, Any]],
        *,
        full_frame: bool = False,
        image_height: int | None = None,
    ) -> list[dict[str, Any]]:
        evidence = []
        for frame_key in frame_keys:
            region = self._frame_region(frame_key)
            region_box = list(regions[region]["bbox_px"])
            annotations = [
                {
                    "label": f"{item['text'] or '未识别'} · {self._state_label(item['state'])}",
                    "bbox_px": item.get("bbox_px"),
                }
                for item in facts[region]["items"]
                if frame_key.endswith("_before") and item.get("bbox_px")
            ]
            if full_frame:
                annotations.insert(0, {"label": f"{region}操作区域", "bbox_px": region_box})
            evidence.append(
                {
                    "frame": frame_key,
                    "label": self._frame_label(frame_key),
                    "bbox_px": [0, 0, region_box[2], image_height] if full_frame and image_height else region_box,
                    "full_frame": full_frame,
                    "annotations": annotations,
                }
            )
        return evidence

    def _sample_z1_colors(
        self,
        image: Image.Image,
        z1: dict[str, Any],
        region_box: list[int],
    ) -> dict[str, str | bool | None]:
        crop = image.crop(tuple(region_box)).convert("RGB")
        background_pixels = crop.get_flattened_data() if hasattr(crop, "get_flattened_data") else crop.getdata()
        background_rgb = self._dominant_rgb(list(background_pixels))
        result: dict[str, str | bool | None] = {
            "selected": None,
            "unselected": None,
            "background": self._rgb_hex(background_rgb) if background_rgb else None,
            "second_button": None,
            "sampled": background_rgb is not None,
        }
        if background_rgb is None:
            return result

        for state in ("selected", "unselected"):
            pixels: list[tuple[int, int, int]] = []
            for item in z1["items"]:
                if item["state"] != state or not item.get("bbox_norm"):
                    continue
                local_box = self._map_bbox(item["bbox_norm"], [0, 0, crop.width, crop.height])
                item_crop = crop.crop(tuple(local_box))
                item_pixels = item_crop.get_flattened_data() if hasattr(item_crop, "get_flattened_data") else item_crop.getdata()
                pixels.extend(item_pixels)
            candidates = self._foreground_candidates(pixels, background_rgb, state)
            color = self._dominant_rgb(candidates, state=state)
            if color is not None:
                result[state] = self._rgb_hex(color)
                result["sampled"] = True

        if len(z1["items"]) > 1 and z1["items"][1].get("bbox_norm"):
            second_box = self._map_bbox(
                z1["items"][1]["bbox_norm"],
                [0, 0, crop.width, crop.height],
            )
            second_crop = crop.crop(tuple(second_box))
            second_pixels = list(
                second_crop.get_flattened_data() if hasattr(second_crop, "get_flattened_data") else second_crop.getdata()
            )
            second_candidates = self._foreground_candidates(second_pixels, background_rgb, "special")
            second_color = self._dominant_rgb(second_candidates, state="special")
            if second_color is not None:
                result["second_button"] = self._rgb_hex(second_color)
                result["sampled"] = True
        return result

    def _has_red_pixels(self, image: Image.Image, bbox: list[int]) -> bool:
        crop = image.crop(tuple(bbox)).convert("RGB")
        pixels = list(crop.get_flattened_data() if hasattr(crop, "get_flattened_data") else crop.getdata())
        red_count = sum(
            1
            for red, green, blue in pixels
            if red >= 140 and red - green >= 35 and red - blue >= 25
        )
        return red_count >= max(8, len(pixels) // 200)

    def _foreground_candidates(
        self,
        pixels: list[tuple[int, int, int]],
        background: tuple[int, int, int],
        state: str,
    ) -> list[tuple[int, int, int]]:
        candidates = []
        background_luma = sum(background) / 3
        for pixel in pixels:
            distance = math.sqrt(sum((pixel[index] - background[index]) ** 2 for index in range(3)))
            if distance < 32:
                continue
            red, green, blue = pixel
            if state == "selected":
                if red >= 110 and red - green >= 22 and red - blue >= 16:
                    candidates.append(pixel)
            elif state == "unselected":
                if max(pixel) - min(pixel) <= 65 and sum(pixel) / 3 <= background_luma - 18:
                    candidates.append(pixel)
            else:
                candidates.append(pixel)
        return candidates

    def _dominant_rgb(
        self,
        pixels: list[tuple[int, int, int]],
        *,
        state: str | None = None,
    ) -> tuple[int, int, int] | None:
        if not pixels:
            return None
        bins: Counter[tuple[int, int, int]] = Counter(
            (red // 12, green // 12, blue // 12) for red, green, blue in pixels
        )
        if state == "selected":
            winning = max(
                bins,
                key=lambda key: bins[key] * (1 + max(0, key[0] - max(key[1], key[2])) / 21),
            )
        elif state == "unselected":
            winning = max(
                bins,
                key=lambda key: bins[key] * (1 + max(0, 21 - sum(key) / 3) / 21),
            )
        else:
            winning = bins.most_common(1)[0][0]
        chosen = [
            pixel
            for pixel in pixels
            if (pixel[0] // 12, pixel[1] // 12, pixel[2] // 12) == winning
        ]
        return tuple(
            round(sum(pixel[index] for pixel in chosen) / len(chosen))
            for index in range(3)
        )  # type: ignore[return-value]

    def _selected_texts_consistent(self, facts: dict[str, dict[str, Any]]) -> bool | None:
        selected = [
            [self._normalize_text(text) for text in facts[region]["selected_texts"] if self._normalize_text(text)]
            for region in ("z1", "z2")
        ]
        if any(not values for values in selected):
            return None
        return selected[0] == selected[1]

    def _check(
        self,
        check_id: str,
        title: str,
        status: str,
        conclusion: str,
        details: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if status not in ALLOWED_STATUSES:
            raise ValueError(f"Unsupported secondary Tab check status: {status}")
        return {
            "id": check_id,
            "title": title,
            "status": status,
            "conclusion": conclusion,
            "details": details,
            "evidence": evidence,
        }

    def _status_from_bool(self, value: bool | None) -> str:
        if value is True:
            return "pass"
        if value is False:
            return "fail"
        return "uncertain"

    def _inverted_status_from_bool(self, value: bool | None) -> str:
        if value is True:
            return "fail"
        if value is False:
            return "pass"
        return "uncertain"

    def _required_status(self, values: list[bool | None]) -> str:
        if any(value is False for value in values):
            return "fail"
        if values and all(value is True for value in values):
            return "pass"
        return "uncertain"

    def _match_text(self, value: bool | None) -> str:
        if value is True:
            return "一致"
        if value is False:
            return "不一致"
        return "待确认"

    def _correct_error_text(self, matches: bool | None, *, inverted: bool = False) -> str:
        if matches is None:
            return "待确认"
        correct = not matches if inverted else matches
        return "正确" if correct else "错误"

    def _check4_conclusion(self, status: str) -> str:
        return {
            "pass": "z1、z2区域内容均保持单行文本显示",
            "fail": "z1或z2区域存在非单行文本，或未识别到目标二级Tab内容",
            "uncertain": "z1、z2区域的单行显示状态存在无法确认项",
        }[status]

    def _check5_conclusion(self, status: str) -> str:
        return {
            "pass": "z1、z2区域均只有一个选中态，且选中态内容一致",
            "fail": "z1或z2区域不是唯一选中态，或两处选中内容不一致",
            "uncertain": "z1、z2区域的唯一选中态或内容一致性无法确认",
        }[status]

    def _check6_conclusion(self, status: str, facts: dict[str, dict[str, Any]]) -> str:
        if status == "pass":
            return "z1、z2均可横向滑动，且滑动后区域外主要内容保持不变"
        if status == "uncertain":
            return "至少一个区域的横向滑动或区域外稳定性无法确认"
        failed = []
        for region in ("z1", "z2"):
            if facts[region]["content_moved_horizontally"] is False:
                failed.append(f"{region}区域内容未横向变化")
            if facts[region]["outside_region_unchanged"] is False:
                failed.append(f"{region}区域外内容发生变化")
        return "；".join(failed) or "横向滑动要求未通过"


    def _summarize(self, checks: dict[str, dict[str, Any]]) -> dict[str, Any]:
        counts = {status: 0 for status in ("pass", "fail", "uncertain")}
        for check in checks.values():
            counts[check["status"]] += 1
        status = "fail" if counts["fail"] else "uncertain" if counts["uncertain"] else "pass"
        conclusion = {
            "pass": "二级Tab组件6项检查全部通过",
            "fail": f"二级Tab组件发现{counts['fail']}项不符合要求",
            "uncertain": f"二级Tab组件有{counts['uncertain']}项无法确认",
        }[status]
        return {"status": status, "counts": counts, "conclusion": conclusion}

    def _normalize_bbox(self, value: Any) -> list[int] | None:
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            return None
        result = []
        for item in value:
            if isinstance(item, bool):
                return None
            try:
                number = float(item)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(number):
                return None
            result.append(round(max(0, min(1000, number))))
        if result[2] <= result[0] or result[3] <= result[1]:
            return None
        return result

    def _map_bbox(self, bbox: list[int], region_box: list[int]) -> list[int]:
        left, top, right, bottom = region_box
        width, height = right - left, bottom - top
        return [
            left + round(bbox[0] * width / 1000),
            top + round(bbox[1] * height / 1000),
            left + round(bbox[2] * width / 1000),
            top + round(bbox[3] * height / 1000),
        ]

    def _region_box(
        self,
        region: str,
        width: int,
        z1_top: int,
        z1_bottom: int,
    ) -> tuple[int, int, int, int]:
        if region == "z1":
            return 0, z1_top, width, z1_bottom
        return 0, Z23_TOP, width, Z23_BOTTOM

    def _frame_region(self, frame_key: str) -> str:
        return frame_key.split("_", 1)[0]

    def _frame_label(self, frame_key: str) -> str:
        if frame_key == "z3_before":
            return "z3 页面回退400px后"
        suffix = "横滑前" if frame_key.endswith("_before") else "左滑400px后"
        return f"{self._frame_region(frame_key)} {suffix}"

    def _state_label(self, state: str) -> str:
        return {
            "selected": "选中态",
            "unselected": "非选中态",
            "special": "第二按钮特殊态",
        }.get(state, "待确认")

    def _optional_bool(self, value: Any) -> bool | None:
        return value if isinstance(value, bool) else None

    def _object(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _text(self, value: Any) -> str:
        return value.strip() if isinstance(value, str) else ""

    def _texts(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [self._text(item) for item in value if self._text(item)]

    def _normalize_text(self, value: str) -> str:
        return re.sub(r"\s+", "", value)

    def _hex(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip().upper()
        if re.fullmatch(r"#[0-9A-F]{6}", normalized):
            return normalized
        if re.fullmatch(r"#[0-9A-F]{3}", normalized):
            return "#" + "".join(character * 2 for character in normalized[1:])
        return None

    def _rgb_hex(self, value: tuple[int, int, int]) -> str:
        return "#{:02X}{:02X}{:02X}".format(*value)


jd_secondary_tab_analyzer = JdSecondaryTabAnalyzer()
