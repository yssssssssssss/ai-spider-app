import httpx
from typing import List
from app.config import settings

DOUBAO_EMBEDDING_MODEL_ALIASES = {
    "Doubao-embedding": "doubao-embedding-vision-251215",
}


class Embedder:
    def __init__(self):
        if settings.use_doubao_embedding():
            self.api_key = settings.AI_MATCH_DOUBAO_EMBEDDING_API_KEY
            self.base_url = settings.AI_MATCH_DOUBAO_EMBEDDING_ENDPOINT.rstrip("/")
            self.model = settings.AI_MATCH_DOUBAO_EMBEDDING_MODEL or "Doubao-embedding"
            path = "embeddings/multimodal" if settings.use_doubao_multimodal_embedding() else "embeddings"
        else:
            self.api_key = (
                settings.EMBEDDING_API_KEY
                or settings.AI_MATCH_TEXT_EMBEDDING_API_KEY
                or settings.OPENAI_API_KEY
            )
            self.base_url = (
                settings.EMBEDDING_BASE_URL
                or settings.AI_MATCH_TEXT_EMBEDDING_ENDPOINT
                or settings.OPENAI_BASE_URL
            ).rstrip("/")
            self.model = settings.EMBEDDING_MODEL or settings.AI_MATCH_TEXT_EMBEDDING_MODEL or "text-embedding-3-small"
            path = "embeddings"
        self.embedding_url = f"{self.base_url}/{path}"
        self.dim = settings.effective_embedding_dim()
        self.request_model = self._request_model()

    async def embed(self, texts: List[str]) -> List[List[float]]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self.embedding_url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=self._request_payload(texts),
                timeout=30.0
            )
            resp.raise_for_status()
            data = resp.json()
            return self._vectors_from_response(data)

    def _request_payload(self, texts: List[str]) -> dict:
        if settings.use_doubao_embedding() and settings.use_doubao_multimodal_embedding():
            return {
                "input": [{"type": "text", "text": text} for text in texts],
                "model": self.request_model,
            }
        return {"input": texts, "model": self.request_model}

    def _vectors_from_response(self, data: dict) -> List[List[float]]:
        response_data = data["data"]
        if isinstance(response_data, dict):
            return [response_data["embedding"]]
        return [item["embedding"] for item in response_data]

    def _request_model(self) -> str:
        if settings.use_doubao_embedding():
            return DOUBAO_EMBEDDING_MODEL_ALIASES.get(self.model, self.model)
        return self.model

    async def embed_single(self, text: str) -> List[float]:
        results = await self.embed([text])
        return results[0]

    def health(self) -> dict:
        return {
            "configured": bool(self.api_key),
            "endpoint": self.embedding_url,
            "model": self.model,
            "dim": self.dim,
            "provider": self._provider_name(),
        }

    def _provider_name(self) -> str:
        if settings.use_doubao_embedding():
            return "doubao"
        if settings.EMBEDDING_API_KEY or settings.EMBEDDING_BASE_URL:
            return "embedding"
        if settings.AI_MATCH_TEXT_EMBEDDING_API_KEY or settings.AI_MATCH_TEXT_EMBEDDING_ENDPOINT:
            return "ai_match_text"
        return "openai"

    async def probe(self) -> dict:
        health = self.health()
        if not self.api_key:
            return {**health, "ok": False, "error": "EMBEDDING_API_KEY or OPENAI_API_KEY not configured"}
        try:
            vector = await self.embed_single("health check")
            return {**health, "ok": True, "vector_dim": len(vector)}
        except httpx.HTTPStatusError as exc:
            response_text = exc.response.text[:1000] if exc.response is not None else str(exc)
            return {
                **health,
                "ok": False,
                "status_code": exc.response.status_code if exc.response is not None else None,
                "error": response_text,
            }
        except Exception as exc:
            return {**health, "ok": False, "error": str(exc)}

embedder = Embedder()
