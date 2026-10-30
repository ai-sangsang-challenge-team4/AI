from typing import Any


SYSTEM_PROMPT = """
너는 학교 민원 분석을 지원하는 AI다.

사용자가 입력한 학교 민원 내용을 분석하고, 검색된 관련 문서를 참고하여
위험 요소를 판단한다.

반드시 아래 JSON 형식으로만 응답한다.

{
  "tags": [
    {
      "code": "위험 태그 코드",
      "state": "PRESENT 또는 ABSENT",
      "confidence": 0.0,
      "evidenceSpans": [
        {
          "text": "판단 근거가 되는 민원 내용",
          "start": null,
          "end": null
        }
      ],
      "reason": "판단 이유"
    }
  ],
  "metadata": {
    "modelName": "모델 이름",
    "temperature": 0.0
  }
}

주의사항:
- 민원 내용에 근거하여 판단한다.
- 검색된 문서에 없는 규정이나 사실을 임의로 만들어내지 않는다.
- 법률적 판단을 단정하지 않는다.
- 위험 요소가 명확하지 않다면 해당 위험 태그를 생성하지 않는다.
- evidenceSpans의 text는 가능한 한 실제 민원 내용에서 근거가 되는 표현을 사용한다.
- confidence는 0.0 이상 1.0 이하의 값이다.
- 반드시 유효한 JSON만 반환한다.
"""


def build_prompt(
    complaint: str,
    documents: list[dict[str, Any]],
) -> str:
    context_parts = []

    for index, document in enumerate(documents, start=1):
        content = document.get("content", "")
        source = document.get("source")
        page = document.get("page")

        context_parts.append(
            f"""
[검색 결과 {index}]
출처: {source or "알 수 없음"}
페이지: {page if page is not None else "알 수 없음"}

{content}
"""
        )

    context = "\n".join(context_parts)

    return f"""
{SYSTEM_PROMPT}

[민원 내용]
{complaint}

[관련 문서 검색 결과]
{context if context else "검색된 관련 문서가 없습니다."}

위 정보를 바탕으로 민원을 분석하라.

응답은 반드시 다음 JSON 구조를 따른다.

{{
  "tags": [
    {{
      "code": "THREAT",
      "state": "PRESENT",
      "confidence": 0.0,
      "evidenceSpans": [
        {{
          "text": "근거 문구",
          "start": null,
          "end": null
        }}
      ],
      "reason": "판단 이유"
    }}
  ],
  "metadata": {{
    "modelName": "사용한 모델 이름",
    "temperature": 0.0
  }}
}}
""".strip()


def build_softened_summary_prompt(complaint: str) -> str:
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

예시:

원문:
"선생님이 왜 이렇게 처리하는지 진짜 이해가 안 됩니다.
너무 화가 나니까 당장 제대로 처리해 주세요."

완충 요약:
"해당 처리 과정에 대해 이해하기 어려운 부분이 있으며,
관련 사항을 확인하고 적절한 조치를 요청함."

원문:
"이 요구를 안 들어주면 교육청에 신고하고 학교에 불이익을 주겠습니다."

완충 요약:
"요구사항이 받아들여지지 않을 경우 교육청 신고 등의 조치를 검토하겠다는 입장을 밝히며, 해당 요구사항의 처리를 요청함."

[민원 내용]
{complaint}

위 민원을 중립적이고 차분한 표현으로 요약하라.
""".strip()