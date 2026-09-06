import json
import os
import time

import httpx

RETRIES, BACKOFF_S = 3, 15  # provider stalls mid-stream now and then; a retry is cheaper than a dead job


def client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        base_url=os.environ["OPENAI_COMPAT_BASE_URL"],
        headers={"Authorization": f"Bearer {os.environ['OPENAI_COMPAT_API_KEY']}"},
        timeout=httpx.Timeout(600, read=120),  # streaming: the read timeout is between tokens, not per response
        transport=transport,
    )


MAX_TOKENS = int(os.environ.get("EXTRACTION_MAX_TOKENS", "100000"))  # a 700-ZIP bulletin with spans is ~80k tokens


class OpenAICompatAdapter:
    def __init__(self, model_id: str, max_tokens: int = MAX_TOKENS, transport: httpx.BaseTransport | None = None):
        self.model_id, self.max_tokens = model_id, max_tokens
        self.client = client(transport)

    def structured(self, prompt: str, schema: dict) -> dict:
        for attempt in range(RETRIES):
            try:
                return self._once(prompt, schema)
            except httpx.TransportError as e:
                if attempt == RETRIES - 1:
                    raise
                print(f"retry {attempt + 1}/{RETRIES} after {type(e).__name__}", flush=True)
                time.sleep(BACKOFF_S * (attempt + 1))
        raise AssertionError("unreachable")

    def _once(self, prompt: str, schema: dict) -> dict:
        body = {
            "model": self.model_id,
            "max_tokens": self.max_tokens,
            "temperature": 0,
            "stream": True,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_schema", "json_schema": {"name": "result", "schema": schema}},
        }
        parts: list[str] = []
        with self.client.stream("POST", "/chat/completions", json=body) as r:
            r.raise_for_status()
            for line in r.iter_lines():
                if line.startswith("data: ") and line != "data: [DONE]":
                    choices = json.loads(line[6:])["choices"]  # the final usage event carries no choices
                    parts += [c["delta"].get("content") or "" for c in choices]
        return json.loads("".join(parts))
