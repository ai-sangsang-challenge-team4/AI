import json

from app.llm.gemini_client import GeminiLlmClient
from app.llm.mock_client import MockLlmClient
from app.rag.mock_retriever import MockRagRetriever
from app.rag.context_example_retriever import ContextExampleRetriever
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

        # 교사 검토 사례 검색
        self.example_retriever = ContextExampleRetriever()

        # 완충 요약
        self.summary_llm_client = GeminiLlmClient(
            model="gemini-3.5-flash-lite"
        )

        # 문맥 분석
        self.context_llm_client = GeminiLlmClient(
            model="gemini-3.5-flash-lite"
        )

    def analyze(
        self,
        complaint: str,
    ) -> AiAnalysisResult:

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
        return AiAnalysisResult.model_validate(
            data
        )

    def analyze_context(
        self,
        complaint: str,
    ) -> dict:

        # 1. 과거 교사 검토 사례 검색
        examples = self.example_retriever.search(
            complaint
        )

        # 2. 기본 문맥 분석 프롬프트 생성
        prompt = build_context_analysis_prompt(
            complaint=complaint,
        )

        # 3. 과거 검토 사례를 참고자료로 추가
        prompt = self._append_context_examples(
            prompt=prompt,
            examples=examples,
        )

        # 4. Gemini 문맥 분석
        response = self.context_llm_client.generate(
            prompt
        )

        response = (response or "").strip()

        # Gemini가 Markdown 코드블록으로
        # JSON을 반환하는 경우 처리
        if response.startswith("```"):
            response = response.replace(
                "```json",
                "",
                1,
            )

            response = response.replace(
                "```",
                "",
            )

            response = response.strip()

        # 5. JSON 응답 검증
        try:
            return json.loads(response)

        except json.JSONDecodeError as exc:
            print(
                "===== CONTEXT ANALYSIS INVALID JSON ====="
            )
            print(
                f"RAW RESPONSE: {response!r}"
            )
            print(
                "=========================================="
            )

            raise ValueError(
                "문맥 분석 LLM이 유효한 JSON을 반환하지 않았습니다."
            ) from exc

    def _append_context_examples(
        self,
        prompt: str,
        examples: list[dict],
    ) -> str:

        example_blocks = []

        for example in examples:
            context = example.get(
                "context",
                {},
            )

            tags = example.get(
                "tags",
                [],
            )

            example_blocks.append(
                f"""
[교사 검토 사례 {example.get("caseId")}]

민원:
{example.get("message", "")}

교사 검토 결과:
- communicationIntent:
{context.get("communicationIntent")}

- primaryTopic:
{context.get("primaryTopic")}

- secondaryTopics:
{json.dumps(
    context.get(
        "secondaryTopics",
        [],
    ),
    ensure_ascii=False,
)}

- 위험 태그:
{json.dumps(
    tags,
    ensure_ascii=False,
)}

이 사례는 교사 검토를 통해 확인된 사례이다.
현재 민원과 의미가 유사한 경우 판단 기준을 참고하되,
현재 민원에 존재하지 않는 내용을 임의로 추가하지 않는다.
"""
            )

        examples_text = "\n".join(
            example_blocks
        )

        return f"""
{prompt}

========================================
교사 검토 완료 사례 참고자료
========================================

아래 사례들은 과거에 교사가 검토하여 확정한 사례이다.

{examples_text}

========================================
사례 활용 원칙
========================================

1. 현재 입력된 민원을 가장 우선하여 판단한다.

2. 과거 사례는 판단 기준을 참고하기 위한
   few-shot 예시로만 사용한다.

3. 과거 사례의 라벨을 그대로 복사하지 않는다.

4. 현재 민원에 명확한 근거가 없는
   communicationIntent를 추가하지 않는다.

5. 현재 민원에 명확한 근거가 없는
   primaryTopic을 추가하지 않는다.

6. 현재 민원에서 확인되지 않는 내용을
   과거 사례를 근거로 추론하지 않는다.

7. evidenceSpans가 필요한 경우
   반드시 현재 민원에 실제로 존재하는
   정확한 표현을 사용한다.

8. 현재 민원의 의미가 과거 사례와 다르면
   과거 사례와 다른 결과를 선택할 수 있다.

9. 확신하기 어려운 경우에는 억지로 과거 사례와
   동일하게 판단하지 않는다.

10. 반드시 기존 JSON 출력 형식을 유지한다.

========================================
최종 작업
========================================

위의 교사 검토 사례를 참고하여
현재 민원의 문맥을 분석하라.

반드시 위에서 제공된 현재 민원을 기준으로 판단하라.
"""

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