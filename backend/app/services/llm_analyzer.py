import json
import base64
import httpx
import os
import re
from io import BytesIO
from typing import Optional, Tuple
from PIL import Image
from app.config import settings

MAX_VLM_IMAGE_SIDE = 2048

DEFAULT_PROMPT_PROFILE = "default"
WATCH_PROMPT_PROFILE = "watch"

ANALYSIS_PROMPT = """你现在只是一名电商截图分析器，不要操作手机，不要输出[finish]或finish(...)，不要解释你的思考。
请观察图片并只输出一个JSON对象：
{
  "design_analysis": "从UI设计角度分析布局、配色、视觉层级、信息架构、交互细节，120-250字",
  "ops_analysis": "从运营策略角度分析促销手段、文案策略、价格策略、用户引导、转化漏斗，120-250字"
}
如果截图内容较少，也必须分别给出design_analysis和ops_analysis。"""

WATCH_ANALYSIS_PROMPT = """你现在只是一名电商固定页面持续观察截图分析器，不要操作手机，不要输出[finish]或finish(...)，不要解释你的思考。
请围绕固定页面首屏的长期可比性进行分析，并只输出一个JSON对象：
{
  "design_analysis": "从UI设计角度分析首屏布局、视觉层级、核心入口、活动模块、商品信息密度和可复用对比点，120-250字",
  "ops_analysis": "从运营策略角度分析首屏利益点、促销节奏、转化入口、商品推荐策略、用户激励和可持续观察信号，120-250字"
}
如果截图内容较少，也必须分别给出design_analysis和ops_analysis。"""

TARGET_PAGE_PROMPT = """你现在只判断截图是否符合用户要采集的目标页面，不做设计/运营分析。
请只输出一个JSON对象：
{
  "is_target": true,
  "reason": "一句话说明为什么符合或不符合"
}
判断标准：截图必须已经到达用户指定的目标场景，并且画面内容和关键词/关注点、关注问题明显相关。启动页、权限页、登录页、加载页、搜索中间页、无关页面都不是目标页面。"""

WATCH_TARGET_PAGE_PROMPT = """你现在只判断持续观察截图是否符合固定页面观察目标，不做设计/运营分析。
请只输出一个JSON对象：
{
  "is_target": true,
  "reason": "一句话说明为什么符合或不符合"
}
判断标准：
1. 以目标App和目标场景为硬条件，关注问题只作为后续分析方向，不作为判定截图无效的硬条件。
2. 对首页、频道页、活动页、信息流首屏，只要页面框架、导航栏、频道名、活动入口或首屏内容能说明已到达目标场景，就应判定为目标页面。
3. 搜索结果页只有在目标场景明确要求搜索结果时才判定为目标页面；不要仅因为页面有搜索框或商品列表就判定为搜索结果页。
4. 启动页、权限页、登录页、加载页、无关App、无关频道和明显未到达目标场景的中间页都不是目标页面。"""

ANALYSIS_PROMPTS = {
    DEFAULT_PROMPT_PROFILE: ANALYSIS_PROMPT,
    WATCH_PROMPT_PROFILE: WATCH_ANALYSIS_PROMPT,
}

TARGET_PAGE_PROMPTS = {
    DEFAULT_PROMPT_PROFILE: TARGET_PAGE_PROMPT,
    WATCH_PROMPT_PROFILE: WATCH_TARGET_PAGE_PROMPT,
}

class LLMAnalyzer:
    def __init__(self):
        self.providers = self._build_providers()
        first = self.providers[0] if self.providers else None
        self.api_key = first["api_key"] if first else ""
        self.base_url = first["base_url"] if first else ""
        self.model = first["model"] if first else ""

    def _build_providers(self) -> list[dict[str, str]]:
        providers = []
        if settings.VLM_API_KEY:
            providers.append({
                "name": "vlm",
                "api_key": settings.VLM_API_KEY,
                "base_url": settings.VLM_BASE_URL.rstrip("/"),
                "model": settings.VLM_MODEL,
            })
        if settings.PHONE_AGENT_API_KEY:
            providers.append({
                "name": "modelscope_vlm",
                "api_key": settings.PHONE_AGENT_API_KEY,
                "base_url": settings.PHONE_AGENT_BASE_URL.rstrip("/"),
                "model": settings.MODELSCOPE_VLM_MODEL,
            })
        if settings.OPENAI_API_KEY:
            providers.append({
                "name": "openai",
                "api_key": settings.OPENAI_API_KEY,
                "base_url": settings.OPENAI_BASE_URL.rstrip("/"),
                "model": settings.VLM_MODEL,
            })
        return providers

    def _resolve_image_path(self, image_path: str) -> str:
        if os.path.isabs(image_path):
            return image_path
        return os.path.join(settings.PROJECT_ROOT, image_path)

    def _encode_image(self, image_path: str) -> str:
        resolved_path = self._resolve_image_path(image_path)
        with Image.open(resolved_path) as img:
            width, height = img.size
            if max(width, height) > MAX_VLM_IMAGE_SIDE:
                ratio = MAX_VLM_IMAGE_SIDE / max(width, height)
                new_size = (max(1, int(width * ratio)), max(1, int(height * ratio)))
                resized = img.resize(new_size, Image.Resampling.LANCZOS)
                buffer = BytesIO()
                resized.save(buffer, format="PNG", optimize=True)
                return base64.b64encode(buffer.getvalue()).decode("utf-8")

        with open(resolved_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _extract_json(self, text: str) -> Optional[dict]:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        m = re.search(r'(\{.*"design_analysis".*"ops_analysis".*\})', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        return None

    def _extract_chunked_content(self, text: str) -> str:
        decoder = json.JSONDecoder()
        pos = 0
        parts = []
        while pos < len(text):
            while pos < len(text) and text[pos].isspace():
                pos += 1
            if pos >= len(text):
                break
            obj, pos = decoder.raw_decode(text, pos)
            for choice in obj.get("choices", []):
                delta = choice.get("delta") or {}
                message = choice.get("message") or {}
                content = delta.get("content") or message.get("content")
                if content:
                    parts.append(content)
        if not parts:
            raise ValueError("No content found in chunked response")
        return "".join(parts)

    def _response_content(self, text: str) -> str:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return self._extract_chunked_content(text)

        choice = data["choices"][0]
        message = choice.get("message") or {}
        delta = choice.get("delta") or {}
        return message.get("content") or delta.get("content") or ""

    def _strip_finish_wrapper(self, text: str) -> str:
        match = re.search(r'finish\(message=(["\'])(.*)\1\)\s*$', text, re.DOTALL)
        if match:
            return match.group(2).replace("\\n", "\n")
        return text

    def _extract_text_sections(self, text: str) -> Optional[dict]:
        header = (
            r"(?:^|\n)\s*(?:[-*#]+\s*)*(?:\*\*)?{name}"
            r"(?:\s*[（(][^）)]*[）)])?\s*(?:[：:]\s*)?(?:\*\*)?"
        )
        design_header = header.format(name="(?:设计分析|design_analysis)")
        ops_header = header.format(name="(?:运营分析|ops_analysis)")
        match = re.search(design_header + r"(.*?)" + ops_header + r"(.*)", text, re.DOTALL | re.IGNORECASE)
        if not match:
            return None
        design = match.group(1).strip()
        ops = match.group(2).strip().rstrip(')"\'')
        if not design or not ops:
            return None
        return {"design_analysis": design, "ops_analysis": ops}

    def _context_lines(self, context: Optional[dict]) -> list[str]:
        if not context:
            return []
        lines = []
        if context.get("target_app"):
            lines.append(f"目标App：{context['target_app']}")
        if context.get("target_scenario"):
            lines.append(f"目标场景：{context['target_scenario']}")
        keywords = [k for k in context.get("keywords", []) if k]
        if keywords:
            lines.append(f"关键词/关注点：{'、'.join(keywords)}")
        if context.get("focus_question"):
            lines.append(f"关注问题：{context['focus_question']}")
        return lines

    def _prompt_profile(self, context: Optional[dict]) -> str:
        if not context:
            return DEFAULT_PROMPT_PROFILE
        profile = context.get("prompt_profile") or DEFAULT_PROMPT_PROFILE
        if profile in ANALYSIS_PROMPTS and profile in TARGET_PAGE_PROMPTS:
            return profile
        return DEFAULT_PROMPT_PROFILE

    def _build_analysis_prompt(self, context: Optional[dict] = None) -> str:
        context_lines = self._context_lines(context)
        base_prompt = ANALYSIS_PROMPTS[self._prompt_profile(context)]
        if not context_lines:
            return base_prompt
        return base_prompt + "\n\n用户需求上下文：\n" + "\n".join(context_lines)

    def _build_target_page_prompt(self, context: Optional[dict] = None) -> str:
        context_lines = self._context_lines(context)
        base_prompt = TARGET_PAGE_PROMPTS[self._prompt_profile(context)]
        if not context_lines:
            return base_prompt
        return base_prompt + "\n\n用户需求上下文：\n" + "\n".join(context_lines)

    def _extract_target_result(self, text: str) -> tuple[bool, str]:
        content = self._strip_finish_wrapper(text)
        parsed = self._extract_json(content)
        if parsed is None:
            lowered = content.lower()
            return ("true" in lowered or "符合" in content, content[:200])
        return bool(parsed.get("is_target")), str(parsed.get("reason") or "")

    async def _chat_with_provider(self, provider: dict[str, str], prompt: str, base64_image: str) -> str:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                ]
            }
        ]
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{provider['base_url']}/chat/completions",
                headers={"Authorization": f"Bearer {provider['api_key']}"},
                json={
                    "model": provider["model"],
                    "messages": messages,
                    "temperature": 0.1,
                    "max_tokens": 2048,
                    "stream": False
                },
                timeout=120.0
            )
            resp.raise_for_status()
            return self._response_content(resp.text)

    async def _complete_with_fallback(self, prompt: str, base64_image: str) -> str:
        last_error = None
        for index, provider in enumerate(self.providers):
            try:
                return await self._chat_with_provider(provider, prompt, base64_image)
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as e:
                last_error = e
                if index < len(self.providers) - 1:
                    print(f"⚠️ {provider['name']} 图片请求失败，尝试下一个服务: {e}")
                    continue
                raise
        raise RuntimeError(f"Image request failed: {last_error}")

    async def is_target_page(self, image_path: str, context: Optional[dict] = None) -> Tuple[bool, str]:
        if not self.providers:
            raise RuntimeError("VLM_API_KEY, PHONE_AGENT_API_KEY or OPENAI_API_KEY not configured")

        base64_image = self._encode_image(image_path)
        content = await self._complete_with_fallback(self._build_target_page_prompt(context), base64_image)
        return self._extract_target_result(content)

    async def analyze(self, image_path: str, context: Optional[dict] = None) -> Tuple[Optional[str], Optional[str], str]:
        if not self.providers:
            raise RuntimeError("VLM_API_KEY, PHONE_AGENT_API_KEY or OPENAI_API_KEY not configured")

        base64_image = self._encode_image(image_path)
        content = await self._complete_with_fallback(self._build_analysis_prompt(context), base64_image)
        content = self._strip_finish_wrapper(content)
        parsed = self._extract_json(content) or self._extract_text_sections(content)
        if parsed:
            return (
                parsed.get("design_analysis"),
                parsed.get("ops_analysis"),
                "success" if parsed.get("design_analysis") and parsed.get("ops_analysis") else "partial"
            )
        else:
            return (content, None, "partial")

analyzer = LLMAnalyzer()
