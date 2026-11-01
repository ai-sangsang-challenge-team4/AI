import os

from dotenv import load_dotenv
from anthropic import Anthropic

from app.llm.client import LlmClient


load_dotenv()


class ClaudeLlmClient(LlmClient):

    def __init__(self, model: str | None = None):
        self.client = Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"]
        )

        self.model = model or os.environ.get(
            "ANTHROPIC_MODEL",
            "claude-sonnet-5-5",
        )

    def generate(self, prompt: str) -> str:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=2000,
            temperature=0.0,
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        )

        text = ""

        for block in response.content:
            if hasattr(block, "text"):
                text += block.text

        return text.strip()