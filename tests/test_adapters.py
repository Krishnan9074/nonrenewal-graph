import json

import httpx

from extraction_service.adapters.openai_compat import OpenAICompatAdapter
from extraction_service.embed import Embedder

OUT = json.dumps({"entities": [{"mention": "91001", "type": "ZIP"}], "edges": []})


def sse(*chunks: str) -> str:
    events = [json.dumps({"choices": [{"delta": {"content": c}}]}) for c in chunks]
    usage = json.dumps({"choices": [], "usage": {"total_tokens": 1}})
    return "".join(f"data: {e}\n\n" for e in events) + f"data: {usage}\n\ndata: [DONE]\n\n"


def test_openai_compat_streams_and_parses(monkeypatch):
    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "https://x/v1")
    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", "k")
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen.update(json.loads(req.content), auth=req.headers["authorization"], path=req.url.path)
        return httpx.Response(200, text=sse(OUT[:10], OUT[10:]), headers={"content-type": "text/event-stream"})

    x = OpenAICompatAdapter("m", transport=httpx.MockTransport(handler)).structured("p", {"type": "object"})
    assert x["entities"][0]["mention"] == "91001"
    assert seen["path"] == "/v1/chat/completions" and seen["auth"] == "Bearer k" and seen["stream"] is True
    assert seen["response_format"]["json_schema"]["schema"] == {"type": "object"}


def test_embedder_orders_by_index(monkeypatch):
    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "https://x/v1")
    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", "k")

    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/v1/embeddings" and json.loads(req.content)["input"] == ["a", "b"]
        return httpx.Response(200, json={"data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]})

    assert Embedder("e", transport=httpx.MockTransport(handler)).embed(["a", "b"]) == [[1, 0], [0, 1]]


def test_openai_compat_retries_transport_errors(monkeypatch):
    monkeypatch.setenv("OPENAI_COMPAT_BASE_URL", "https://x/v1")
    monkeypatch.setenv("OPENAI_COMPAT_API_KEY", "k")
    monkeypatch.setattr("extraction_service.adapters.openai_compat.BACKOFF_S", 0)
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) < 3:
            raise httpx.ReadTimeout("stalled")
        return httpx.Response(200, text=sse(OUT), headers={"content-type": "text/event-stream"})

    x = OpenAICompatAdapter("m", transport=httpx.MockTransport(handler)).structured("p", {})
    assert x["entities"][0]["mention"] == "91001" and len(calls) == 3
