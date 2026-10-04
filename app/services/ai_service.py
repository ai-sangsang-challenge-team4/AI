from app.llm.mock_client import MockLlmClient
from app.rag.mock_retriever import MockRagRetriever
from app.rag.prompt import build_prompt


class AiService:

    def __init__(self):
        self.retriever = MockRagRetriever()
        self.llm_client = MockLlmClient()

    def analyze(self, complaint: str) -> str:
        documents = self.retriever.search(
            complaint,
            k=3,
        )

        prompt = build_prompt(
            complaint=complaint,
            documents=documents,
        )

        return self.llm_client.generate(prompt)