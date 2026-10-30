import os

from anthropic import Anthropic

from app.llm.client import LlmClient


class AnthropicLlmClient(LlmClient):

    def __init__(self, model: str | None = None):
        self.client = Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"]
        )
        self.model = model or "claude-sonnet-4-6"

    def generate(self, prompt: str) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        )

        return "".join(
            block.text
            for block in response.content
            if block.type == "text"
        )
