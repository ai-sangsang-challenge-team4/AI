from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


# ============================================================
# 기본 설정
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
RESULT_DIR = BASE_DIR / "results"

INPUT_CSV = RESULT_DIR / "benchmark_results.csv"


# ============================================================
# 데이터 로드
# ============================================================

df = pd.read_csv(INPUT_CSV)

MODEL_ORDER = [
    "Claude",
    "GPT",
    "Gemini",
]


# ============================================================
# 모델별 Summary 생성
# ============================================================

summary = (
    df.groupby("model", observed=True)
    .agg(
        json_success_rate=("json_success", "mean"),
        tag_precision=("tag_precision", "mean"),
        tag_recall=("tag_recall", "mean"),
        tag_f1=("tag_f1", "mean"),
        intent_accuracy=("intent_correct", "mean"),
        avg_latency_ms=("latency_ms", "mean"),
        avg_input_tokens=("input_tokens", "mean"),
        avg_output_tokens=("output_tokens", "mean"),
    )
    .reindex(MODEL_ORDER)
    .reset_index()
)


print()
print("=" * 60)
print("MODEL SUMMARY")
print("=" * 60)
print(summary.to_string(index=False))
print()


# ============================================================
# 공통 Bar Chart
# ============================================================

def save_bar_chart(
    column: str,
    title: str,
    ylabel: str,
    filename: str,
    percent: bool = False,
):
    values = summary[column].astype(float).tolist()

    if percent:
        values = [value * 100 for value in values]

    plt.figure(figsize=(8, 5))

    bars = plt.bar(
        MODEL_ORDER,
        values,
    )

    plt.title(title)
    plt.xlabel("Model")
    plt.ylabel(ylabel)

    if percent:
        plt.ylim(0, 105)

    for bar, value in zip(bars, values):
        label = (
            f"{value:.1f}%"
            if percent
            else f"{value:.3f}"
        )

        plt.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            label,
            ha="center",
            va="bottom",
        )

    plt.tight_layout()

    plt.savefig(
        RESULT_DIR / filename,
        dpi=200,
        bbox_inches="tight",
    )

    plt.close()


# ============================================================
# 1. Risk Tag F1
# ============================================================

save_bar_chart(
    column="tag_f1",
    title="Risk Tag F1 Score",
    ylabel="F1 Score",
    filename="risk_tag_f1.png",
)


# ============================================================
# 2. Precision / Recall
# ============================================================

x = list(range(len(MODEL_ORDER)))
width = 0.35

precision = summary["tag_precision"].tolist()
recall = summary["tag_recall"].tolist()

plt.figure(figsize=(9, 5))

precision_positions = [
    value - width / 2
    for value in x
]

recall_positions = [
    value + width / 2
    for value in x
]

bars_precision = plt.bar(
    precision_positions,
    precision,
    width,
    label="Precision",
)

bars_recall = plt.bar(
    recall_positions,
    recall,
    width,
    label="Recall",
)

for bar, value in zip(
    bars_precision,
    precision,
):
    plt.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height(),
        f"{value:.3f}",
        ha="center",
        va="bottom",
        fontsize=9,
    )

for bar, value in zip(
    bars_recall,
    recall,
):
    plt.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height(),
        f"{value:.3f}",
        ha="center",
        va="bottom",
        fontsize=9,
    )

plt.xticks(
    x,
    MODEL_ORDER,
)

plt.ylim(0, 1.05)
plt.xlabel("Model")
plt.ylabel("Score")
plt.title("Risk Tag Precision vs Recall")
plt.legend()

plt.tight_layout()

plt.savefig(
    RESULT_DIR / "risk_tag_precision_recall.png",
    dpi=200,
    bbox_inches="tight",
)

plt.close()


# ============================================================
# 3. Communication Intent Accuracy
# ============================================================

save_bar_chart(
    column="intent_accuracy",
    title="Communication Intent Accuracy",
    ylabel="Accuracy",
    filename="intent_accuracy.png",
    percent=True,
)


# ============================================================
# 4. JSON Success Rate
# ============================================================

save_bar_chart(
    column="json_success_rate",
    title="JSON Success Rate",
    ylabel="Success Rate",
    filename="json_success_rate.png",
    percent=True,
)


# ============================================================
# 5. Average Latency
# ============================================================

save_bar_chart(
    column="avg_latency_ms",
    title="Average API Latency",
    ylabel="Latency (ms)",
    filename="average_latency.png",
)


# ============================================================
# 6. 종합 성능 비교
# ============================================================

performance_metrics = {
    "Risk Tag F1": "tag_f1",
    "Intent Accuracy": "intent_accuracy",
    "JSON Success": "json_success_rate",
}

x = list(range(len(MODEL_ORDER)))
width = 0.25

plt.figure(figsize=(10, 6))

for index, (
    label,
    column,
) in enumerate(
    performance_metrics.items()
):

    values = summary[column].astype(float).tolist()

    positions = [
        value
        + (index - 1) * width
        for value in x
    ]

    bars = plt.bar(
        positions,
        values,
        width,
        label=label,
    )

    for bar, value in zip(
        bars,
        values,
    ):
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height(),
            f"{value:.2f}",
            ha="center",
            va="bottom",
            fontsize=8,
        )

plt.xticks(
    x,
    MODEL_ORDER,
)

plt.ylim(0, 1.08)
plt.xlabel("Model")
plt.ylabel("Score")
plt.title("LLM Benchmark Performance Comparison")
plt.legend()

plt.tight_layout()

plt.savefig(
    RESULT_DIR / "benchmark_performance_comparison.png",
    dpi=200,
    bbox_inches="tight",
)

plt.close()


# ============================================================
# 완료
# ============================================================

print("=" * 60)
print("BENCHMARK VISUALIZATION COMPLETE")
print("=" * 60)

for file in sorted(
    RESULT_DIR.glob("*.png")
):
    print(file.name)
