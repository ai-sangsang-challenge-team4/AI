"""Optional semantic cross-encoder; never loaded in default vector mode."""
from __future__ import annotations

class CrossEncoderReranker:
    def __init__(self, model_name: str):
        if not model_name.strip():
            raise ValueError("RAG_RERANKER_MODEL is required for hybrid_rerank")
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError("Install optional sentence-transformers before enabling reranking") from exc
        self.model = CrossEncoder(model_name)

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        if not candidates:
            return []
        scores = self.model.predict([(query, row["content"]) for row in candidates])
        ranked = [dict(row, rerankScore=float(score)) for row, score in zip(candidates, scores)]
        return sorted(ranked, key=lambda row: -row["rerankScore"])
