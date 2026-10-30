import os

from openai import OpenAI

from app.llm.client import LlmClient


class OpenAILlmClient(LlmClient):

    def __init__(self, model: str | None = None):
        self.client = OpenAI(
            api_key=os.environ["OPENAI_API_KEY"]
        )
        self.model = model or "gpt-5.4-mini"

    def generate(self, prompt: str) -> str:
        response = self.client.responses.create(
            model=self.model,
            input=prompt,
        )

        return response.output_text
