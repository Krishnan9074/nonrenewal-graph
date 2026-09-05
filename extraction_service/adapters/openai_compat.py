import json
import os

import httpx

from extraction_service.models import Extraction


class OpenAICompatAdapter:
    def __init__(self, model_id: str, max_tokens: int = 32000, transport: httpx.BaseTransport | None = None):
        self.model_id, self.max_tokens = model_id, max_tokens
        self.client = httpx.Client(
            base_url=os.environ["OPENAI_COMPAT_BASE_URL"],
            headers={"Authorization": f"Bearer {os.environ['OPENAI_COMPAT_API_KEY']}"},
            timeout=httpx.Timeout(600, read=120),  # streaming: the read timeout is between tokens, not per response
            transport=transport,
        )

    def extract(self, prompt: str, schema: dict) -> Extraction:
        body = {
            "model": self.model_id,
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "stream": True,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "extraction", "schema": schema}},
        }
        parts: list[str] = []
        with self.client.stream("POST", "/chat/completions", json=body) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    choices = json.loads(line[6:])["choices"]  # the final usage event carries no choices
                    parts += [c["delta"].get("content") or "" for c in choices]
        return Extraction.model_validate_json("".join(parts))
