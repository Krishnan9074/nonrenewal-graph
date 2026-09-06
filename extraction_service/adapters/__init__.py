import os
from typing import Protocol

PROVIDER = os.environ.get("EXTRACTION_PROVIDER", "openai_compat")


class Adapter(Protocol):
    model_id: str

    def structured(self, prompt: str, schema: dict) -> dict:
        """One model call constrained to a JSON schema; the caller validates the result."""
        ...


def build(model_id: str) -> Adapter:
    if PROVIDER == "anthropic":
        from extraction_service.adapters.anthropic import AnthropicAdapter

        return AnthropicAdapter(model_id)
    if PROVIDER == "openai_compat":
        from extraction_service.adapters.openai_compat import OpenAICompatAdapter

        return OpenAICompatAdapter(model_id)
    raise ValueError(f"unknown EXTRACTION_PROVIDER {PROVIDER!r}")
