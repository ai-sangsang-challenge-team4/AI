from app.llm.client import LlmClient


class MockLlmClient(LlmClient):

    def generate(self, prompt: str) -> str:
        return """
{
  "risk_tags": [
    {
      "code": "THREAT",
      "evidence": "위협성 표현이 포함된 것으로 판단되는 내용"
    }
  ],
  "summary": "학부모 민원 내용에 대한 Mock 요약입니다.",
  "draft": "관련 절차에 따라 민원을 확인하고 필요한 조치를 안내드리겠습니다."
}
""".strip()