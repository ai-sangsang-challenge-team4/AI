
import math
import os

import requests
from langchain_core.embeddings import Embeddings


class CloudflareBgeM3Embeddings(Embeddings):
    MODEL = "@cf/baai/bge-m3"

    def __init__(self):
        account_id = os.environ["CLOUDFLARE_ACCOUNT_ID"]
        self.api_token = os.environ["CLOUDFLARE_API_TOKEN"]

        self.url = (
            "https://api.cloudflare.com/client/v4/accounts/"
            f"{account_id}/ai/run/{self.MODEL}"
        )

    @staticmethod
    def _normalize(vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            raise ValueError("Cloudflare returned a zero embedding vector")
        return [value / norm for value in vector]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        response = requests.post(
            self.url,
            headers={
                "Authorization": f"Bearer {self.api_token}",
                "Content-Type": "application/json",
            },
            json={"text": texts},
            timeout=60,
        )
        response.raise_for_status()

        payload = response.json()
        if not payload.get("success", False):
            raise RuntimeError("Cloudflare embedding request failed")

        result = payload.get("result")
        if not isinstance(result, dict):
            raise ValueError("Invalid Cloudflare embedding response")

        vectors = result.get("data")
        if not isinstance(vectors, list) or len(vectors) != len(texts):
            raise ValueError("Unexpected Cloudflare embedding vector count")

        normalized = []
        for vector in vectors:
            if not isinstance(vector, list) or not vector:
                raise ValueError("Invalid embedding vector")
            normalized.append(
                self._normalize([float(value) for value in vector])
            )

        return normalized

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]
