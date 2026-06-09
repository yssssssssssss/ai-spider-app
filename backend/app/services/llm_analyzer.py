import json
import base64
import httpx
import os
import re
from io import BytesIO
from typing import Any, Optional, Tuple
from PIL import Image
from app.config import settings
from app.services.task_planner import chat_completion_options

MAX_VLM_IMAGE_SIDE = 2048

ANALYSIS_PROMPT = """你现在只是一名电商截图分析器，不要操作手机，不要输出[finish]或finish(...)，不要解释你的思考。
请观察图片并只输出一个JSON对象：
{
  "design_analysis": "从UI设计角度分析布局、配色、视觉层级、信息架构、交互细节，120-250字",
  "ops_analysis": "从运营策略角度分析促销手段、文案策略、价格策略、用户引导、转化漏斗，120-250字"
}
如果截图内容较少，也必须分别给出design_analysis和ops_analysis。"""

TARGET_PAGE_PROMPT = """你现在只判断截图是否符合用户要采集的目标页面，不做设计/运营分析。
请只输出一个JSON对象：
{
  "is_target": true,
  "reason": "一句话说明为什么符合或不符合"
}
判断标准：截图必须已经到达用户指定的目标场景，并且画面内容和关键词/关注点、关注问题明显相关。启动页、权限页、搜索中间页、加载页、无关页面都不是目标页面。"""

PAGE_EVIDENCE_PROMPT = """你现在只做电商截图的目标识别与证据提取，不做设计/运营分析，不操作手机。
请根据“用户需求上下文”和“目标定义”判断当前截图是否命中其中一个目标，并只输出一个JSON对象：
{
  "matched_target_key": "命中的target_key；如果没有合适目标则为空字符串",
  "matched_target_name": "命中的目标名称；如果没有合适目标则为空字符串",
  "matched_goal_labels": ["命中的目标截图清单label；只能使用目标定义里给出的label"],
  "confidence": 0.0,
  "page_state": "loading | app_home | target_page | intermediate | wrong_page",
  "target_role": "home | promo_entry | promo_module | promo_channel | product_detail | other",
  "is_terminal_target": false,
  "needs_more_wait": false,
  "visible_text": ["截图中可见且与判断有关的文字"],
  "strong_evidence": ["页面标题、频道/会场/商品流、核心利益点、任务意图一致等强证据"],
  "weak_evidence": ["只有局部相似、入口相似、泛化推荐等弱证据"],
  "negative_evidence": ["说明不应匹配的反证；没有则为空数组"],
  "reason": "一句话说明判断依据"
}
要求：
1. matched_target_key 必须来自目标定义；不确定时返回空字符串。
2. matched_goal_labels 只能来自目标定义中的 goal_labels。
3. 不要求页面标题与目标名称完全一致；如果业务角色、可见内容和用户任务意图等价，可以匹配。
4. 不能只凭单个泛化词高置信匹配；高置信需要至少一个强证据。
5. 如果目标定义说明接受完整业务模块，则当前页中完整露出同名/等价业务模块也可作为终态：需要同时看到模块标题、多个商品/权益/活动项、核心利益点；单个入口按钮、“更多”按钮、单张卡片、加载态不算终态。
6. is_terminal_target 只能在截图已经停留到用户要求的最终截图页面时为 true；入口、搜索过程、加载态、跳转中、错误页必须为 false。完整业务模块满足上一条时可为 true。
7. needs_more_wait 表示页面仍在加载、跳转、弹窗遮挡或需要继续操作，不应作为最终截图。
8. confidence范围为0到1；0.8以上表示强匹配，0.45-0.79表示弱匹配，低于0.45表示不匹配。
9. 不要输出Markdown，不要输出解释。"""

DEFAULT_AB_SKILL_SNAPSHOTS = [
    {
        "skill_id": "default_design",
        "name": "设计维度",
        "instruction_md": "对比两张图的布局、视觉层级、信息密度、关键入口和交互引导差异。",
    },
    {
        "skill_id": "default_ops",
        "name": "运营维度",
        "instruction_md": "对比两张图的利益点表达、价格/补贴策略、转化路径和用户行动引导差异。",
    },
]


def _effective_skill_snapshots(skill_snapshots: list[dict] | None) -> list[dict]:
    return skill_snapshots or DEFAULT_AB_SKILL_SNAPSHOTS


def normalize_dynamic_analysis_result(parsed: dict | None, skill_snapshots: list[dict]) -> dict:
    skill_snapshots = _effective_skill_snapshots(skill_snapshots)
    expected_names = [snapshot.get("name") for snapshot in skill_snapshots if snapshot.get("name")]
    rows = parsed.get("results", []) if isinstance(parsed, dict) else []
    results = []
    errors = []
    by_name = {
        str(row.get("skill_name") or row.get("name") or ""): row
        for row in rows
        if isinstance(row, dict)
    }
    for snapshot in skill_snapshots:
        name = str(snapshot.get("name") or "")
        row = by_name.get(name)
        analysis = str((row or {}).get("analysis") or "").strip()
        item = {
            "skill_id": str(snapshot.get("skill_id") or ""),
            "skill_name": name,
            "analysis": analysis,
        }
        if analysis:
            results.append(item)
        else:
            item["error"] = "模型未返回该维度"
            errors.append(item)
    design = next((row["analysis"] for row in results if row["skill_name"] == "设计维度"), "")
    ops = next((row["analysis"] for row in results if row["skill_name"] == "运营维度"), "")
    status_value = "success" if len(results) == len(expected_names) else ("partial" if results else "failed")
    return {
        "design_analysis": design,
        "ops_analysis": ops,
        "custom_analysis_json": {"results": results, "errors": errors},
        "status": status_value,
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
        if settings.OPENAI_API_KEY:
            providers.append({
                "name": "openai",
                "api_key": settings.OPENAI_API_KEY,
                "base_url": settings.OPENAI_BASE_URL.rstrip("/"),
                "model": settings.VLM_MODEL,
            })
        if settings.PHONE_AGENT_API_KEY:
            providers.append({
                "name": "modelscope_vlm",
                "api_key": settings.PHONE_AGENT_API_KEY,
                "base_url": settings.PHONE_AGENT_BASE_URL.rstrip("/"),
                "model": settings.MODELSCOPE_VLM_MODEL,
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
        m = re.search(r'(\{.*(?:"design_analysis".*"ops_analysis"|"results").*\})', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass
        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                parsed, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
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

    def _build_analysis_prompt(self, context: Optional[dict] = None) -> str:
        context_lines = self._context_lines(context)
        if not context_lines:
            return ANALYSIS_PROMPT
        return ANALYSIS_PROMPT + "\n\n用户需求上下文：\n" + "\n".join(context_lines)

    def _build_dynamic_analysis_prompt(self, skill_snapshots: list[dict], context: Optional[dict] = None) -> str:
        skill_lines = []
        for index, snapshot in enumerate(skill_snapshots, start=1):
            skill_lines.append(f"{index}. {snapshot.get('name')}\n{snapshot.get('instruction_md')}")
        context_lines = self._context_lines(context)
        context_block = "\n".join(context_lines) if context_lines else "无"
        return """你现在只是一名电商截图分析器，不要操作手机，不要输出[finish]或finish(...)，不要解释你的思考。
请根据每个分析 skill 分别观察图片，并只输出一个JSON对象：
{
  "results": [
    {"skill_name": "技能名称", "analysis": "该技能对应的120-250字分析内容"}
  ]
}
要求：
1. 每个输入 skill 都必须返回一条 results。
2. skill_name 必须与输入名称完全一致。
3. 不要输出 Markdown，不要输出解释。
4. 如果截图信息不足，也要说明无法判断的原因。

用户需求上下文：
""" + context_block + "\n\n分析 skill：\n" + "\n\n".join(skill_lines)

    def _build_target_page_prompt(self, context: Optional[dict] = None) -> str:
        context_lines = self._context_lines(context)
        if not context_lines:
            return TARGET_PAGE_PROMPT
        return TARGET_PAGE_PROMPT + "\n\n用户需求上下文：\n" + "\n".join(context_lines)

    def _build_page_evidence_prompt(self, targets: list[dict], context: Optional[dict] = None) -> str:
        context_lines = self._context_lines(context)
        context_block = "\n".join(context_lines) if context_lines else "无"
        return (
            PAGE_EVIDENCE_PROMPT
            + "\n\n用户需求上下文：\n"
            + context_block
            + "\n\n目标定义：\n"
            + json.dumps(targets, ensure_ascii=False, indent=2)
        )

    def _extract_target_result(self, text: str) -> tuple[bool, str]:
        content = self._strip_finish_wrapper(text)
        parsed = self._extract_json(content)
        if parsed is None:
            lowered = content.lower()
            return ("true" in lowered or "符合" in content, content[:200])
        return bool(parsed.get("is_target")), str(parsed.get("reason") or "")

    def _normalize_page_evidence(self, parsed: dict[str, Any] | None, targets: list[dict], content: str) -> dict[str, Any]:
        parsed = parsed if isinstance(parsed, dict) else {}
        valid_keys = {str(target.get("target_key") or "") for target in targets if target.get("target_key")}
        target_by_key = {str(target.get("target_key") or ""): target for target in targets if target.get("target_key")}
        label_by_norm: dict[str, str] = {}
        for target in targets:
            for label in target.get("goal_labels") or []:
                clean_label = " ".join(str(label or "").split())
                if clean_label:
                    label_by_norm["".join(clean_label.lower().split())] = clean_label

        def texts(value: Any) -> list[str]:
            if isinstance(value, list):
                raw = value
            elif value:
                raw = [value]
            else:
                raw = []
            return [" ".join(str(item or "").split()) for item in raw if " ".join(str(item or "").split())]

        def bool_value(value: Any) -> bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "y", "是"}
            return bool(value)

        matched_key = str(parsed.get("matched_target_key") or parsed.get("slot_key") or "").strip()
        if matched_key not in valid_keys:
            matched_key = ""
        matched_target = target_by_key.get(matched_key) or {}
        matched_name = str(parsed.get("matched_target_name") or matched_target.get("target_name") or "").strip()
        if matched_key and not matched_name:
            matched_name = str(matched_target.get("target_name") or "")

        matched_labels = []
        seen_labels = set()
        for label in texts(parsed.get("matched_goal_labels")):
            canonical = label_by_norm.get("".join(label.lower().split()))
            if canonical and canonical not in seen_labels:
                seen_labels.add(canonical)
                matched_labels.append(canonical)

        try:
            confidence = float(parsed.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        page_state = str(parsed.get("page_state") or "").strip().lower()
        if page_state not in {"loading", "app_home", "target_page", "intermediate", "wrong_page"}:
            page_state = ""
        target_role = str(parsed.get("target_role") or "").strip().lower()
        if target_role not in {"home", "promo_entry", "promo_module", "promo_channel", "product_detail", "other"}:
            target_role = "other"

        return {
            "matched_target_key": matched_key,
            "matched_target_name": matched_name,
            "matched_goal_labels": matched_labels,
            "confidence": max(0.0, min(1.0, confidence)),
            "page_state": page_state,
            "target_role": target_role,
            "is_terminal_target": bool_value(parsed.get("is_terminal_target", False)),
            "needs_more_wait": bool_value(parsed.get("needs_more_wait", False)),
            "visible_text": texts(parsed.get("visible_text")),
            "strong_evidence": texts(parsed.get("strong_evidence")),
            "weak_evidence": texts(parsed.get("weak_evidence")),
            "negative_evidence": texts(parsed.get("negative_evidence")),
            "reason": str(parsed.get("reason") or content[:200]).strip(),
        }

    async def _chat_with_provider(self, provider: dict[str, str], prompt: str, base64_image: str) -> str:
        return await self._chat_with_provider_images(provider, prompt, [base64_image])

    async def _chat_with_provider_images(self, provider: dict[str, str], prompt: str, base64_images: list[str]) -> str:
        content = [{"type": "text", "text": prompt}]
        content.extend(
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}}
            for image in base64_images
        )
        messages = [
            {
                "role": "user",
                "content": content
            }
        ]
        payload = chat_completion_options(
            base_url=provider["base_url"],
            model_name=provider["model"],
            model=provider["model"],
            messages=messages,
            temperature=0.1,
            max_tokens=2048,
            stream=False,
        )
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{provider['base_url']}/chat/completions",
                headers={"Authorization": f"Bearer {provider['api_key']}"},
                json=payload,
                timeout=120.0
            )
            resp.raise_for_status()
            return self._response_content(resp.text)

    async def _complete_with_fallback(self, prompt: str, base64_image: str) -> str:
        return await self._complete_images_with_fallback(prompt, [base64_image])

    async def _complete_images_with_fallback(self, prompt: str, base64_images: list[str]) -> str:
        last_error = None
        for index, provider in enumerate(self.providers):
            try:
                return await self._chat_with_provider_images(provider, prompt, base64_images)
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

    async def extract_page_evidence(self, image_path: str, targets: list[dict], context: Optional[dict] = None) -> dict:
        if not targets:
            return {}
        if not self.providers:
            raise RuntimeError("VLM_API_KEY, PHONE_AGENT_API_KEY or OPENAI_API_KEY not configured")

        base64_image = self._encode_image(image_path)
        content = await self._complete_with_fallback(self._build_page_evidence_prompt(targets, context), base64_image)
        content = self._strip_finish_wrapper(content)
        return self._normalize_page_evidence(self._extract_json(content), targets, content)

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

    async def analyze_with_skills(self, image_path: str, skill_snapshots: list[dict], context: Optional[dict] = None) -> dict:
        if not skill_snapshots:
            design, ops, status = await self.analyze(image_path, context=context)
            return {
                "design_analysis": design or "",
                "ops_analysis": ops or "",
                "custom_analysis_json": {},
                "status": status,
            }
        if not self.providers:
            raise RuntimeError("VLM_API_KEY, PHONE_AGENT_API_KEY or OPENAI_API_KEY not configured")

        base64_image = self._encode_image(image_path)
        prompt = self._build_dynamic_analysis_prompt(skill_snapshots, context)
        content = await self._complete_with_fallback(prompt, base64_image)
        content = self._strip_finish_wrapper(content)
        parsed = self._extract_json(content)
        if not parsed:
            parsed = {"results": [{"skill_name": skill_snapshots[0].get("name"), "analysis": content}]}
        return normalize_dynamic_analysis_result(parsed, skill_snapshots)

    async def match_comparison_slot(self, image_path: str, slots: list[dict], context: Optional[dict] = None) -> dict:
        if not self.providers:
            raise RuntimeError("VLM_API_KEY, PHONE_AGENT_API_KEY or OPENAI_API_KEY not configured")
        slot_lines = "\n".join(
            f"- slot_key: {slot.get('slot_key')}\n  name: {slot.get('name')}\n  description: {slot.get('description')}"
            for slot in slots
        )
        context_lines = self._context_lines(context)
        prompt = """你现在只判断截图命中哪个对照槽位，不做设计/运营分析。
请只输出一个JSON对象：
{
  "slot_key": "命中的slot_key；如果没有合适槽位则为空字符串",
  "confidence": 0.0,
  "reason": "一句话说明判断依据"
}
要求：
1. confidence范围为0到1。
2. 只有截图明确符合某个槽位描述时才给高置信。
3. 不要输出Markdown，不要输出解释。

用户需求上下文：
""" + ("\n".join(context_lines) if context_lines else "无") + "\n\n对照槽位：\n" + slot_lines
        base64_image = self._encode_image(image_path)
        content = await self._complete_with_fallback(prompt, base64_image)
        content = self._strip_finish_wrapper(content)
        parsed = self._extract_json(content) or {}
        try:
            confidence = float(parsed.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        return {
            "slot_key": str(parsed.get("slot_key") or "").strip(),
            "confidence": max(0.0, min(1.0, confidence)),
            "reason": str(parsed.get("reason") or content[:200]).strip(),
        }

    async def analyze_pair_with_skills(
        self,
        a_image_path: str,
        jd_image_path: str,
        skill_snapshots: list[dict],
        context: Optional[dict] = None,
    ) -> dict:
        skill_snapshots = _effective_skill_snapshots(skill_snapshots)
        if not self.providers:
            raise RuntimeError("VLM_API_KEY, PHONE_AGENT_API_KEY or OPENAI_API_KEY not configured")
        skill_lines = []
        for index, snapshot in enumerate(skill_snapshots, start=1):
            skill_lines.append(f"{index}. {snapshot.get('name')}\n{snapshot.get('instruction_md')}")
        context_lines = self._context_lines(context)
        prompt = """你是一名电商竞品AB对照分析器。第一张图是A侧竞品截图，第二张图是京东截图。
请对两张图在同一对照槽位下进行逐张对比，并只输出一个JSON对象：
{
  "results": [
    {"skill_name": "技能名称", "analysis": "该技能对应的AB对比分析，120-250字"}
  ]
}
要求：
1. 每个输入skill都必须返回一条results。
2. skill_name必须与输入名称完全一致。
3. 不要评价图片中没有出现的内容。
4. 如果某个维度无法判断，说明无法判断的原因。
5. 不要输出Markdown，不要输出解释。

用户需求上下文：
""" + ("\n".join(context_lines) if context_lines else "无") + "\n\n分析 skill：\n" + "\n\n".join(skill_lines)
        a_base64 = self._encode_image(a_image_path)
        jd_base64 = self._encode_image(jd_image_path)
        content = await self._complete_images_with_fallback(prompt, [a_base64, jd_base64])
        content = self._strip_finish_wrapper(content)
        parsed = self._extract_json(content)
        if not parsed:
            parsed = {"results": [{"skill_name": skill_snapshots[0].get("name"), "analysis": content}]} if skill_snapshots else {"results": []}
        return normalize_dynamic_analysis_result(parsed, skill_snapshots)

analyzer = LLMAnalyzer()
