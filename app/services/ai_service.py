import json

from app.llm.claude_client import ClaudeLlmClient
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
    RiskTagResult,
)

from app.schemas.revision import (
    RevisionRequest,
    RevisionResult,
)

from app.schemas.support import (
    SummaryResult,
    ResponseDraftResult,
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

        # ----------------------------------------------------
        # Claude
        # ----------------------------------------------------

        # 위험 요소 분석
        self.risk_llm_client = ClaudeLlmClient()

        # 문맥 분석
        self.context_llm_client = ClaudeLlmClient()

        # 학부모용 민원 표현 수정안
        self.revision_llm_client = ClaudeLlmClient()

        # ----------------------------------------------------
        # Gemini
        # ----------------------------------------------------

        # 완충 요약
        self.summary_llm_client = GeminiLlmClient(
            model="gemini-3.5-flash-lite"
        )

        # 교사용 답변 초안
        self.response_draft_llm_client = GeminiLlmClient(
            model="gemini-3.5-flash-lite"
        )

        # ========================================================
    # Backend /api/v1/ai/analyze
    #
    # Backend Rule 기반 1차 탐지 결과를 참고하여
    # Claude가 민원 문맥 기반 2차 위험 분석을 수행한다.
    # ========================================================

    def analyze(
        self,
        complaint: str,
        rule_results: list[RiskTagResult],
    ) -> LlmRiskAnalysisResult:

        # ----------------------------------------------------
        # 1. 관련 자료 검색
        # ----------------------------------------------------

        documents = self.retriever.search(
            complaint,
            k=3,
        )

        # ----------------------------------------------------
        # 2. Rule 탐지 결과 직렬화
        # ----------------------------------------------------

        rule_results_data = [
            result.model_dump(
                exclude_none=True
            )
            for result in rule_results
        ]

        # ----------------------------------------------------
        # 3. 위험 요소 2차 분석 프롬프트
        # ----------------------------------------------------

        prompt = build_prompt(
            complaint=complaint,
            documents=documents,
            rule_results=rule_results_data,
        )

        # ----------------------------------------------------
        # 4. Claude 호출
        # ----------------------------------------------------

        response = self.risk_llm_client.generate(
            prompt
        )

        # ----------------------------------------------------
        # 5. JSON 파싱
        # ----------------------------------------------------

        risk_data = self._parse_json_response(
            response,
            error_message=(
                "위험 요소 분석 LLM이 "
                "유효한 JSON을 반환하지 않았습니다."
            ),
        )

        # ----------------------------------------------------
        # 6. RiskTagCode 검증
        # ----------------------------------------------------

        self._validate_risk_tags(
            risk_data
        )

        # ----------------------------------------------------
        # 7. Backend 계약에 맞는 결과 생성
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
                        "modelName": self.risk_llm_client.model,
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
        # 4. Claude 호출
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
    # Backend 연동용: 완충 요약 생성
    # ========================================================

    def generate_summary(
        self,
        content: str,
    ) -> SummaryResult:

        summary = self.soften_summary(
            content
        )

        return SummaryResult(
            summary=summary,
            modelName=self.summary_llm_client.model,
        )


    # ========================================================
    # Backend 연동용: 교사용 AI 답변 초안
    #
    # 내부 처리:
    # 1. Claude 문맥 분석
    # 2. BGE-M3 RAG 검색
    # 3. Gemini 답변 초안 생성
    # ========================================================

    def generate_response_draft(
        self,
        content: str,
    ) -> ResponseDraftResult:

        # ----------------------------------------------------
        # 1. 민원 문맥 분석
        # ----------------------------------------------------

        context = self.analyze_context(
            content
        )

        # ----------------------------------------------------
        # 2. 관련 근거 자료 검색
        # ----------------------------------------------------

        documents = self.retriever.search(
            content,
            k=3,
        )

        # ----------------------------------------------------
        # 3. 답변 초안 프롬프트 생성
        # ----------------------------------------------------

        prompt = self._build_response_draft_prompt(
            content=content,
            context=context,
            documents=documents,
        )

        # ----------------------------------------------------
        # 4. Gemini 호출
        # ----------------------------------------------------

        response = (
            self.response_draft_llm_client
            .generate(prompt)
            .strip()
        )

        return ResponseDraftResult(
            content=response,
            modelName=self.response_draft_llm_client.model,
        )

    # ========================================================
    # 내부 기능: 학부모용 민원 표현 수정안
    #
    # 선정 모델: Claude
    #
    # 평가 기준:
    # 1. 의도 보존
    # 2. 정보 보존
    # 3. 감정 완화
    # 4. 표현 적절성
    # 5. 과도한 순화 방지
    # ========================================================

    def revise_complaint(
        self,
        request: RevisionRequest,
    ) -> RevisionResult:

        prompt = self._build_revision_prompt(
            request
        )

        response = self.revision_llm_client.generate(
            prompt
        )

        data = self._parse_json_response(
            response,
            error_message=(
                "민원 표현 수정안 LLM이 "
                "유효한 JSON을 반환하지 않았습니다."
            ),
        )

        return RevisionResult.model_validate(
            data
        )

    # ========================================================
    # 수정안 Prompt
    # ========================================================

    def _build_revision_prompt(
        self,
        request: RevisionRequest,
    ) -> str:

        detected_tags = [
            tag
            for tag in request.tags
            if tag.state == "PRESENT"
        ]

        tag_context = []

        for tag in detected_tags:
            tag_context.append(
                {
                    "code": tag.code,
                    "state": tag.state,
                    "confidence": tag.confidence,
                    "evidence": tag.evidence,
                    "reason": tag.reason,
                }
            )

        tag_context_json = json.dumps(
            tag_context,
            ensure_ascii=False,
            indent=2,
        )

        return f"""
당신은 학교 학부모 민원의 표현을 전문적이고 건설적인 방식으로 수정하는 AI입니다.

입력된 민원의 핵심적인 의도와 사실관계를 유지하면서,
학교와 교사가 내용을 정확하게 이해하고 대응할 수 있는 표현으로 수정하십시오.

==================================================
[민원 원문]
==================================================

{request.complaint}

==================================================
[위험 분석 결과]
==================================================

위험 점수: {request.riskScore}
위험 수준: {request.riskLevel}

탐지된 위험 태그:

{tag_context_json}

==================================================
[수정 원칙]
==================================================

1. 의도 보존

- 학부모가 실제로 요청하거나 문제를 제기하려는 핵심 의도를 유지하십시오.
- 원문에 없는 새로운 요구사항을 추가하지 마십시오.
- 단순한 문의를 다른 유형의 요구로 바꾸지 마십시오.

2. 정보 보존

- 원문에 포함된 사실, 상황, 요청사항을 가능한 한 유지하십시오.
- 사실관계를 임의로 삭제하거나 변경하지 마십시오.
- 원문에 없는 구체적인 사실을 만들어내지 마십시오.

3. 감정 완화

- 공격적이거나 감정적인 표현은 정중하고 객관적인 표현으로 바꾸십시오.
- 비난, 모욕, 협박으로 읽힐 수 있는 표현은 완화하십시오.
- 단, 민원의 정당한 문제 제기 자체를 삭제하지 마십시오.

4. 표현 적절성

- 학부모가 실제 학교 민원에 사용할 수 있는 자연스러운 문장으로 작성하십시오.
- 지나치게 딱딱하거나 법률문서와 같은 표현은 피하십시오.
- 구체적인 요청사항은 명확하게 남겨두십시오.

5. 과도한 순화 방지

- 학부모의 문제 제기를 단순한 문의나 감사 표현으로 바꾸지 마십시오.
- 부당한 상황에 대한 문제 제기나 개선 요구가 있었다면 그 의미를 유지하십시오.
- 원문의 핵심적인 불만이나 요청을 삭제해서는 안 됩니다.

6. 위험 태그별 수정 제안

- 실제로 PRESENT 상태인 위험 태그에 대해서만 tagSuggestions를 생성하십시오.
- 각 originalExpression은 반드시 원문에 실제로 존재하는 표현을 사용하십시오.
- suggestedExpression은 해당 표현을 정중하고 객관적으로 바꾼 표현이어야 합니다.
- reason에는 왜 해당 표현을 수정하는지 구체적으로 설명하십시오.
- 원문에서 확인되지 않는 위험요소에 대한 제안은 생성하지 마십시오.

7. 근거 없는 수정 금지

- 위험 점수나 위험 수준만 보고 원문에 없는 위험요소를 만들어내지 마십시오.
- 제공된 evidence와 원문을 우선하여 판단하십시오.
- 원문의 사실관계, 인물, 사건, 날짜, 요구사항을 임의로 추가하거나 변경하지 마십시오.

==================================================
[출력 형식]
==================================================

반드시 JSON 객체 하나만 반환하십시오.

마크다운 코드블록을 사용하지 마십시오.
JSON 앞뒤에 설명을 붙이지 마십시오.

다음 구조를 정확히 지키십시오:

{{
  "finalRevision": {{
    "reason": "전체 수정안을 제안한 이유",
    "content": "수정된 전체 민원 내용"
  }},
  "tagSuggestions": [
    {{
      "code": "위험 태그 코드",
      "originalExpression": "원문에 실제 존재하는 표현",
      "suggestedExpression": "수정된 표현",
      "reason": "해당 표현을 수정한 이유"
    }}
  ]
}}

중요:

- finalRevision은 반드시 생성하십시오.
- tagSuggestions는 PRESENT 상태의 위험 태그에 대해서만 생성하십시오.
- 위험 태그가 하나도 PRESENT가 아니라면 tagSuggestions는 빈 배열이어야 합니다.
- originalExpression은 반드시 원문의 표현이어야 합니다.
- suggestedExpression은 실제 학교 민원에서 사용할 수 있는 자연스러운 표현이어야 합니다.
- 원문의 핵심적인 주장이나 요구를 약화시키거나 삭제하지 마십시오.
- JSON 이외의 내용을 출력하지 마십시오.

==================================================
[최종 작업]
==================================================

위의 위험 분석 결과를 참고하여 현재 민원의 표현을 수정하십시오.
단, 위험 분석 결과보다 현재 민원 원문을 우선하여 판단하십시오.
"""

        # ========================================================
    # 교사용 답변 초안 Prompt
    # ========================================================

    def _build_response_draft_prompt(
        self,
        content: str,
        context: ContextAnalysisResult,
        documents: list[dict],
    ) -> str:

        context_json = json.dumps(
            context.model_dump(),
            ensure_ascii=False,
            indent=2,
        )

        document_blocks = []

        for index, document in enumerate(
            documents,
            start=1,
        ):
            document_blocks.append(
                f"""
[참고자료 {index}]

출처:
{document.get("source", "알 수 없음")}

페이지:
{document.get("page")}

내용:
{document.get("content", "")}
""".strip()
            )

        documents_text = "\n\n".join(
            document_blocks
        )

        return f"""
당신은 학교 교사가 학부모 민원에 답변할 때 사용할
답변 초안을 작성하는 AI입니다.

아래 대화 내용과 문맥 분석 결과,
그리고 검색된 참고자료를 바탕으로
교사가 실제 학부모에게 전달할 수 있는
답변 초안을 작성하십시오.

==================================================
[민원 및 대화 내용]
==================================================

{content}

==================================================
[문맥 분석 결과]
==================================================

{context_json}

==================================================
[관련 참고자료]
==================================================

{documents_text}

==================================================
[작성 원칙]
==================================================

1. 학부모의 핵심 질문과 요청에 직접 답하십시오.

2. 민원의 사실관계를 임의로 추가하거나 변경하지 마십시오.

3. 학부모의 감정이나 문제 제기를 무시하지 말고,
   정중하고 차분한 어조를 사용하십시오.

4. 교사가 실제 학부모에게 전달할 수 있는
   자연스럽고 구체적인 문장으로 작성하십시오.

5. 확인되지 않은 사실을 확정적으로 말하지 마십시오.

6. 검색된 참고자료와 관련이 없는 법령,
   규정 또는 절차를 임의로 만들어내지 마십시오.

7. 참고자료가 현재 민원과 직접 관련되지 않는다면
   억지로 답변에 포함하지 마십시오.

8. 법률적 판단이나 학교의 최종 처분을
   임의로 확정하지 마십시오.

9. 필요한 경우
   "확인 후 안내드리겠습니다",
   "관련 기준을 확인하겠습니다"처럼
   확인이 필요한 사항임을 명확하게 표현하십시오.

10. 지나치게 장황하지 않게 작성하되,
    학부모가 다음 조치나 답변 내용을 이해할 수 있을 정도의
    정보를 포함하십시오.

11. 제목, 마크다운, JSON을 사용하지 마십시오.

12. 최종 답변 본문만 출력하십시오.

==================================================
[최종 작업]
==================================================

위 정보를 바탕으로
교사용 학부모 민원 답변 초안을 작성하십시오.
""".strip()

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