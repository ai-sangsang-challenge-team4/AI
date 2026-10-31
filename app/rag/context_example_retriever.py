import json
from pathlib import Path


class ContextExampleRetriever:

    def __init__(self, top_k: int = 3):
        self.top_k = top_k

        data_path = (
            Path(__file__).resolve().parents[2]
            / "data"
            / "context_examples.json"
        )

        with open(data_path, "r", encoding="utf-8") as f:
            self.examples = json.load(f)

    def search(self, complaint: str) -> list[dict]:
        complaint_tokens = self._tokenize(complaint)

        scored_examples = []

        for example in self.examples:
            message = example.get("message", "")
            example_tokens = self._tokenize(message)

            score = self._similarity(
                complaint_tokens,
                example_tokens,
            )

            scored_examples.append(
                (score, example)
            )

        scored_examples.sort(
            key=lambda x: x[0],
            reverse=True,
        )

        return [
            example
            for score, example in scored_examples[: self.top_k]
        ]

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        normalized = text.lower()

        tokens = set()

        # 공백 기준
        tokens.update(normalized.split())

        # 2글자 단위 토큰
        for i in range(len(normalized) - 1):
            tokens.add(normalized[i:i + 2])

        return tokens

    @staticmethod
    def _similarity(
        tokens_a: set[str],
        tokens_b: set[str],
    ) -> float:
        if not tokens_a or not tokens_b:
            return 0.0

        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b

        return len(intersection) / len(union)