import json
import csv
import statistics
from pathlib import Path

from app.rag.retriever import RagRetriever


BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

DATA_PATH = PROJECT_DIR / "data" / "context_examples.json"
RESULT_DIR = BASE_DIR / "rag_results"

RESULT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

RESULT_CSV = RESULT_DIR / "rag_retrieval_results.csv"
SUMMARY_CSV = RESULT_DIR / "rag_retrieval_summary.csv"


def load_dataset():
    with open(
        DATA_PATH,
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)


def main():

    cases = load_dataset()

    retriever = RagRetriever(
        max_results=5,
        max_per_source=2,
    )

    rows = []

    print("=" * 100)
    print("RAG RETRIEVAL BENCHMARK")
    print("=" * 100)
    print(f"총 데이터: {len(cases)}건")

    for index, case in enumerate(cases, 1):

        case_id = case["caseId"]
        complaint = case["message"]

        print()
        print(
            f"[{index}/{len(cases)}] {case_id}"
        )
        print(f"  민원: {complaint}")

        results = retriever.search(
            complaint,
            k=5,
        )

        sources = [
            result.get("source")
            for result in results
        ]

        unique_sources = len(
            set(sources)
        )

        scores = [
            result.get("score")
            for result in results
            if result.get("score") is not None
        ]

        for rank, result in enumerate(
            results,
            1,
        ):

            row = {
                "case_id": case_id,
                "rank": rank,
                "complaint": complaint,
                "score": result.get("score"),
                "source": result.get("source"),
                "page": result.get("page"),
                "unique_sources_top5": unique_sources,
            }

            rows.append(row)

            print(
                f"  {rank}. "
                f"score={result.get('score', 0):.4f} | "
                f"source={result.get('source')} | "
                f"page={result.get('page')}"
            )

    # --------------------------------------------------------
    # 상세 결과 저장
    # --------------------------------------------------------

    with open(
        RESULT_CSV,
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=[
                "case_id",
                "rank",
                "complaint",
                "score",
                "source",
                "page",
                "unique_sources_top5",
            ],
        )

        writer.writeheader()
        writer.writerows(rows)

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    case_summaries = []

    for case_id in sorted(
        set(row["case_id"] for row in rows)
    ):

        case_rows = [
            row
            for row in rows
            if row["case_id"] == case_id
        ]

        scores = [
            row["score"]
            for row in case_rows
            if row["score"] is not None
        ]

        sources = [
            row["source"]
            for row in case_rows
        ]

        unique_sources = len(
            set(sources)
        )

        case_summaries.append(
            {
                "case_id": case_id,
                "top1_score": scores[0]
                if scores
                else None,
                "top5_avg_score": (
                    statistics.mean(scores)
                    if scores
                    else None
                ),
                "top5_min_score": (
                    min(scores)
                    if scores
                    else None
                ),
                "unique_sources_top5": unique_sources,
                "source_diversity_ratio": (
                    unique_sources / len(sources)
                    if sources
                    else 0
                ),
            }
        )

    with open(
        SUMMARY_CSV,
        "w",
        newline="",
        encoding="utf-8-sig",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=[
                "case_id",
                "top1_score",
                "top5_avg_score",
                "top5_min_score",
                "unique_sources_top5",
                "source_diversity_ratio",
            ],
        )

        writer.writeheader()
        writer.writerows(case_summaries)

    # --------------------------------------------------------
    # 전체 요약
    # --------------------------------------------------------

    top1_scores = [
        row["top1_score"]
        for row in case_summaries
        if row["top1_score"] is not None
    ]

    avg_scores = [
        row["top5_avg_score"]
        for row in case_summaries
        if row["top5_avg_score"] is not None
    ]

    diversity = [
        row["source_diversity_ratio"]
        for row in case_summaries
    ]

    print()
    print("=" * 100)
    print("RAG RETRIEVAL BENCHMARK COMPLETE")
    print("=" * 100)

    print(
        f"평균 Top-1 score: "
        f"{statistics.mean(top1_scores):.4f}"
    )

    print(
        f"평균 Top-5 score: "
        f"{statistics.mean(avg_scores):.4f}"
    )

    print(
        f"평균 source diversity: "
        f"{statistics.mean(diversity):.4f}"
    )

    print()
    print(f"상세 결과: {RESULT_CSV}")
    print(f"요약 결과: {SUMMARY_CSV}")


if __name__ == "__main__":
    main()
