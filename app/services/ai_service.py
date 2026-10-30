import json

from app.llm.gemini_client import GeminiLlmClient
from app.llm.mock_client import MockLlmClient
from app.rag.mock_retriever import MockRagRetriever
from app.rag.prompt import (
    build_prompt,
    build_softened_summary_prompt,
)
from app.schemas.ai import AiAnalysisResult


class AiService:

    def __init__(self):
        # 기존 위험 분석 구조는 유지
        self.retriever = MockRagRetriever()
        self.llm_client = MockLlmClient()

        # 완충 요약은 실제 Gemini LLM 사용
        self.summary_llm_client = GeminiLlmClient()

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

    def soften_summary(self, complaint: str) -> str:
        prompt = build_softened_summary_prompt(
            complaint
        )

        response = self.summary_llm_client.generate(
            prompt
        )

        return response.strip()