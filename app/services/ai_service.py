import json

from app.llm.gemini_client import GeminiLlmClient
from app.llm.mock_client import MockLlmClient
from app.rag.mock_retriever import MockRagRetriever
from app.rag.prompt import (
    build_context_analysis_prompt,
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

        # 문맥 분석
        self.context_llm_client = GeminiLlmClient(
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

        # 2. LLM 문맥 분석
        context = self.analyze_context(
            complaint
        )

        data["context"] = context

        # 3. Gemini 완충 요약
        softened_summary = self.soften_summary(
            complaint
        )

        data["softenedSummary"] = softened_summary

        # 4. 최종 결과 검증
        return AiAnalysisResult.model_validate(data)

    def analyze_context(
        self,
        complaint: str,
    ) -> dict:
        prompt = build_context_analysis_prompt(
            complaint=complaint,
        )

        response = self.context_llm_client.generate(
            prompt
        )

        return json.loads(response)

    def soften_summary(
        self,
        complaint: str,
    ) -> str:
        prompt = build_softened_summary_prompt(
            complaint
        )

        response = self.summary_llm_client.generate(
            prompt
        )

        return response.strip()