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
        # 위험 분석
        self.retriever = MockRagRetriever()
        self.llm_client = MockLlmClient()

        # 완충 요약
        self.summary_llm_client = GeminiLlmClient(
    model="gemini-3.5-flash-lite"
)

    def analyze(self, complaint: str) -> AiAnalysisResult:
        # 1. 기존 위험 분석
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

        # 2. Gemini 완충 요약
        softened_summary = self.soften_summary(
            complaint
        )

        # 3. 기존 분석 결과에 완충 요약 추가
        data["softenedSummary"] = softened_summary

        return AiAnalysisResult.model_validate(data)

    def soften_summary(self, complaint: str) -> str:
        prompt = build_softened_summary_prompt(
            complaint
        )

        response = self.summary_llm_client.generate(
            prompt
        )

        return response.strip()