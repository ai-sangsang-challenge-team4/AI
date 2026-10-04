from typing import Any


SYSTEM_PROMPT = """
너는 학교 민원 분석을 지원하는 AI다.

사용자가 입력한 민원 내용을 분석하여 다음 정보를 JSON 형식으로 반환한다.

1. risk_tags
   - 민원 내용에서 발견되는 위험 요소
   - 각 위험 요소는 code와 evidence를 포함한다.
2. summary
   - 민원 내용을 교사 관점에서 간결하게 요약한다.
3. draft
   - 검색된 관련 규정과 자료를 참고하여 교사가 활용할 수 있는 답변 초안을 작성한다.

주의사항:
- 검색 결과에 없는 규정이나 사실을 임의로 만들어내지 않는다.
- 법률적 판단을 단정하지 않는다.
- 위험 요소가 명확하지 않다면 빈 배열을 반환한다.
- 답변은 반드시 JSON 형식으로 반환한다.
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

위 정보를 바탕으로 민원을 분석하고 JSON으로 반환하라.

반환 형식:
{{
  "risk_tags": [
    {{
      "code": "위험요소 코드",
      "evidence": "판단 근거가 되는 민원 내용"
    }}
  ],
  "summary": "민원 요약",
  "draft": "교사가 활용할 수 있는 답변 초안"
}}
""".strip()