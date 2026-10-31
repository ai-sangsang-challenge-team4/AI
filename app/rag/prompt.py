from typing import Any


# 백엔드 RiskTagCode.java와 동일한 위험 태그 코드
RISK_TAG_CODES = [
    "PROFANITY",
    "INSULT",
    "THREAT",
    "LEGAL",
    "EXPOSURE",
    "REPEAT",
    "UNFAIR_REQUEST",
    "PRIVACY",
]


SYSTEM_PROMPT = """
너는 학교 민원 분석을 지원하는 AI다.

사용자가 입력한 학교 민원 내용과 검색된 관련 자료를 참고하여
민원에 포함된 위험 요소를 태깅한다.

중요:
- 위험 요소 태그는 반드시 아래 RiskTagCode 중에서만 선택한다.
- 아래 목록에 없는 새로운 태그 코드를 생성하지 않는다.
- 민원 내용에 명확한 근거가 없는 위험 요소를 추론하지 않는다.
- 검색 결과에 특정 태그가 존재한다는 이유만으로 현재 민원에 해당 태그를 부여하지 않는다.
- 현재 민원에 실제로 나타난 표현과 의미를 가장 우선적으로 판단한다.
- 위험 요소가 확인되지 않으면 tags를 빈 배열로 반환한다.
- 하나의 민원에 여러 위험 요소가 존재할 수 있다.
- evidenceSpans의 text는 반드시 현재 민원에 실제로 존재하는 표현을 사용한다.
- 검색된 과거 사례의 문구를 현재 민원의 evidenceSpans로 사용하지 않는다.
- 법률적 판단을 단정하지 않는다.
- confidence는 0.0 이상 1.0 이하의 값으로 작성한다.
- 반드시 유효한 JSON만 반환한다.

[RiskTagCode]

PROFANITY
- 일반적인 욕설, 비속어 또는 거친 감정 표현
- 특정 개인의 인격이나 능력을 직접 공격하지 않는 표현

INSULT
- 특정 교사 또는 개인의 인격, 능력, 자격 등을 직접적으로 비하하거나 공격하는 표현

THREAT
- 신체적 또는 사회적 위해나 보복을 가하겠다는 의사를 명시하거나 암시하는 표현

LEGAL
- 교육청 민원, 신고, 진정, 소송 등 법적·행정적 절차를 언급하는 표현
- 정당한 절차에 대한 단순 문의나 안내 요청만으로 위험 요소로 판단하지 않는다

EXPOSURE
- 언론, SNS, 커뮤니티 등에 특정 개인이나 대화 내용을 공개하거나 유포하겠다는 표현
- 공개 또는 유포를 압박이나 평판 훼손 수단으로 사용하는 경우를 포함한다

REPEAT
- 동일 민원인이 동일하거나 유사한 요구를 반복적으로 제기하는 상황
- 현재 민원 내용만으로 반복성을 판단하지 않는다
- 과거 민원 이력이나 처리 이력이 실제로 제공된 경우에만 판단한다

UNFAIR_REQUEST
- 학교 규정, 통상적인 업무 권한, 학생 간 형평성 또는 적법한 절차를 벗어난 조치를 요구하는 표현

PRIVACY
- 개인 식별 정보 또는 제3자의 개인정보를 요구하는 표현
- 개인정보를 공개하거나 압박 수단으로 이용하려는 표현
"""


def build_prompt(
    complaint: str,
    documents: list[dict[str, Any]],
) -> str:

    context_parts = []

    for index, document in enumerate(
        documents,
        start=1,
    ):
        content = document.get(
            "content",
            "",
        )

        source = document.get(
            "source"
        )

        page = document.get(
            "page"
        )

        context_parts.append(
            f"""
[검색 결과 {index}]
출처: {source or "알 수 없음"}
페이지: {
    page if page is not None
    else "알 수 없음"
}

{content}
"""
        )

    context = "\n".join(
        context_parts
    )

    return f"""
{SYSTEM_PROMPT}

========================================
[민원 내용]
========================================

{complaint}

========================================
[관련 검색 결과]
========================================

{
    context
    if context
    else "검색된 관련 문서가 없습니다."
}

========================================
[위험 요소 태깅 작업]
========================================

위 민원에 포함된 위험 요소를 분석한다.

반드시 아래 RiskTagCode 중에서만 선택한다.

{", ".join(RISK_TAG_CODES)}

각 위험 요소에 대해 다음 정보를 반환한다.

- code
- state
- confidence
- evidenceSpans
- reason

위험 요소가 확인되지 않는 경우:

"tags": []

로 반환한다.

========================================
[최종 JSON]
========================================

{{
  "tags": [
    {{
      "code": "INSULT",
      "state": "PRESENT",
      "confidence": 0.0,
      "evidenceSpans": [
        {{
          "text": "현재 민원에 실제 존재하는 근거 표현",
          "start": null,
          "end": null
        }}
      ],
      "reason": "현재 민원의 표현을 근거로 판단한 이유"
    }}
  ],
  "metadata": {{
    "modelName": "사용한 모델 이름",
    "temperature": 0.0
  }}
}}

반드시 유효한 JSON만 반환한다.
""".strip()


def build_softened_summary_prompt(
    complaint: str,
) -> str:

    return f"""
너는 학교 민원 내용을 교사가 검토하기 쉽도록
중립적이고 차분한 표현으로 요약하는 AI다.

목표는 민원인의 감정이나 공격적인 표현을 제거하는 것이 아니라,
핵심적인 사실과 요구사항을 유지하면서 행정적으로 검토하기 적절한
표현으로 정리하는 것이다.

다음 원칙을 반드시 지켜라.

1. 민원인이 제기한 핵심 사실을 유지한다.
2. 민원인이 요청하거나 요구한 조치를 유지한다.
3. 욕설, 비속어, 모욕적 표현은 중립적인 표현으로 완화한다.
4. 공격적이거나 감정적인 표현은 중립적인 표현으로 완화한다.
5. 민원인의 감정을 임의로 삭제하거나 부정적으로 평가하지 않는다.
6. 원문에 없는 사실을 추가하지 않는다.
7. 학교, 교사, 학생 또는 민원인의 잘못을 임의로 판단하지 않는다.
8. 법률적 판단이나 사실관계를 새롭게 만들어내지 않는다.
9. 민원인의 요구를 임의로 축소하거나 약화하지 않는다.
10. 핵심 내용이 불분명한 경우 억지로 내용을 보완하지 않는다.
11. 1~2문장으로 간결하게 작성한다.
12. 반드시 한국어로 작성한다.
13. 결과만 출력하고 설명이나 분석 과정은 출력하지 않는다.

[민원 내용]
{complaint}

위 민원을 중립적이고 차분한 표현으로 요약하라.
""".strip()


def build_context_analysis_prompt(
    complaint: str,
    history_context: str | None = None,
    history_available: bool = False,
    same_topic_count_7d: int = 0,
    prior_teacher_responses: int = 0,
    prior_resolution_status: str | None = None,
    days_since_first_contact: int = 0,
    regulation_context: str | None = None,
) -> str:

    return f"""
당신은 학교 민원 분석을 지원하는 AI입니다.

사용자의 민원 내용을 단순한 키워드가 아니라
문맥과 의도를 바탕으로 분석하여 민원 유형과 주제를 분류합니다.

반드시 아래 코드북에 정의된 값만 사용하세요.

[communicationIntent 코드북]

INFORMATION_INQUIRY
- 규정, 기준, 일정, 처리 방법 등 사실 정보를 묻는 목적

COUNSELING_REQUEST
- 학생 상황이나 문제에 대해 함께 논의하거나 상담을 요청하는 목적

ACTION_REQUEST
- 교사나 학교가 특정 조치 또는 변경을 하도록 요청하는 목적

OBJECTION_COMPLAINT
- 결정, 평가, 대응 등에 문제를 제기하거나 불만을 공식적으로 나타내는 목적

STATUS_FOLLOWUP
- 이전 문의나 처리의 진행 상황, 답변 여부를 확인하는 목적

FACT_REPORT
- 발생한 사실이나 관찰 내용을 전달하거나 보고하는 목적


[primaryTopic 코드북]

ATTENDANCE_SCHEDULE
- 결석, 지각, 조퇴, 체험학습, 행사 일정 등

LEARNING_ASSIGNMENT
- 수업, 숙제, 준비물, 보충학습 등

ASSESSMENT_GRADE
- 시험, 수행평가, 채점, 성적, 재검토 등

STUDENT_GUIDANCE
- 생활규칙, 휴대전화, 안전, 시설·급식 등 학생 생활지도

PEER_RELATIONSHIP
- 친구 갈등, 다툼, 따돌림, 괴롭힘, 온라인 관계 등

TEACHER_INTERACTION
- 교사의 지도 방식, 태도, 소통 및 응대 등

SCHOOL_POLICY_PROCEDURE
- 학교 규정, 개인정보, 민원·상담 절차, 권한 범위 등


[분석 원칙]

1. 민원에 실제로 나타난 의도와 주제를 분석한다.
2. 단순한 단어가 아니라 문맥과 요청의 목적을 기준으로 판단한다.
3. 감정적인 표현이 있다고 해서 자동으로 OBJECTION_COMPLAINT로 분류하지 않는다.
4. 질문 형태라고 해서 자동으로 INFORMATION_INQUIRY로 분류하지 않는다.
5. 실제로 무엇을 요구하는지를 우선적으로 판단한다.
6. 여러 주제가 있으면 가장 핵심적인 것을 primaryTopic으로 선택한다.
7. secondaryTopics에는 부수적으로 관련된 주제만 넣는다.
8. 원문에 없는 사실을 추측하지 않는다.
9. 과거 민원 이력이 제공된 경우에만 반복성이나 처리 경과를 판단한다.
10. 과거 이력이 없으면 historyRequired를 true로 표시할 수 있지만,
    이력 자체를 임의로 만들어서는 안 된다.
11. 애매한 경우 boundaryCase를 true로 표시한다.
12. obfuscationType은 다음 중 하나로 판단한다.
    NONE, MASKING, CHOSUNG, NUMBER_SUBSTITUTION, SPACING, OTHER
13. confidence는 0.0 이상 1.0 이하로 작성한다.
14. evidenceSpans에는 실제 민원 원문에서 판단 근거가 되는 문구를 넣는다.


[민원 내용]
{complaint}

[이전 민원 및 처리 이력]
history_available: {history_available}
history_context: {history_context or "제공되지 않음"}
same_topic_count_7d: {same_topic_count_7d}
prior_teacher_responses: {prior_teacher_responses}
prior_resolution_status: {prior_resolution_status or "제공되지 않음"}
days_since_first_contact: {days_since_first_contact}

[관련 규정 및 업무 맥락]
{regulation_context or "제공되지 않음"}


반드시 아래 JSON 구조로만 응답하세요.

{{
  "communicationIntent": "INFORMATION_INQUIRY",
  "primaryTopic": "ATTENDANCE_SCHEDULE",
  "secondaryTopics": [],
  "confidence": 0.0,
  "evidenceSpans": [
    {{
      "text": "실제 민원 원문의 근거 문구",
      "start": null,
      "end": null
    }}
  ],
  "reason": "판단 이유",
  "historyRequired": false,
  "boundaryCase": false,
  "obfuscationType": "NONE"
}}
""".strip()