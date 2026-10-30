import json

from app.llm.mock_client import MockLlmClient
from app.rag.retriever import RagRetriever
from app.rag.prompt import build_prompt
from app.schemas.ai import AiAnalysisResult


class AiService:

    def __init__(self):
        self.retriever = RagRetriever()
        self.llm_client = MockLlmClient()

    def analyze(self, complaint: str) -> AiAnalysisResult:
        documents = self.retriever.search(
            complaint,
            k=3,
        )

        prompt = build_prompt(
            complaint=complaint,
            documents=documents,
        )

        response = self.llm_client.generate(prompt)

        data = json.loads(response)

        return AiAnalysisResult.model_validate(data)