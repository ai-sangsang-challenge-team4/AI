"""Gemini client with bounded HTTP calls and no implicit SDK retries."""
import os

from google import genai
from google.genai import types

from app.llm.client import LlmClient


# Google Gen AI HttpOptions.timeout uses milliseconds.
GEMINI_REQUEST_TIMEOUT_MS = 30_000


class GeminiLlmClient(LlmClient):

    def __init__(self, model: str | None = None):
        self.client = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"],
            http_options=types.HttpOptions(
                timeout=GEMINI_REQUEST_TIMEOUT_MS,
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )
        self.model = model or "gemini-3.8-flash"

    def generate(self, prompt: str) -> str:
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
        )
        return response.text
