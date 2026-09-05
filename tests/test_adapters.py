import json

import httpx

from extraction_service.adapters.openai_compat import OpenAICompatAdapter

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

    x = OpenAICompatAdapter("m", transport=httpx.MockTransport(handler)).extract("p", {"type": "object"})
    assert x.entities[0].mention == "91001"
    assert seen["path"] == "/v1/chat/completions" and seen["auth"] == "Bearer k" and seen["stream"] is True
    assert seen["response_format"]["json_schema"]["schema"] == {"type": "object"}
