import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path


# ============================================================
# 기본 설정
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

RESULT_DIR = BASE_DIR / "summary_results"

INPUT_CSV = RESULT_DIR / "summary_benchmark_summary.csv"

OUTPUT_PERFORMANCE = (
    RESULT_DIR / "summary_performance_comparison.png"
)

OUTPUT_LATENCY = (
    RESULT_DIR / "summary_latency_comparison.png"
)


# ============================================================
# 데이터 로드
# ============================================================

df = pd.read_csv(INPUT_CSV)

# 모델 표시 순서 고정
model_order = ["Claude", "GPT", "Gemini"]

df["model"] = pd.Categorical(
    df["model"],
    categories=model_order,
    ordered=True,
)

df = df.sort_values("model")


# ============================================================
# 1. 성능 비교
# ============================================================

metrics = {
    "rouge1": "ROUGE-1",
    "rougeL": "ROUGE-L",
    "bertscore_f1": "BERTScore F1",
}

fig, ax = plt.subplots(
    figsize=(10, 6)
)

x = range(len(df))
width = 0.24

for index, (column, label) in enumerate(
    metrics.items()
):

    positions = [
        value + (index - 1) * width
        for value in x
    ]

    bars = ax.bar(
        positions,
        df[column],
        width=width,
        label=label,
    )

    # 값 표시
    for bar in bars:
        height = bar.get_height()

        ax.text(
            bar.get_x() + bar.get_width() / 2,
            height + 0.01,
            f"{height:.3f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )


ax.set_title(
    "LLM Benchmark - Summary Performance",
    fontsize=14,
    fontweight="bold",
)

ax.set_ylabel("Score")

ax.set_xticks(list(x))
ax.set_xticklabels(
    df["model"]
)

ax.set_ylim(0, 1)

ax.legend()

ax.grid(
    axis="y",
    alpha=0.2,
)

plt.tight_layout()

plt.savefig(
    OUTPUT_PERFORMANCE,
    dpi=200,
    bbox_inches="tight",
)

plt.close()


# ============================================================
# 2. 평균 응답시간 비교
# ============================================================

fig, ax = plt.subplots(
    figsize=(9, 6)
)

bars = ax.bar(
    df["model"],
    df["avg_latency_ms"] / 1000,
)

for bar in bars:

    height = bar.get_height()

    ax.text(
        bar.get_x() + bar.get_width() / 2,
        height + 0.05,
        f"{height:.2f}s",
        ha="center",
        va="bottom",
        fontsize=10,
    )


ax.set_title(
    "LLM Benchmark - Average Latency",
    fontsize=14,
    fontweight="bold",
)

ax.set_ylabel(
    "Latency (seconds)"
)

ax.grid(
    axis="y",
    alpha=0.2,
)

plt.tight_layout()

plt.savefig(
    OUTPUT_LATENCY,
    dpi=200,
    bbox_inches="tight",
)

plt.close()


# ============================================================
# 완료
# ============================================================

print()
print("=" * 60)
print("SUMMARY BENCHMARK VISUALIZATION COMPLETE")
print("=" * 60)

print(
    f"성능 비교: {OUTPUT_PERFORMANCE}"
)

print(
    f"응답시간 비교: {OUTPUT_LATENCY}"
)