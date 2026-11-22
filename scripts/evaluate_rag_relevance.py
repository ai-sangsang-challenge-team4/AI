#!/usr/bin/env python3
"""Compare retrieval against human-judged PDF pages; not similarity-score averages."""
from __future__ import annotations
import argparse
import csv
import json
import math
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def metric_at_k(found: list[tuple[str, int | None]], relevant: set[tuple[str, int | None]], k: int) -> dict:
    if k <= 0 or not relevant:
        raise ValueError("k must be positive and relevant judgments cannot be empty")
    seen = set()
    hits = []
    for key in found[:k]:
        if key not in seen:
            seen.add(key)
            hits.append(int(key in relevant))
    recall = sum(hits) / len(relevant)
    reciprocal_rank = next((1 / rank for rank, hit in enumerate(hits, 1) if hit), 0.0)
    dcg = sum(hit / math.log2(rank + 1) for rank, hit in enumerate(hits, 1))
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(relevant), k) + 1))
    return {"recall": recall, "mrr": reciprocal_rank, "ndcg": dcg / ideal}

def load_judgments(path: Path) -> list[dict]:
    cases, seen = [], set()
    for index, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        case = json.loads(line)
        case_id, relevant = case.get("query_id"), case.get("relevant")
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError(f"invalid or duplicate query_id at line {index}")
        if not isinstance(case.get("query"), str) or not case["query"].strip():
            raise ValueError(f"missing query at line {index}")
        if not isinstance(relevant, list) or not relevant:
            raise ValueError(f"human-judged relevant entries required at line {index}")
        for target in relevant:
            if (not isinstance(target, dict) or not isinstance(target.get("source"), str)
                or not target["source"] or type(target.get("page")) is not int or target["page"] < 0):
                raise ValueError(f"invalid 0-based source/page at line {index}")
        seen.add(case_id)
        cases.append(case)
    if not cases:
        raise ValueError("judgment file is empty")
    return cases

def evaluate(cases: list[dict], retriever, k: int = 3) -> tuple[list[dict], dict]:
    rows = []
    for case in cases:
        documents = retriever.search(case["query"], k=k)
        found = [(doc.get("source"), doc.get("page")) for doc in documents]
        relevant = {(target["source"], target["page"]) for target in case["relevant"]}
        rows.append({"query_id": case["query_id"], **metric_at_k(found, relevant, k),
                     "returned": len(documents)})
    return rows, {"queries": len(rows), "k": k, **{
        name: round(sum(row[name] for row in rows) / len(rows), 4)
        for name in ("recall", "mrr", "ndcg")}}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--judgments", required=True, type=Path)
    parser.add_argument("--out", default="reports/rag_relevance", type=Path)
    parser.add_argument("--k", type=int, default=3)
    parser.add_argument("--mode", choices=("vector", "hybrid", "hybrid_rerank"), default="vector")
    parser.add_argument("--reranker-model")
    args = parser.parse_args()
    if args.k <= 0:
        parser.error("k must be positive")
    if args.mode == "hybrid_rerank" and not args.reranker_model:
        parser.error("--reranker-model is required")
    cases = load_judgments(args.judgments)
    from app.rag.retriever import RagRetriever
    retriever = RagRetriever(mode=args.mode, reranker_model=args.reranker_model, max_results=args.k)
    rows, summary = evaluate(cases, retriever, k=args.k)
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / f"{args.mode}_cases.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["query_id", "recall", "mrr", "ndcg", "returned"])
        writer.writeheader()
        writer.writerows(rows)
    summary["mode"] = args.mode
    (args.out / f"{args.mode}_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
