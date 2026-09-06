import os

import httpx

from extraction_service.adapters.openai_compat import client

EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-ai/nomic-embed-text-v1.5")  # served by Fireworks' OpenAI-compatible API


class Embedder:
    def __init__(self, model_id: str = EMBED_MODEL, transport: httpx.BaseTransport | None = None):
        self.model_id = model_id
        self.client = client(transport)

    def embed(self, texts: list[str]) -> list[list[float]]:
        r = self.client.post("/embeddings", json={"model": self.model_id, "input": texts})
        r.raise_for_status()
        return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
