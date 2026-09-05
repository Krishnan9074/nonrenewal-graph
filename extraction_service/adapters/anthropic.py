import anthropic

from extraction_service.models import Extraction


class AnthropicAdapter:
    def __init__(self, model_id: str, max_tokens: int = 32000):  # a bulletin yields ~120 edges with spans
        self.model_id, self.max_tokens = model_id, max_tokens
        self.client = anthropic.Anthropic()

    def extract(self, prompt: str, schema: dict) -> Extraction:
        with self.client.messages.stream(
            model=self.model_id,
            max_tokens=self.max_tokens,
            tools=[{"name": "emit", "description": "Emit the extraction.", "input_schema": schema}],
            tool_choice={"type": "tool", "name": "emit"},
            messages=[{"role": "user", "content": prompt}],
        ) as s:
            r = s.get_final_message()
        return Extraction.model_validate(next(b for b in r.content if b.type == "tool_use").input)
