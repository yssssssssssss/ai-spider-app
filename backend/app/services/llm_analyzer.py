import json
import base64
import httpx
import re
from typing import Optional, Tuple
from app.config import settings

ANALYSIS_PROMPT = """你是一位电商竞品分析专家。请对以下截图进行双维度分析，输出为JSON格式：

{
  "design_analysis": "从UI设计角度分析（布局、配色、视觉层级、信息架构、交互细节等）",
  "ops_analysis": "从运营策略角度分析（促销手段、文案策略、价格策略、用户引导、转化漏斗等）"
}

要求：
- 每个维度200-500字
- 具体指出截图中的设计/运营亮点
- 如果是系列截图，请与前几张做对比分析（如有上下文）
"""

class LLMAnalyzer:
    def __init__(self):
        self.api_key = settings.VLM_API_KEY or settings.OPENAI_API_KEY
        self.base_url = settings.VLM_BASE_URL or settings.OPENAI_BASE_URL
        self.model = settings.VLM_MODEL

    def _encode_image(self, image_path: str) -> str:
        with open(image_path, "rb") as f:
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

    async def analyze(self, image_path: str) -> Tuple[Optional[str], Optional[str], str]:
        base64_image = self._encode_image(image_path)
        messages = [
            {"role": "system", "content": ANALYSIS_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "请分析这张电商截图，按要求的JSON格式输出。"},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{base64_image}"}}
                ]
            }
        ]
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.5,
                    "max_tokens": 2048
                },
                timeout=120.0
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]

        parsed = self._extract_json(content)
        if parsed:
            return (
                parsed.get("design_analysis"),
                parsed.get("ops_analysis"),
                "success" if parsed.get("design_analysis") and parsed.get("ops_analysis") else "partial"
            )
        else:
            return (content, None, "partial")

analyzer = LLMAnalyzer()
