import os

import anthropic

MAX_TOKENS = int(os.environ.get("EXTRACTION_MAX_TOKENS", "64000"))  # a 700-ZIP bulletin with spans is ~80k tokens


class AnthropicAdapter:
    def __init__(self, model_id: str, max_tokens: int = MAX_TOKENS):
        self.model_id, self.max_tokens = model_id, max_tokens
        self.client = anthropic.Anthropic()

    def structured(self, prompt: str, schema: dict) -> dict:
        with self.client.messages.stream(
            model=self.model_id,
            max_tokens=self.max_tokens,
            tools=[{"name": "emit", "description": "Emit the structured result.", "input_schema": schema}],
            tool_choice={"type": "tool", "name": "emit"},
            messages=[{"role": "user", "content": prompt}],
        ) as s:
            r = s.get_final_message()
        return next(b for b in r.content if b.type == "tool_use").input
