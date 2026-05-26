import httpx
from typing import List
from app.config import settings

class Embedder:
    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY
        self.base_url = settings.OPENAI_BASE_URL
        self.model = settings.EMBEDDING_MODEL
        self.dim = settings.EMBEDDING_DIM

    async def embed(self, texts: List[str]) -> List[List[float]]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"input": texts, "model": self.model},
                timeout=30.0
            )
            resp.raise_for_status()
            data = resp.json()
            return [item["embedding"] for item in data["data"]]

    async def embed_single(self, text: str) -> List[float]:
        results = await self.embed([text])
        return results[0]

embedder = Embedder()
