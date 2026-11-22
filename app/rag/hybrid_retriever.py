"""Combine BGE-M3 Chroma similarity with corpus BM25 via RRF."""
from __future__ import annotations
from app.rag.hybrid import BM25Index, IndexedChunk, document_key, reciprocal_rank_fusion

class HybridRetriever:
    def __init__(self, vectorstore, *, max_per_source: int = 2,
                 score_threshold: float = .35, search_k: int = 20,
                 reranker=None, max_index_chunks: int = 10000):
        self.vectorstore = vectorstore
        self.max_per_source = max_per_source
        self.score_threshold = score_threshold
        self.search_k = search_k
        self.reranker = reranker
        self.max_index_chunks = max_index_chunks
        self._index = None

    def _sparse_index(self):
        if self._index is None:
            collection = self.vectorstore._collection
            if collection.count() > self.max_index_chunks:
                raise RuntimeError("In-memory BM25 index exceeds limit")
            stored = collection.get(include=["documents", "metadatas"])
            content = stored.get("documents") or []
            metadata = stored.get("metadatas") or []
            self._index = BM25Index([
                IndexedChunk(text, meta.get("source"), meta.get("page"))
                for text, meta in zip(content, metadata) if text and meta is not None
            ])
        return self._index

    def search(self, query: str, k: int = 3) -> list[dict]:
        from app.rag.retriever import is_low_quality_chunk
        if not query.strip() or k <= 0:
            return []
        candidate_k = max(self.search_k, k * 4)
        dense = self.vectorstore.similarity_search_with_relevance_scores(query, k=candidate_k)
        sparse = self._sparse_index().search(query, limit=candidate_k)
        candidates = {}
        dense_order, sparse_order = [], []
        for doc, score in dense:
            content = doc.page_content.strip()
            if float(score) < self.score_threshold or is_low_quality_chunk(content):
                continue
            source, page = doc.metadata.get("source"), doc.metadata.get("page")
            key = document_key(content, source, page)
            dense_order.append(key)
            candidates[key] = {"content": content, "source": source, "page": page}
        for doc, _score in sparse:
            if is_low_quality_chunk(doc.content):
                continue
            sparse_order.append(doc.key)
            candidates.setdefault(doc.key, {"content": doc.content, "source": doc.source, "page": doc.page})
        ranked = [dict(candidates[key], fusionScore=score) for key, score
                  in reciprocal_rank_fusion([dense_order, sparse_order]) if key in candidates]
        if self.reranker is not None and ranked:
            try:
                ranked = self.reranker.rerank(query, ranked)
            except Exception:
                # Optional inference errors must not block evidence retrieval.
                pass
        results, source_counts, seen = [], {}, set()
        for row in ranked:
            if row["content"] in seen:
                continue
            seen.add(row["content"])
            source = row["source"] or "알 수 없음"
            if source_counts.get(source, 0) >= self.max_per_source:
                continue
            # Hybrid score is RRF, not dense cosine relevance.
            results.append({"content": row["content"], "source": row["source"],
                            "page": row["page"], "score": row["fusionScore"]})
            source_counts[source] = source_counts.get(source, 0) + 1
            if len(results) >= k:
                break
        return results
