class AiService:
    
    def __init__(self):
        self.retriever = MockRagRetriever()
        self.llm_client = MockLlmClient()

    def analyze(self, complaint: str) -> AiAnalysisResult:
        documents = self.retriever.search(
            complaint,
            k=3,
        )

        prompt = build_prompt(
            complaint=complaint,
            documents=documents,
        )

        response = self.llm_client.generate(prompt)

        data = json.loads(response)

        return AiAnalysisResult.model_validate(data)