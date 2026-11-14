from __future__ import annotations

import os

from anthropic import Anthropic

from app.llm.client import LlmClient


class ClaudeLlmClient(LlmClient):

    def __init__(
        self,
        model: str | None = None,
        temperature: float | None = None,
    ):
        self.client = Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            timeout=30.0,
            max_retries=0,
        )

        self.model = (
            model
            or os.getenv(
                "ANTHROPIC_MODEL",
                "claude-sonnet-4-6",
            )
        )
        self.generation_settings = {"max_tokens": 4096}
        if temperature is not None:
            self.generation_settings["temperature"] = temperature

    def generate(
        self,
        prompt: str,
    ) -> str:

        response = self.client.messages.create(
            model=self.model,
            **self.generation_settings,
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
