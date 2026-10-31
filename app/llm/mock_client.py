import json
import re

from app.llm.client import LlmClient


class MockLlmClient(LlmClient):

    def generate(self, prompt: str) -> str:
        complaint = self._extract_complaint(prompt)

        tags = []

        # --------------------------------------------------
        # 1. GENERAL_PROFANITY_EMOTION
        # --------------------------------------------------
        profanity_patterns = [
            "개판",
            "ㄱ판",
            "무능",
            "무책임",
            "엉망",
            "한심",
            "답답",
            "짜증",
            "화가",
            "어이없",
            "말도 안",
        ]

        profanity_match = self._find_match(
            complaint,
            profanity_patterns,
        )

        if profanity_match:
            tags.append({
                "code": "GENERAL_PROFANITY_EMOTION",
                "state": "PRESENT",
                "confidence": 0.95,
                "evidenceSpans": [
                    {
                        "text": profanity_match,
                        "start": None,
                        "end": None,
                    }
                ],
                "reason": (
                    "민원 내용에서 비속어 또는 강한 감정적 표현이 "
                    "확인되었습니다."
                ),
            })

        # --------------------------------------------------
        # 2. DIRECT_INSULT_PERSONAL_ATTACK
        # --------------------------------------------------
        insult_patterns = [
            "무능",
            "무책임",
            "한심",
            "멍청",
            "무식",
            "자격이 없",
            "능력이 없",
            "쓸모없",
            "형편없",
        ]

        insult_match = self._find_match(
            complaint,
            insult_patterns,
        )

        if insult_match:
            tags.append({
                "code": "DIRECT_INSULT_PERSONAL_ATTACK",
                "state": "PRESENT",
                "confidence": 0.95,
                "evidenceSpans": [
                    {
                        "text": insult_match,
                        "start": None,
                        "end": None,
                    }
                ],
                "reason": (
                    "교사 개인의 능력, 인격 또는 자격을 직접적으로 "
                    "비하하거나 깎아내리는 표현이 확인되었습니다."
                ),
            })

        # --------------------------------------------------
        # 3. THREAT_INTIMIDATION
        # --------------------------------------------------
        threat_patterns = [
            "다치게",
            "죽이",
            "해치",
            "보복",
            "가만두지",
            "불이익을 주",
            "찾아가",
            "두고 보",
            "가만히 있지 않",
        ]

        threat_match = self._find_match(
            complaint,
            threat_patterns,
        )

        if threat_match:
            tags.append({
                "code": "THREAT_INTIMIDATION",
                "state": "PRESENT",
                "confidence": 0.95,
                "evidenceSpans": [
                    {
                        "text": threat_match,
                        "start": None,
                        "end": None,
                    }
                ],
                "reason": (
                    "민원 내용에서 상대방에 대한 위해 또는 "
                    "보복을 암시하는 표현이 확인되었습니다."
                ),
            })

        # --------------------------------------------------
        # 4. LEGAL_ADMIN_ACTION_MENTION
        # --------------------------------------------------
        legal_action_patterns = [
            "교육청에 신고",
            "교육청 신고",
            "경찰에 신고",
            "경찰 신고",
            "민원을 넣",
            "민원 넣",
            "소송",
            "법적 조치",
            "법적 대응",
            "고소",
            "신고하",
        ]

        legal_match = self._find_match(
            complaint,
            legal_action_patterns,
        )

        if legal_match:
            tags.append({
                "code": "LEGAL_ADMIN_ACTION_MENTION",
                "state": "PRESENT",
                "confidence": 0.90,
                "evidenceSpans": [
                    {
                        "text": legal_match,
                        "start": None,
                        "end": None,
                    }
                ],
                "reason": (
                    "민원 내용에서 교육청 신고, 경찰 신고, "
                    "법적 조치 등 행정적 또는 법적 대응이 언급되었습니다."
                ),
            })

        # --------------------------------------------------
        # 5. PUBLIC_DISCLOSURE_THREAT
        # --------------------------------------------------
        disclosure_patterns = [
            "커뮤니티에 올리",
            "인터넷에 올리",
            "SNS에 올리",
            "공개하",
            "공개할",
            "퍼뜨리",
            "알리겠",
            "이름과 대화 내용을",
        ]

        disclosure_match = self._find_match(
            complaint,
            disclosure_patterns,
        )

        if disclosure_match:
            tags.append({
                "code": "PUBLIC_DISCLOSURE_THREAT",
                "state": "PRESENT",
                "confidence": 0.90,
                "evidenceSpans": [
                    {
                        "text": disclosure_match,
                        "start": None,
                        "end": None,
                    }
                ],
                "reason": (
                    "민원 내용에서 특정 개인이나 대화 내용을 "
                    "외부에 공개하거나 알리겠다는 표현이 확인되었습니다."
                ),
            })

        # --------------------------------------------------
        # 6. UNREASONABLE_DEMAND
        # --------------------------------------------------
        unreasonable_patterns = [
            "무조건 처리",
            "무조건 해",
            "반드시 처리",
            "반드시 해",
            "즉시 시행",
            "즉시 처리",
            "즉각 처리",
            "교체해",
            "교체하고",
            "당장 처리",
            "당장 해",
            "해줘야",
            "요구합니다",
        ]

        unreasonable_match = self._find_match(
            complaint,
            unreasonable_patterns,
        )

        if unreasonable_match:
            tags.append({
                "code": "UNREASONABLE_DEMAND",
                "state": "PRESENT",
                "confidence": 0.85,
                "evidenceSpans": [
                    {
                        "text": unreasonable_match,
                        "start": None,
                        "end": None,
                    }
                ],
                "reason": (
                    "민원 내용에서 일반적인 절차나 기준을 벗어나 "
                    "즉각적인 조치 등을 요구하는 표현이 확인되었습니다."
                ),
            })

        # --------------------------------------------------
        # 7. PERSONAL_INFO_RISK
        # --------------------------------------------------
        personal_info_patterns = [
            "이름",
            "전화번호",
            "연락처",
            "개인정보",
            "대화 내용",
            "학생 정보",
            "아이 정보",
        ]

        personal_info_match = self._find_match(
            complaint,
            personal_info_patterns,
        )

        if personal_info_match:
            tags.append({
                "code": "PERSONAL_INFO_RISK",
                "state": "PRESENT",
                "confidence": 0.85,
                "evidenceSpans": [
                    {
                        "text": personal_info_match,
                        "start": None,
                        "end": None,
                    }
                ],
                "reason": (
                    "민원 내용에서 개인 식별 정보 또는 "
                    "개인적인 대화 및 정보의 공개 가능성이 언급되었습니다."
                ),
            })

        # --------------------------------------------------
        # 8. 결과
        # --------------------------------------------------
        return json.dumps(
            {
                "tags": tags,
                "metadata": {
                    "modelName": "mock-python-llm",
                    "temperature": 0.0,
                },
            },
            ensure_ascii=False,
        )

    def _extract_complaint(
        self,
        prompt: str,
    ) -> str:
        marker = "[민원 내용]"

        if marker not in prompt:
            return prompt

        complaint = prompt.split(
            marker,
            1,
        )[1]

        if "[관련 문서 검색 결과]" in complaint:
            complaint = complaint.split(
                "[관련 문서 검색 결과]",
                1,
            )[0]

        return complaint.strip()

    def _find_match(
        self,
        complaint: str,
        patterns: list[str],
    ) -> str | None:

        for pattern in patterns:
            match = re.search(
                re.escape(pattern),
                complaint,
                re.IGNORECASE,
            )

            if match:
                start = max(
                    0,
                    match.start() - 20,
                )

                end = min(
                    len(complaint),
                    match.end() + 20,
                )

                return complaint[
                    start:end
                ].strip()

        return None