from app import models
from app.services.llm_analyzer import analyzer


def _asset_label(index: int, asset: models.ComparisonAsset) -> str:
    parts = [
        f"图{index}",
        asset.display_name,
        asset.source_app,
        asset.scenario,
    ]
    return " / ".join(str(part).strip() for part in parts if part)


def _asset_file_path(asset: models.ComparisonAsset) -> str:
    if asset.image_id and asset.image and asset.image.file_path:
        return asset.image.file_path
    if asset.file_path:
        return asset.file_path
    raise ValueError(f"Comparison asset {asset.id} has no file")


def _build_prompt(
    assets: list[models.ComparisonAsset],
    skill: models.ComparisonSkill,
    focus_question: str | None,
) -> str:
    labels = "\n".join(_asset_label(index, asset) for index, asset in enumerate(assets, start=1))
    prompt = f"""你是电商竞品对比分析专家。请基于用户选择的多张截图输出中文对比分析报告。

分析 Skill：
{skill.prompt}

图片清单：
{labels}
"""
    if focus_question:
        prompt += f"\n用户关注问题：{focus_question.strip()}\n"
    prompt += """
输出要求：
1. 用 Markdown 输出。
2. 包含：一句话结论、关键差异表、逐图洞察、可借鉴机会、下一步建议。
3. 每条重要结论都要标注对应图片编号，例如“图1”。
4. 不要编造截图中看不到的信息。
"""
    return prompt


class CompareAnalyzer:
    async def generate_report(
        self,
        assets: list[models.ComparisonAsset],
        skill: models.ComparisonSkill,
        focus_question: str | None = None,
    ) -> str:
        if len(assets) < 1:
            raise ValueError("At least one asset is required")
        if not analyzer.providers:
            raise RuntimeError("VLM_API_KEY, PHONE_AGENT_API_KEY or OPENAI_API_KEY not configured")

        prompt = _build_prompt(assets, skill, focus_question)
        images = [analyzer._encode_image(_asset_file_path(asset)) for asset in assets]
        report = await self._complete(prompt, images)
        if not report:
            raise RuntimeError("Compare report is empty")
        return report

    async def _complete(self, prompt: str, base64_images: list[str]) -> str:
        last_error = None
        for index, provider in enumerate(analyzer.providers):
            try:
                return await self._chat_with_provider(provider, prompt, base64_images)
            except Exception as exc:
                last_error = exc
                if index < len(analyzer.providers) - 1:
                    continue
                raise
        raise RuntimeError(f"Compare report request failed: {last_error}")

    def _chat_payload(self, provider: dict[str, str], prompt: str, base64_images: list[str]) -> dict:
        if not base64_images:
            raise ValueError("At least one image is required")
        payload = analyzer._chat_payload(provider, prompt, base64_images[0])
        payload["messages"][0]["content"] = [
            {"type": "text", "text": prompt},
            *(
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}}
                for image in base64_images
            ),
        ]
        payload["max_tokens"] = 4096
        return payload

    async def _chat_with_provider(self, provider: dict[str, str], prompt: str, base64_images: list[str]) -> str:
        import httpx

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{provider['base_url']}/chat/completions",
                headers={"Authorization": f"Bearer {provider['api_key']}"},
                json=self._chat_payload(provider, prompt, base64_images),
                timeout=180.0,
            )
            analyzer._raise_for_status_with_detail(response)
            return analyzer._strip_finish_wrapper(analyzer._response_content(response.text)).strip()


compare_analyzer = CompareAnalyzer()
