import json

from app.llm.gemini_client import GeminiLlmClient
from app.rag.retriever import RagRetriever
from app.rag.context_example_retriever import ContextExampleRetriever
from app.rag.prompt import (
    RISK_TAG_CODES,
    build_context_analysis_prompt,
    build_prompt,
    build_softened_summary_prompt,
)
from app.schemas.ai import (
    ContextAnalysisResult,
    LlmAnalysisMetadata,
    LlmRiskAnalysisResult,
)


class AiService:

    def __init__(self):
        # ====================================================
        # RAG
        # ====================================================

        # 실제 Chroma + BGE-M3 Retriever
        self.retriever = RagRetriever()

        # 교사 검토 완료 사례 Retriever
        self.example_retriever = ContextExampleRetriever()

        # ====================================================
        # LLM
        # ====================================================

        # 현재 백엔드의 LlmRiskAnalysisResult 계약에 맞는
        # 위험 요소 분석용 LLM
        self.risk_llm_client = GeminiLlmClient(
            model="gemini-3.5-flash-lite"
        )

        # 문맥 분석용 LLM
        self.context_llm_client = GeminiLlmClient(
            model="gemini-3.5-flash-lite"
        )

        # 완충 요약용 LLM
        self.summary_llm_client = GeminiLlmClient(
            model="gemini-3.5-flash-lite"
        )

    # ========================================================
    # Backend /api/v1/ai/analyze
    # ========================================================

    def analyze(
        self,
        complaint: str,
    ) -> LlmRiskAnalysisResult:

        # ----------------------------------------------------
        # 1. 관련 자료 검색
        # ----------------------------------------------------

        documents = self.retriever.search(
            complaint,
            k=3,
        )

        # ----------------------------------------------------
        # 2. 위험 요소 분석 프롬프트
        # ----------------------------------------------------

        prompt = build_prompt(
            complaint=complaint,
            documents=documents,
        )

        # ----------------------------------------------------
        # 3. LLM 호출
        # ----------------------------------------------------

        response = self.risk_llm_client.generate(
            prompt
        )

        # ----------------------------------------------------
        # 4. JSON 파싱
        # ----------------------------------------------------

        risk_data = self._parse_json_response(
            response,
            error_message=(
                "위험 요소 분석 LLM이 "
                "유효한 JSON을 반환하지 않았습니다."
            ),
        )

        # ----------------------------------------------------
        # 5. RiskTagCode 검증
        # ----------------------------------------------------

        self._validate_risk_tags(
            risk_data
        )

        # ----------------------------------------------------
        # 6. Backend 계약에 맞는 결과 생성
        # ----------------------------------------------------

        return LlmRiskAnalysisResult.model_validate(
            {
                "tags": risk_data.get(
                    "tags",
                    [],
                ),
                "metadata": risk_data.get(
                    "metadata",
                    {
                        "modelName": "gemini-3.5-flash-lite",
                        "temperature": 0.0,
                    },
                ),
            }
        )

    # ========================================================
    # 내부 기능: 문맥 분석
    #
    # 현재 /analyze 응답에는 포함하지 않는다.
    # 이후 별도 Backend API가 필요할 때 사용한다.
    # ========================================================

    def analyze_context(
        self,
        complaint: str,
    ) -> ContextAnalysisResult:

        # ----------------------------------------------------
        # 1. 과거 교사 검토 사례 검색
        # ----------------------------------------------------

        examples = self.example_retriever.search(
            complaint
        )

        # ----------------------------------------------------
        # 2. 기본 프롬프트
        # ----------------------------------------------------

        prompt = build_context_analysis_prompt(
            complaint=complaint,
        )

        # ----------------------------------------------------
        # 3. 과거 검토 사례 추가
        # ----------------------------------------------------

        prompt = self._append_context_examples(
            prompt=prompt,
            examples=examples,
        )

        # ----------------------------------------------------
        # 4. LLM 호출
        # ----------------------------------------------------

        response = self.context_llm_client.generate(
            prompt
        )

        # ----------------------------------------------------
        # 5. JSON 파싱
        # ----------------------------------------------------

        data = self._parse_json_response(
            response,
            error_message=(
                "문맥 분석 LLM이 "
                "유효한 JSON을 반환하지 않았습니다."
            ),
        )

        return ContextAnalysisResult.model_validate(
            data
        )

    # ========================================================
    # 내부 기능: 완충 요약
    #
    # 현재 /analyze 응답에는 포함하지 않는다.
    # ========================================================

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

    # ========================================================
    # RiskTagCode 검증
    # ========================================================

    def _validate_risk_tags(
        self,
        data: dict,
    ) -> None:

        tags = data.get(
            "tags",
            [],
        )

        if not isinstance(tags, list):
            raise ValueError(
                "위험 요소 분석 결과의 tags는 리스트여야 합니다."
            )

        for tag in tags:

            if not isinstance(tag, dict):
                raise ValueError(
                    "위험 요소 분석 결과의 각 tag는 객체여야 합니다."
                )

            code = tag.get("code")

            if code not in RISK_TAG_CODES:
                raise ValueError(
                    f"허용되지 않은 RiskTagCode입니다: {code}"
                )

    # ========================================================
    # JSON 파싱
    # ========================================================

    def _parse_json_response(
        self,
        response: str,
        error_message: str,
    ) -> dict:

        response = response.strip()

        # ----------------------------------------------------
        # Markdown 코드블록 제거
        # ----------------------------------------------------

        if response.startswith("```"):

            if response.startswith("```json"):
                response = response[
                    len("```json"):
                ]

            else:
                response = response[
                    len("```"):
                ]

            if response.endswith("```"):
                response = response[
                    :-len("```")
                ]

            response = response.strip()

        # ----------------------------------------------------
        # JSON 파싱
        # ----------------------------------------------------

        try:
            data = json.loads(
                response
            )

        except json.JSONDecodeError as exc:

            print(
                "===== LLM INVALID JSON ====="
            )
            print(response)
            print(
                "============================"
            )

            raise ValueError(
                error_message
            ) from exc

        if not isinstance(data, dict):
            raise ValueError(
                error_message
            )

        return data

    # ========================================================
    # 문맥 분석용 과거 사례 추가
    # ========================================================

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
""".strip()
