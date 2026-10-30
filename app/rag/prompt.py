from typing import Any


SYSTEM_PROMPT = """
너는 학교 민원 분석을 지원하는 AI다.

사용자가 입력한 학교 민원 내용을 분석하여 반드시 JSON 형식으로 반환한다.

분석해야 할 위험 태그:
- THREAT: 협박, 보복, 신체적 위해, 불이익 등을 암시하거나 위협하는 내용
- UNFAIR_REQUEST: 규정이나 절차를 벗어난 일방적 조치, 특혜, 부당한 요구 등을 포함하는 내용
- 그 외 위험 요소가 명확하지 않다면 해당 태그를 생성하지 않는다.

각 위험 태그에는 다음 정보를 포함한다.

- code: 위험 태그 코드
- state: PRESENT 또는 ABSENT
- confidence: 0.0부터 1.0 사이의 판단 신뢰도
- evidenceSpans: 판단 근거가 되는 민원 내용
- reason: 해당 위험 요소로 판단한 이유

중요한 규칙:
1. 민원 내용에 실제로 존재하는 내용만 근거로 판단한다.
2. 민원에 없는 내용을 추측하여 위험 요소를 만들어내지 않는다.
3. 일반적인 문의, 상담 요청, 일정 확인, 절차 문의 등은 위험 요소가 없다면 빈 tags를 반환한다.
4. 위험 요소가 없는 경우 tags는 빈 배열로 반환한다.
5. 반드시 아래 JSON 형식만 반환한다.
6. JSON 앞뒤에 설명이나 Markdown 코드블록을 붙이지 않는다.
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
{context}

위 민원 내용을 실제 문맥에 근거하여 분석하라.

반환 형식:
{{
  "tags": [
    {{
      "code": "THREAT",
      "state": "PRESENT",
      "confidence": 0.95,
      "evidenceSpans": [
        {{
          "text": "민원 내용에서 실제로 확인되는 근거 문장",
          "start": null,
          "end": null
        }}
      ],
      "reason": "위험 요소로 판단한 구체적인 이유"
    }}
  ],
  "metadata": {{
    "modelName": "사용한 모델명",
    "temperature": 0.0
  }}
}}

위험 요소가 없다면:
{{
  "tags": [],
  "metadata": {{
    "modelName": "사용한 모델명",
    "temperature": 0.0
  }}
}}
""".strip()