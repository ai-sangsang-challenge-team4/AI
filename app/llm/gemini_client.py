import os

from dotenv import load_dotenv
from google import genai

from app.llm.client import LlmClient


load_dotenv()


class GeminiLlmClient(LlmClient):

    def __init__(self, model: str | None = None):
        self.client = genai.Client(
            api_key=os.environ["GEMINI_API_KEY"]
        )
        self.model = model or "gemini-3.8-flash"

    def generate(self, prompt: str) -> str:
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
        )

        return response.text