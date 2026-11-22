"""Offline deterministic tests: no Cloudflare/Claude/model downloads."""
import pytest
from app.rag.hybrid import BM25Index, IndexedChunk, reciprocal_rank_fusion
from app.rag.hybrid_retriever import HybridRetriever
from scripts.evaluate_rag_relevance import metric_at_k, evaluate, load_judgments

def test_bm25_finds_korean_law_article():
    docs = [IndexedChunk("학교폭력예방법 제13조의2 자체해결 요건", "rules.pdf", 2),
            IndexedChunk("학교 행사 일정과 급식 안내", "notice.pdf", 4)]
    matches = BM25Index(docs).search("학교폭력예방법 제13조의2")
    assert matches[0][0].source == "rules.pdf"
    assert matches[0][1] > 0

def test_rank_fusion_deduplicates_and_rewards_both_sources():
    ranked = reciprocal_rank_fusion([["a", "b", "a"], ["a", "c"]])
    assert [item[0] for item in ranked] == ["a", "b", "c"]
    assert ranked[0][1] > ranked[1][1]

def test_ground_truth_metrics_ignore_similarity_scores():
    scores = metric_at_k([("noise", 1), ("rules.pdf", 2)], {("rules.pdf", 2)}, 3)
    assert scores["recall"] == 1
    assert scores["mrr"] == .5
    assert 0 < scores["ndcg"] < 1

def test_relevance_evaluate_with_fake_retriever():
    class Fake:
        def search(self, query, k):
            return [{"source": "rules.pdf", "page": 2}]
    cases = [{"query_id": "Q1", "query": "폭력", "relevant": [{"source": "rules.pdf", "page": 2}]}]
    rows, summary = evaluate(cases, Fake(), 3)
    assert summary["recall"] == summary["mrr"] == summary["ndcg"] == 1
    assert rows[0]["returned"] == 1

def test_hybrid_search_fallback_and_document_cap(monkeypatch):
    import sys
    import types
    fake_module = types.ModuleType("app.rag.retriever")
    fake_module.is_low_quality_chunk = lambda content: not content.strip()
    monkeypatch.setitem(sys.modules, "app.rag.retriever", fake_module)

    class Doc:
        def __init__(self, text, source, page):
            self.page_content, self.metadata = text, {"source": source, "page": page}

    class Collection:
        def count(self):
            return 3
        def get(self, include):
            return {"documents": ["학교폭력예방법 처리 절차", "학생 간 갈등 조정", "일반적인 행사 문의"],
                    "metadatas": [{"source": "manual.pdf", "page": 1},
                                  {"source": "manual.pdf", "page": 2},
                                  {"source": "notice.pdf", "page": 1}]}
    class Store:
        _collection = Collection()
        def similarity_search_with_relevance_scores(self, query, k):
            return [(Doc("일반적인 행사 문의", "notice.pdf", 1), .9)]

    class BrokenReranker:
        def rerank(self, query, candidates):
            raise RuntimeError("temporary inference failure")

    retriever = HybridRetriever(Store(), max_per_source=1, reranker=BrokenReranker())
    results = retriever.search("학교폭력예방법 처리 절차", k=3)
    assert any(result["source"] == "manual.pdf" for result in results)
    assert len([result for result in results if result["source"] == "manual.pdf"]) == 1
    assert all(result["score"] > 0 for result in results)

def test_empty_relevance_labels_are_invalid():
    with pytest.raises(ValueError):
        metric_at_k([], set(), 3)
