import os
from typing import Protocol

from extraction_service.models import Extraction

PROVIDER = os.environ.get("EXTRACTION_PROVIDER", "openai_compat")


class Adapter(Protocol):
    model_id: str

    def extract(self, prompt: str, schema: dict) -> Extraction: ...


def build(model_id: str) -> Adapter:
    if PROVIDER == "anthropic":
        from extraction_service.adapters.anthropic import AnthropicAdapter

        return AnthropicAdapter(model_id)
    if PROVIDER == "openai_compat":
        from extraction_service.adapters.openai_compat import OpenAICompatAdapter

        return OpenAICompatAdapter(model_id)
    raise ValueError(f"unknown EXTRACTION_PROVIDER {PROVIDER!r}")
