import json
import re

from app.llm.client import LlmClient


class MockLlmClient(LlmClient):

    def generate(self, prompt: str) -> str:
        complaint = self._extract_complaint(prompt)

        tags = []

        threat_patterns = [
            "다치게",
            "죽이",
            "해치",
            "보복",
            "가만두지",
            "불이익을 주",
            "찾아가",
            "두고 보",
        ]

        unfair_patterns = [
            "특혜",
            "예외로",
            "규정 무시",
            "일방적으로",
            "무조건 처리",
            "요구합니다",
            "해줘야",
        ]

        threat_match = self._find_match(
            complaint,
            threat_patterns
        )

        if threat_match:
            tags.append({
                "code": "THREAT",
                "state": "PRESENT",
                "confidence": 0.95,
                "evidenceSpans": [
                    {
                        "text": threat_match,
                        "start": None,
                        "end": None
                    }
                ],
                "reason": "민원 내용에서 상대방에 대한 위해 또는 보복을 암시하는 표현이 확인되었습니다."
            })

        unfair_match = self._find_match(
            complaint,
            unfair_patterns
        )

        if unfair_match:
            tags.append({
                "code": "UNFAIR_REQUEST",
                "state": "PRESENT",
                "confidence": 0.85,
                "evidenceSpans": [
                    {
                        "text": unfair_match,
                        "start": None,
                        "end": None
                    }
                ],
                "reason": "민원 내용에서 규정이나 일반적인 절차를 벗어난 요구를 암시하는 표현이 확인되었습니다."
            })

        return json.dumps({
            "tags": tags,
            "metadata": {
                "modelName": "mock-python-llm",
                "temperature": 0.0
            }
        }, ensure_ascii=False)

    def _extract_complaint(self, prompt: str) -> str:
        marker = "[민원 내용]"

        if marker not in prompt:
            return prompt

        complaint = prompt.split(marker, 1)[1]

        if "[관련 문서 검색 결과]" in complaint:
            complaint = complaint.split(
                "[관련 문서 검색 결과]",
                1
            )[0]

        return complaint.strip()

    def _find_match(
        self,
        complaint: str,
        patterns: list[str]
    ) -> str | None:

        for pattern in patterns:
            match = re.search(
                re.escape(pattern),
                complaint,
                re.IGNORECASE
            )

            if match:
                start = max(0, match.start() - 20)
                end = min(len(complaint), match.end() + 20)

                return complaint[start:end].strip()

        return None