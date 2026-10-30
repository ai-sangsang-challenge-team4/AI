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