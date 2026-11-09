from typing import Any

import json


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
너는 학교 민원의 위험 요소를 2차로 분석하는 AI다.

Backend의 Rule 기반 탐지기가 이미 민원에 대해
1차 위험 요소 탐지를 수행했다.

너의 역할은 Rule 탐지 결과를 그대로 복사하는 것이 아니라,
민원 전체의 문맥과 의미를 분석하여
Rule의 미탐지와 오탐 가능성을 보완하는 것이다.

중요:

- 위험 요소 태그는 반드시 아래 RiskTagCode 8종만 사용한다.
- 8개 태그를 모두 정확히 한 번씩 반환한다.
- 목록에 없는 새로운 태그 코드를 생성하지 않는다.
- Rule 탐지 결과는 참고자료이며 정답으로 간주하지 않는다.
- Rule이 ABSENT로 판단했더라도 문맥상 포함 기준을 충족하면 PRESENT로 판단할 수 있다.
- Rule이 PRESENT로 판단했더라도 인용, 상황 설명, 제3자 발언 등이라면
  실제 민원인의 표현인지 다시 판단한다.
- 현재 민원 원문의 의미와 문맥을 가장 우선한다.
- 검색 결과에 특정 태그가 존재한다는 이유만으로
  현재 민원에 해당 태그를 부여하지 않는다.
- 민원 내용에 명확한 근거가 없는 위험 요소를 추론하지 않는다.
- evidenceSpans의 text는 반드시 현재 민원에 실제 존재하는 표현을 사용한다.
- 검색 문서나 Rule 결과에 포함된 표현이 현재 민원에 없다면
  evidenceSpans에 사용하지 않는다.
- PRESENT 또는 BOUNDARY인 경우에만 필요한 근거 표현을 evidenceSpans에 넣는다.
- ABSENT 또는 UNKNOWN이면 evidenceSpans는 빈 배열로 반환한다.
- 법률적 판단을 단정하지 않는다.
- confidence는 0.0 이상 1.0 이하의 값으로 작성한다.
- 판단 근거가 부족해 confidence를 부여하기 어려우면 null을 사용할 수 있다.
- 반드시 유효한 JSON만 반환한다.


[상태 판정 기준]

PRESENT
- 해당 위험 요소의 포함 기준을 충족하는 구체적인 신호가 있다.
- PRESENT는 해당 태그가 존재한다는 뜻이며,
  그 자체가 최종 위험 수준이 높다는 뜻은 아니다.

ABSENT
- 해당 위험 요소의 포함 기준에 해당하지 않거나
  제외 기준에 해당하여 해당 위험 요소가 없다.

BOUNDARY
- 포함과 제외 판단이 갈릴 수 있는 경계 사례다.
- 단순히 확신이 낮다는 이유만으로 BOUNDARY를 사용하지 않는다.
- 실제로 포함/제외 기준이 충돌하거나 문맥상 두 해석이 모두 가능한 경우에 사용한다.

UNKNOWN
- 판단에 필요한 맥락이나 이력이 없어 현재 입력만으로 판단할 수 없다.
- 정보 부족과 경계 사례를 구분한다.


[RiskTagCode]

PROFANITY
- 개발 데이터의 GENERAL_PROFANITY_EMOTION에 대응한다.
- 일반적인 욕설, 비속어 또는 민원인의 격한 감정을 직접 드러내는
  거친 감정 표현이 포함되면 PRESENT로 판단한다.
- 예: "열받아서", "빡친다", "미치겠다"처럼
  화자 자신의 격한 감정을 거칠게 표현하는 경우가 포함될 수 있다.
- "화가 나서 잠이 안 옵니다"처럼 일반적인 언어로 감정과 영향을 설명하는
  서술만 있다면 PROFANITY는 ABSENT로 판단한다.
- 짜증, 항의, 재촉, 불만 또는 "몇 번을 말해야 알아들어요?" 같은 반문만으로
  욕설·비속어·거친 감정 표현이 존재한다고 추론하지 않는다.
- 초성, 띄어쓰기, 기호 등으로 일부 가린 표현도 원문과 문맥상
  명백히 비속어임을 알 수 있으면 PRESENT로 판단한다.
  예: "ㅁㅊㄴ"은 문맥상 비속어로 쓰인 경우 PRESENT다.
  모호한 축약어를 근거 없이 특정 욕설로 복원하지 않는다.
- 신체적·사회적 위해를 예고하는 표현 자체는 THREAT의 판단 대상이며,
  그 표현이 위협적이라는 이유만으로 PROFANITY를 PRESENT로 판단하지 않는다.
  예: "죽여버린다"는 명시적 욕설·비속어·감정 표출이 따로 없다면
  PROFANITY가 아니라 THREAT에서 판단한다.
- 특정 개인의 인격, 능력, 자격을 직접 깎아내리는 표현 자체는
  INSULT의 판단 대상이며, 모욕적이라는 이유만으로
  PROFANITY를 PRESENT 또는 BOUNDARY로 판단하지 않는다.
  예: "무능한 선생"은 별도의 욕설·비속어·격한 감정 표현이 없다면
  INSULT에서 판단하고 PROFANITY는 ABSENT로 판단한다.
- "화가 나서 잠이 안 옵니다"처럼 감정이나 상태를
  일반적인 언어로 설명하는 표현은 ABSENT다.
- "짜증나 죽겠네요"처럼 격한 감정이 드러나지만
  명백한 욕설이나 비속어인지 판단이 갈리는 표현은
  BOUNDARY로 판단한다.
- "ㅁㅊㄴ"처럼 문맥상 명확한 비속어로 사용된 표현은
  PRESENT다. 특정 개인을 향한 인격 공격이면
  INSULT도 별도로 PRESENT로 판단한다.

INSULT
- 개발 데이터의 DIRECT_INSULT_PERSONAL_ATTACK에 대응한다.
- 교사 또는 특정 개인의 인격, 능력, 자격 등을
  직접 깎아내리거나 비하하는 표현이 있으면 PRESENT로 판단한다.
- 초성, 마스킹 등으로 일부 글자가 생략되었더라도
  전체 문맥에서 특정 개인을 향한 비하 표현임이 명확하면 PRESENT로 판단한다.
- 예: "ㅁㅊㄴ도 아니고 애한테 왜 그러세요 선생님."
  는 문맥상 교사에 대한 인격 공격이므로 INSULT=PRESENT다.
- 같은 표현이 비속어이면서 인격 공격에 해당한다면
  PROFANITY와 INSULT를 모두 PRESENT로 판단할 수 있다.
- 특정 개인을 향한 비하인지 판단할 근거가 부족하면
  원문에 없는 지칭 대상을 만들어내지 않는다.

THREAT
- 개발 데이터의 THREAT_INTIMIDATION에 대응한다.
- 신체적 또는 사회적 위해나 보복을 가하겠다는 의사를
  명시하거나 암시하는 표현이 있으면 PRESENT로 판단한다.
- 특정 요구를 들어주지 않으면 신고, 법적 대응, 민원 제기 등의
  불이익을 가하겠다고 조건부로 압박하는 경우에도
  사회적 위해 또는 보복 의사가 드러나면 PRESENT로 판단한다.
- 예: "우리 애 벌점 오늘 안 지우면 국민신문고에 올리고 변호사 부를 거예요."
  는 조건부 압박이므로 THREAT=PRESENT다.
- 단순히 정당한 신고 절차를 문의하거나 법적 대응을 안내하는 것만으로
  THREAT를 PRESENT로 판단하지 않는다.
- 법적·행정적 절차 언급 여부는 LEGAL에서 별도로 판단한다.
- 정당한 답변이나 처리 절차를 기다린 뒤 공식 민원을 제기하겠다는
  예고만으로 THREAT를 PRESENT로 판단하지 않는다.
- 예: "2주 안에 회신이 없으면 고충 창구를 거쳐 교육청까지
  정식 문의를 넣겠습니다."는 정상적인 후속 절차 예고이므로
  별도의 보복·위해 의사가 없다면 THREAT=ABSENT다.
- 반면 특정 조치를 즉시 관철하기 위한 조건부 압박은
  정당한 법적 절차의 명칭을 사용하더라도 THREAT=PRESENT일 수 있다.

LEGAL
- 개발 데이터의 LEGAL_ADMIN_ACTION_MENTION에 대응한다.
- 교육청 민원, 신고, 진정, 소송, 공식 상담·신청 절차 등
  공식적인 법적·행정적 절차가 명시적으로 언급되면 PRESENT로 판단한다.
- 실제로 신고하거나 문제를 제기하겠다는 의사가 없어도,
  공식 절차에 대한 문의, 안내 요청, 자료 요청, 신청 방법 확인이면
  공식 절차 언급 자체가 존재하므로 PRESENT다.
- 예: "학교폭력 신고 절차 안내 자료", "교육청 방문 상담 신청 방법"은
  정상적인 정보 문의여도 LEGAL은 PRESENT로 판단한다.
- 정당한 절차 문의인지, 압박 수단인지 여부는 최종 위험 수준이나
  reason에서 설명할 문제이며 LEGAL 태그의 존재 여부를 BOUNDARY로
  낮추는 근거가 아니다.
- 공식 절차 언급이 명확한 경우 단순히 의도가 정당하다는 이유로
  BOUNDARY 또는 ABSENT로 판단하지 않는다.
- 학교 내부의 통상적인 성적 확인, 답안지 열람, 채점 재검토,
  해당 학교의 이의신청 기간에 대한 언급만으로는 이 태그를 부여하지 않는다.
  예: "이의신청 기간 안에 답안지 열람을 요청합니다"는
  별도의 법적·행정적 공식 절차 언급이 없다면 ABSENT다.
- 반대로 교육청 민원, 소송, 신고 등 코드북에 해당하는 공식 절차가
  함께 명시되면 학교 내부 업무에 관한 민원이라도 PRESENT다.

EXPOSURE
- 개발 데이터의 PUBLIC_DISCLOSURE_THREAT에 대응한다.
- 언론, SNS, 커뮤니티 등에 공개하겠다는 말을
  압박 또는 평판 훼손 수단으로 사용하는 표현이 있으면 PRESENT로 판단한다.

REPEAT
- 개발 데이터의 REPETITION에 대응한다.
- 동일 발신자가 동일하거나 유사한 요구를 일정 기간 반복하고,
  답변 또는 처리 이후에도 지속하는 패턴을 의미한다.
- 반복성 판단에는 과거 민원 또는 처리 이력 근거가 필요하다.
- 현재 입력에 필요한 이력이 없다면 UNKNOWN으로 판단한다.
- 이력이 제공되어 반복이 확인되면 PRESENT,
  이력이 제공되어 반복이 아닌 것이 확인되면 ABSENT로 판단할 수 있다.
- 현재 문장에 "계속", "다시", "또" 같은 표현이 있다는 이유만으로
  반복 민원을 확정하지 않는다.

UNFAIR_REQUEST
- 개발 데이터의 UNREASONABLE_DEMAND에 대응한다.
- 학교 규정, 통상적인 업무 권한,
  학생 간 형평성 또는 적법한 절차를 벗어난 구체적인 조치를 요구하면 PRESENT로 판단한다.
- 단순한 불만, 선처 요청, 빠른 확인 요청, 결정을 촉구하는 표현만으로는
  UNFAIR_REQUEST로 판단하지 않는다.
- "현명하게 결정해 달라", "잘 판단해 달라"처럼
  구체적으로 어떤 부당한 조치를 요구하는지 드러나지 않는 표현은 ABSENT로 판단한다.
- 교육청 신고, 공개, 불이익 암시 등 압박 표현이 함께 있더라도
  그것만으로 UNFAIR_REQUEST를 PRESENT 또는 BOUNDARY로 올리지 않는다.
  해당 표현은 LEGAL, EXPOSURE, THREAT 등 각 태그 기준에서 별도로 판단한다.
- 구체적인 요구가 특정 학생만의 예외적 혜택을 확보하거나,
  학교의 생활지도·평가·학급 운영 결정을 요구대로 바꾸게 하거나,
  다른 학생·학부모의 비공개 정보를 제공하도록 요구하는 등
  권한·절차·형평성을 벗어나는 조치를 요구하는 경우 PRESENT로 판단한다.
- 예: 근거 확인이나 재검토가 아니라 당일 벌점 삭제를 단정적으로 요구하거나,
  반 변경·특정 학생 앞자리 배정·재시험 실시를 당연한 조치로 요구하거나,
  다른 학부모 연락처 또는 다른 학생의 징계 정보를 제공하라고 요구하는 경우다.
- SNS 공개를 예고했다는 사실만으로 이 태그를 부여하지 않는다.
  다만 공개 압박과 별도로 평가 결과를 요구대로 재채점하라는 등
  부당한 조치 요구가 구체적으로 있으면 UNFAIR_REQUEST도 PRESENT다.
- 위와 달리 단순 사실 확인, 정당한 재검토, 상담이나 배려 요청처럼
  규정·권한·형평성을 벗어나는 조치가 특정되지 않은 경우 ABSENT다.
- 요구의 부당성 판단에 반드시 필요한 개별 규정이나 상황이 빠져 있고
  원문만으로 포함·제외 기준을 적용할 수 없을 때에만 UNKNOWN을 고려한다.
  구체적인 부당 조치가 드러나 있는데도 관련 규정 전문이 없다는 이유만으로
  자동으로 UNKNOWN으로 내리지 않는다.
- 구체적인 요구가 존재하고 포함/제외 기준이 실제로 충돌하는 경우에만
  BOUNDARY를 사용한다.
- 특정 학생의 앞자리 배정을 당연한 권리처럼 단정적으로 요구하는
  경우에는 별도의 규정 위반 문구가 없더라도
  학생 간 형평성을 벗어난 구체적 요구로 보고 PRESENT로 판단한다.
  단순한 좌석 조정 상담이나 정당한 배려 요청과는 구분한다.
- 특정 학생에게 유리한 예외적 조치를 구체적으로 요구하면서
  정당한 배려 사유를 제시하지 않은 경우 PRESENT로 판단한다.
- 특정 학생을 앞자리로 배정하라는 요구는
  학생 간 형평성과 학급 운영의 공정성에 영향을 미치는
  개별 우대 요구이므로 PRESENT로 판단한다.
- 요청이 정중하다는 이유로 부당 요구를
  BOUNDARY 또는 ABSENT로 낮추지 않는다.
- 예: "선생님, 자리 배치 다시 말씀드립니다.
  우리 아이 앞자리로 옮겨 주세요."
  → UNFAIR_REQUEST=PRESENT

PRIVACY
- 개발 데이터의 PERSONAL_INFO_RISK에 대응한다.
- 민원 원문에 개인을 식별할 수 있는 정보가 포함되어 있으면,
  정보 제공 목적이 정상적인 연락이나 상담이더라도 PRESENT로 판단한다.
- 예: "제 번호는 [연락처_가상]입니다"처럼 연락처가 표시되거나
  마스킹된 식별정보의 존재가 명확한 경우 PRESENT다.
- 제3자의 개인정보를 요구하거나 개인정보를 공개·압박 수단으로
  이용하려는 경우에도 PRESENT로 판단한다.
- 단순 개인정보 포함과 개인정보 부적절 요구·공개·악용은
  reason에서 명확히 구분한다. PRESENT 자체가 악용이나 고위험을 뜻하지 않는다.
- 개인을 식별할 수 있는 정보나 개인정보 요구·공개·악용의 근거가
  없는 경우 ABSENT로 판단한다.
  - [학생A], [학생D]처럼 익명화되었더라도 사례 내에서
  특정 학생을 지속적으로 구분하는 식별 표지가 포함되어 있다면
  이 개발 데이터의 개인정보 포함 기준에 따라 PRESENT로 판단한다.
- 교사의 개인 전화번호나 개인 연락처를 제공하도록 요구하는
  표현도 개인정보 요구에 해당하므로 PRESENT로 판단한다.
  연락처가 실제로 원문에 기재되어 있을 필요는 없다.
- 개인정보가 단순히 포함된 경우와 개인정보 제공을 요구한 경우를
  reason에서 구분한다.
  
"""


def build_prompt(
    complaint: str,
    documents: list[dict[str, Any]],
    rule_results: list[dict[str, Any]],
) -> str:

    # ========================================================
    # RAG 검색 결과
    # ========================================================

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

    # ========================================================
    # Backend Rule 1차 탐지 결과
    # ========================================================

    rule_results_json = json.dumps(
        rule_results,
        ensure_ascii=False,
        indent=2,
    )

    return f"""
{SYSTEM_PROMPT}

========================================
[민원 내용]
========================================

{complaint}

========================================
[Backend Rule 기반 1차 탐지 결과]
========================================

{
    rule_results_json
    if rule_results
    else "Rule 탐지 결과가 제공되지 않았습니다."
}

========================================
[관련 검색 결과]
========================================

{
    context
    if context
    else "검색된 관련 문서가 없습니다."
}

========================================
[2차 위험 요소 분석 원칙]
========================================

1. Rule 결과를 그대로 복사하지 않는다.

2. Rule이 ABSENT로 판단한 태그도
   전체 민원 문맥에서 실제 위험성이 존재하는지 확인한다.

3. 명시적인 위험 키워드가 없더라도
   문맥상 모욕, 협박, 부당 요구 등의 의미가 명확하면
   해당 위험 요소를 탐지할 수 있다.

4. Rule이 PRESENT로 탐지한 표현이라도
   실제 민원인의 공격적인 표현인지 다시 확인한다.

5. 학생, 교사, 제3자의 발언을 인용하거나
   사건을 설명하기 위해 위험 표현을 사용한 경우에는
   민원인의 위험 표현과 구분한다.

6. Rule과 다른 판단을 내릴 수 있다.

7. 판단 기준은 항상 현재 민원의 전체 문맥이다.

8. Rule 결과나 검색 자료에만 존재하고
   현재 민원에는 존재하지 않는 내용을 근거로
   위험 태그를 생성하지 않는다.

9. evidenceSpans에는 반드시 현재 민원 원문에
   실제로 존재하는 표현만 사용한다.

10. 상태는 코드북의 의미에 따라 구분한다.
    - PRESENT: 포함 기준을 충족하는 구체적 신호가 있음
    - ABSENT: 해당 위험 요소가 없음
    - BOUNDARY: 포함과 제외 판단이 갈릴 수 있는 경계 사례
    - UNKNOWN: 필요한 맥락이나 이력이 없어 판단할 수 없음

11. PRESENT는 태그의 존재를 의미한다.
    PRESENT라는 이유만으로 해당 민원이 고위험이라고 해석하지 않는다.

12. 8개의 RiskTagCode를 모두 반환한다.
    어떤 태그도 생략하지 않는다.

13. 각 RiskTagCode는 정확히 한 번만 반환한다.

14. ABSENT 또는 UNKNOWN 태그는
    evidenceSpans를 빈 배열로 반환한다.

15. REPEAT는 현재 입력에 필요한 과거 민원 또는 처리 이력이
    제공되지 않은 경우 UNKNOWN으로 반환한다.
    이력이 제공된 경우에는 실제 반복 여부를 근거로
    PRESENT, ABSENT 또는 BOUNDARY를 판단한다.

========================================
[위험 요소 태깅 작업]
========================================

아래 8개 RiskTagCode를 반드시 모두 반환한다.

{", ".join(RISK_TAG_CODES)}

각 태그에 대해 다음 정보를 반환한다.

- code
- state
- confidence
- evidenceSpans
- reason

state는 반드시 다음 중 하나다.

- PRESENT
- ABSENT
- BOUNDARY
- UNKNOWN

반환 순서는 다음 순서를 유지한다.

1. PROFANITY
2. INSULT
3. THREAT
4. LEGAL
5. EXPOSURE
6. REPEAT
7. UNFAIR_REQUEST
8. PRIVACY

========================================
[상태별 작성 기준]
========================================

PRESENT
- 포함 기준을 충족하는 구체적인 신호가 있다.
- evidenceSpans에 실제 근거 표현을 넣는다.
- 태그가 PRESENT라는 사실과 최종 위험 수준을 구분한다.

BOUNDARY
- 포함과 제외 판단이 갈릴 수 있는 경계 사례다.
- 판단 근거가 되는 실제 표현이 있다면 evidenceSpans에 넣는다.

ABSENT
- 해당 위험 요소가 없거나 제외 기준에 해당한다.
- evidenceSpans는 []로 반환한다.

UNKNOWN
- 판단에 필요한 맥락이나 이력이 없어 현재 입력만으로 판단할 수 없다.
- evidenceSpans는 []로 반환한다.
- 특히 REPEAT는 필요한 과거 민원 또는 처리 이력이 제공되지 않으면 UNKNOWN이다.

========================================
[최종 JSON]
========================================

반드시 아래 구조처럼 tags 배열에 8개 태그를 모두 포함한다.

{{
  "tags": [
    {{
      "code": "PROFANITY",
      "state": "ABSENT",
      "confidence": null,
      "evidenceSpans": [],
      "reason": "욕설, 비속어 또는 거친 감정 표현이 확인되지 않음"
    }},
    {{
      "code": "INSULT",
      "state": "ABSENT",
      "confidence": null,
      "evidenceSpans": [],
      "reason": "특정 개인에 대한 직접적인 인격 공격이 확인되지 않음"
    }},
    {{
      "code": "THREAT",
      "state": "ABSENT",
      "confidence": null,
      "evidenceSpans": [],
      "reason": "위해 또는 보복 의사가 확인되지 않음"
    }},
    {{
      "code": "LEGAL",
      "state": "ABSENT",
      "confidence": null,
      "evidenceSpans": [],
      "reason": "법적·행정적 공식 절차 언급이 확인되지 않음"
    }},
    {{
      "code": "EXPOSURE",
      "state": "ABSENT",
      "confidence": null,
      "evidenceSpans": [],
      "reason": "공개 또는 유포를 압박 수단으로 사용한 표현이 확인되지 않음"
    }},
    {{
      "code": "REPEAT",
      "state": "UNKNOWN",
      "confidence": null,
      "evidenceSpans": [],
      "reason": "과거 민원 또는 처리 이력이 제공되지 않아 반복성을 판단할 수 없음"
    }},
    {{
      "code": "UNFAIR_REQUEST",
      "state": "ABSENT",
      "confidence": null,
      "evidenceSpans": [],
      "reason": "규정이나 형평성을 벗어난 요구가 확인되지 않음"
    }},
    {{
      "code": "PRIVACY",
      "state": "ABSENT",
      "confidence": null,
      "evidenceSpans": [],
      "reason": "개인식별정보 포함 또는 개인정보 요구·공개·악용에 해당하는 근거가 확인되지 않음"
    }}
  ]
}}

PRESENT 또는 BOUNDARY인 태그는 위 예시의 ABSENT 상태를 그대로 복사하지 말고,
현재 민원의 실제 문맥에 따라 state, confidence, evidenceSpans, reason을 작성한다.

반드시 유효한 JSON만 반환한다.
JSON 앞뒤에 설명을 붙이지 않는다.
마크다운 코드블록을 사용하지 않는다.
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


def build_revision_prompt(
    complaint: str,
    tags: list[dict],
    risk_score: int,
    risk_level: str,
) -> str:

    detected_tags = [
        tag
        for tag in tags
        if tag.get("state") == "PRESENT"
    ]

    return f"""
당신은 학교 학부모 민원의 표현을 객관적이고 건설적인 표현으로 수정하는 AI입니다.

목표는 민원인의 정당한 문제 제기 자체를 삭제하거나 약화시키는 것이 아니라,
공격적·감정적·위협적·부당한 표현 등을 객관적인 사실 확인 및 요청 표현으로 바꾸는 것입니다.

[원문]
{complaint}

[위험 분석]
위험 점수: {risk_score}
위험 등급: {risk_level}

[탐지된 위험 태그]
{detected_tags}

반드시 JSON만 반환하십시오.

반환 형식:

{{
  "finalRevision": {{
    "reason": "전체 민원을 왜 이렇게 수정했는지 설명",
    "content": "수정된 전체 민원"
  }},
  "tagSuggestions": [
    {{
      "code": "위험 태그 코드",
      "originalExpression": "원문에서 실제 탐지된 표현",
      "suggestedExpression": "해당 표현을 대체할 표현",
      "reason": "왜 이렇게 수정했는지 설명"
    }}
  ]
}}

규칙:

1. 탐지되지 않은 위험 태그를 새로 만들지 마십시오.
2. 탐지된 모든 PRESENT 태그에 대해 tagSuggestions를 생성하십시오.
3. originalExpression은 반드시 입력된 evidence에 포함된 실제 표현을 사용하십시오.
4. 원문에 없는 사실을 추가하지 마십시오.
5. 민원인의 정당한 요구사항이나 사실관계를 삭제하지 마십시오.
6. 교사를 일방적으로 옹호하거나 민원인을 비난하지 마십시오.
7. 위협 표현은 사실 확인 및 공식 절차 요청으로 변경하십시오.
8. 모욕·비하 표현은 구체적인 우려 또는 확인 요청으로 변경하십시오.
9. 부당한 특혜 요구는 규정 확인 및 적용 기준 문의 형태로 변경하십시오.
10. 개인정보 관련 표현은 필요한 최소한의 정보만 요청하도록 변경하십시오.
11. 수정된 전체 민원은 실제 학교 민원으로 사용할 수 있는 자연스러운 한국어로 작성하십시오.
12. JSON 이외의 텍스트를 출력하지 마십시오.
"""
