from __future__ import annotations

import base64
import json
import re
from dataclasses import asdict, dataclass
from io import BytesIO
from typing import Protocol

from PIL import Image, UnidentifiedImageError

from app.services.llm_analyzer import MAX_VLM_IMAGE_SIDE, analyzer


PROMOTION_DETECTION_PROMPT = """你是移动端 UI 视觉检测器。检测图片右下角是否存在悬浮在页面内容上方的促销贴片；不要把底部导航栏、普通商品卡片或页面原生模块当作贴片。
只输出一个 JSON 对象，不要 Markdown：
{
  "promo_present": true,
  "promo_state": "expanded|collapsed|none|uncertain",
  "promo_bbox_norm": [x1,y1,x2,y2],
  "promo_description": "可见文字和外观",
  "close_button_present": true,
  "close_button_bbox_norm": [x1,y1,x2,y2],
  "close_button_description": "关闭按钮外观",
  "confidence": 0.0
}
所有 bbox 使用 0-1000 归一化坐标，左上角为 (0,0)，右下角为 (1000,1000)。贴片 bbox 必须完整包住贴片。没有贴片或关闭按钮时，对应 bbox 返回 null。"""


class ImageCompletion(Protocol):
    providers: list

    async def complete_images(self, prompt: str, images: list[str], preferred_provider: str | None = None) -> str: ...


@dataclass(frozen=True)
class PromotionDetection:
    promo_present: bool
    promo_state: str
    promo_bbox_norm: list[int] | None
    promo_description: str
    close_button_present: bool
    close_button_below_promo: bool
    close_button_bbox_norm: list[int] | None
    close_button_description: str
    confidence: float
    image_width: int
    image_height: int

    def to_dict(self) -> dict:
        return asdict(self)


class PromotionDetector:
    """Detect promotion overlays behind one small interface."""

    def __init__(self, image_completion: ImageCompletion = analyzer):
        self.image_completion = image_completion

    async def detect_png(self, content: bytes) -> PromotionDetection:
        encoded, width, height = self._encode_png(content)
        if not self.image_completion.providers:
            raise RuntimeError("No image-capable LLM provider configured")
        full_payload = await self._complete_payload(PROMOTION_DETECTION_PROMPT, encoded)
        full_result = self._detection_from_payload(full_payload, width, height)
        if full_result.promo_present:
            return full_result

        crop_encoded = self._encode_bottom_right_crop(content)
        crop_payload = await self._complete_payload(
            PROMOTION_DETECTION_PROMPT
            + "\n当前图片已经是原图右下区域裁剪图；请在这张裁剪图内检测贴片，bbox 仍相对当前裁剪图使用 0-1000 坐标。",
            crop_encoded,
        )
        crop_payload["promo_bbox_norm"] = self._map_crop_bbox(crop_payload.get("promo_bbox_norm"))
        crop_payload["close_button_bbox_norm"] = self._map_crop_bbox(crop_payload.get("close_button_bbox_norm"))
        crop_result = self._detection_from_payload(crop_payload, width, height)
        return crop_result if crop_result.promo_present else full_result

    async def _complete_payload(self, prompt: str, encoded: str) -> dict:
        response = await self.image_completion.complete_images(
            prompt,
            [encoded],
            preferred_provider="openai",
        )
        return self._parse_json(response)

    def _detection_from_payload(self, payload: dict, width: int, height: int) -> PromotionDetection:
        present = bool(payload.get("promo_present"))
        promo_bbox = self._normalize_bbox(payload.get("promo_bbox_norm")) if present else None
        present = present and promo_bbox is not None and self._is_bottom_right(promo_bbox)
        if not present:
            promo_bbox = None
        state = str(payload.get("promo_state") or ("uncertain" if present else "none")).lower()
        if state not in {"expanded", "collapsed", "none", "uncertain"}:
            state = "uncertain" if present else "none"
        close_bbox = self._normalize_bbox(payload.get("close_button_bbox_norm"))
        close_present = present and bool(payload.get("close_button_present")) and close_bbox is not None
        close_below = present and close_present and self._is_close_below_promo(promo_bbox, close_bbox)
        if present and promo_bbox:
            if close_present and promo_bbox[2] < 995:
                state = "expanded"
            elif promo_bbox[2] >= 995 and not close_present:
                state = "collapsed"
        try:
            confidence = max(0.0, min(1.0, float(payload.get("confidence") or 0.0)))
        except (TypeError, ValueError):
            confidence = 0.0
        return PromotionDetection(
            promo_present=present,
            promo_state=state if present else "none",
            promo_bbox_norm=promo_bbox,
            promo_description=str(payload.get("promo_description") or "") if present else "",
            close_button_present=close_present,
            close_button_below_promo=close_below,
            close_button_bbox_norm=close_bbox if close_present else None,
            close_button_description=str(payload.get("close_button_description") or "") if close_present else "",
            confidence=confidence,
            image_width=width,
            image_height=height,
        )

    def _encode_png(self, content: bytes) -> tuple[str, int, int]:
        if not content:
            raise ValueError("Image content is empty")
        try:
            with Image.open(BytesIO(content)) as image:
                image.load()
                width, height = image.size
                if width < 1 or height < 1:
                    raise ValueError("Image dimensions are invalid")
                converted = image.convert("RGB")
                if max(width, height) > MAX_VLM_IMAGE_SIDE:
                    ratio = MAX_VLM_IMAGE_SIDE / max(width, height)
                    converted = converted.resize(
                        (max(1, int(width * ratio)), max(1, int(height * ratio))),
                        Image.Resampling.LANCZOS,
                    )
                buffer = BytesIO()
                converted.save(buffer, format="PNG", optimize=True)
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("Unsupported image content") from exc
        return base64.b64encode(buffer.getvalue()).decode("ascii"), width, height

    def _encode_bottom_right_crop(self, content: bytes) -> str:
        try:
            with Image.open(BytesIO(content)) as image:
                image.load()
                width, height = image.size
                crop = image.convert("RGB").crop((int(width * 0.60), int(height * 0.55), width, height))
                if max(crop.size) > MAX_VLM_IMAGE_SIDE:
                    ratio = MAX_VLM_IMAGE_SIDE / max(crop.size)
                    crop = crop.resize(
                        (max(1, int(crop.width * ratio)), max(1, int(crop.height * ratio))),
                        Image.Resampling.LANCZOS,
                    )
                buffer = BytesIO()
                crop.save(buffer, format="PNG", optimize=True)
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("Unsupported image content") from exc
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def _map_crop_bbox(self, value) -> list[int] | None:
        bbox = self._normalize_bbox(value)
        if bbox is None:
            return None
        x1, y1, x2, y2 = bbox
        return [
            round(600 + x1 * 0.40),
            round(550 + y1 * 0.45),
            round(600 + x2 * 0.40),
            round(550 + y2 * 0.45),
        ]

    def _parse_json(self, text: str) -> dict:
        candidate = text.strip()
        fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", candidate, re.DOTALL)
        if fenced:
            candidate = fenced.group(1)
        else:
            start, end = candidate.find("{"), candidate.rfind("}")
            if start >= 0 and end > start:
                candidate = candidate[start : end + 1]
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise ValueError("Promotion detector returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("Promotion detector result must be an object")
        return payload

    def _is_close_below_promo(self, promo_bbox: list[int], close_bbox: list[int]) -> bool:
        promo_x1, _promo_y1, promo_x2, promo_y2 = promo_bbox
        close_x1, close_y1, close_x2, _close_y2 = close_bbox
        close_center_x = (close_x1 + close_x2) / 2
        return promo_x1 - 50 <= close_center_x <= promo_x2 + 50 and promo_y2 <= close_y1 <= promo_y2 + 120

    def _is_bottom_right(self, bbox: list[int]) -> bool:
        x1, y1, _x2, _y2 = bbox
        return x1 >= 700 and y1 >= 650

    def _normalize_bbox(self, value) -> list[int] | None:
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            return None
        try:
            x1, y1, x2, y2 = (max(0, min(1000, int(round(float(item))))) for item in value)
        except (TypeError, ValueError):
            return None
        if x2 <= x1 or y2 <= y1:
            return None
        return [x1, y1, x2, y2]


promotion_detector = PromotionDetector()
