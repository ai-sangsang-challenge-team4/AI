import json

from app.llm.client import LlmClient


class MockLlmClient(LlmClient):

    def generate(self, prompt: str) -> str:
        return json.dumps({
            "tags": [
                {
                    "code": "THREAT",
                    "state": "PRESENT",
                    "confidence": 0.9,
                    "evidenceSpans": [
                        {
                            "text": "불이익을 주겠습니다.",
                            "start": None,
                            "end": None
                        }
                    ],
                    "reason": "불이익을 암시하는 위협성 문맥"
                },
                {
                    "code": "UNFAIR_REQUEST",
                    "state": "PRESENT",
                    "confidence": 0.8,
                    "evidenceSpans": [
                        {
                            "text": "일방적인 조치를 요구합니다.",
                            "start": None,
                            "end": None
                        }
                    ],
                    "reason": "일방적인 조치를 요구하는 문맥"
                }
            ],
            "metadata": {
                "modelName": "mock-python-llm",
                "temperature": 0.0
            }
        }, ensure_ascii=False)