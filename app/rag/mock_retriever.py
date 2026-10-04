class MockRagRetriever:
    
    def search(self, query: str, k: int = 3) -> list[dict]:
        return [
            {
                "content": "학교 민원 처리 관련 규정의 Mock 검색 결과입니다.",
                "source": "학교민원처리매뉴얼.pdf",
                "page": 12,
            },
            {
                "content": "교원 보호 및 민원 대응 절차에 관한 Mock 검색 결과입니다.",
                "source": "교원민원대응매뉴얼.pdf",
                "page": 8,
            },
            {
                "content": "반복적인 민원 대응과 관련된 Mock 검색 결과입니다.",
                "source": "학부모민원연구자료.pdf",
                "page": 25,
            },
        ][:k]