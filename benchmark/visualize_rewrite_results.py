from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


# ============================================================
# 기본 설정
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

INPUT_CSV = (
    BASE_DIR
    / "results"
    / "rewrite_human_eval.csv"
)

OUTPUT_DIR = (
    BASE_DIR
    / "rewrite_results"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# 평가 항목
# ============================================================

METRICS = [
    "intent_preservation",
    "information_preservation",
    "emotion_moderation",
    "expression_appropriateness",
    "over_smoothing_prevention",
]

METRIC_LABELS = {
    "intent_preservation":
        "Intent Preservation",

    "information_preservation":
        "Information Preservation",

    "emotion_moderation":
        "Emotion Moderation",

    "expression_appropriateness":
        "Expression Appropriateness",

    "over_smoothing_prevention":
        "Over-Smoothing Prevention",
}


# ============================================================
# 데이터 로드
# ============================================================

df = pd.read_csv(
    INPUT_CSV,
    encoding="utf-8-sig",
)


# ============================================================
# 숫자형 변환
# ============================================================

for metric in METRICS:
    df[metric] = pd.to_numeric(
        df[metric],
        errors="coerce",
    )


# ============================================================
# 총점 계산
# ============================================================

df["total_score"] = (
    df[METRICS]
    .sum(axis=1)
)


# ============================================================
# 모델별 평균
# ============================================================

summary = (
    df.groupby("model")
    .agg(
        intent_preservation=(
            "intent_preservation",
            "mean",
        ),
        information_preservation=(
            "information_preservation",
            "mean",
        ),
        emotion_moderation=(
            "emotion_moderation",
            "mean",
        ),
        expression_appropriateness=(
            "expression_appropriateness",
            "mean",
        ),
        over_smoothing_prevention=(
            "over_smoothing_prevention",
            "mean",
        ),
        total_score=(
            "total_score",
            "mean",
        ),
    )
    .reset_index()
)


# ============================================================
# 순위
# ============================================================

summary = summary.sort_values(
    "total_score",
    ascending=False,
)

summary["rank"] = (
    summary["total_score"]
    .rank(
        method="min",
        ascending=False,
    )
    .astype(int)
)


# ============================================================
# 결과 출력
# ============================================================

print()
print("=" * 70)
print("REWRITE BENCHMARK RESULT")
print("=" * 70)

print()

display_columns = [
    "model",
    "intent_preservation",
    "information_preservation",
    "emotion_moderation",
    "expression_appropriateness",
    "over_smoothing_prevention",
    "total_score",
    "rank",
]

print(
    summary[
        display_columns
    ].to_string(
        index=False,
        formatters={
            metric: "{:.3f}".format
            for metric in METRICS
        }
        | {
            "total_score":
                "{:.3f}".format
        },
    )
)

print()


# ============================================================
# 모델별 해석
# ============================================================

best_score = summary[
    "total_score"
].max()

best_models = summary[
    summary["total_score"] == best_score
]["model"].tolist()

print("=" * 70)
print("MODEL SELECTION")
print("=" * 70)

if len(best_models) == 1:

    print(
        f"우선 모델: {best_models[0]}"
    )

else:

    print(
        "공동 최고 모델: "
        + ", ".join(best_models)
    )

print(
    f"최고 평균 점수: "
    f"{best_score:.3f} / 25"
)

print()


# ============================================================
# CSV 저장
# ============================================================

summary_path = (
    OUTPUT_DIR
    / "rewrite_benchmark_summary.csv"
)

summary.to_csv(
    summary_path,
    index=False,
    encoding="utf-8-sig",
)

print(
    f"요약 저장: {summary_path}"
)


# ============================================================
# 1. 종합 점수 시각화
# ============================================================

plt.figure(
    figsize=(8, 5)
)

bars = plt.bar(
    summary["model"],
    summary["total_score"],
)

plt.title(
    "Overall Human Evaluation Score"
)

plt.ylabel(
    "Average Score / 25"
)

plt.ylim(
    0,
    25,
)

for bar, value in zip(
    bars,
    summary["total_score"],
):

    plt.text(
        bar.get_x()
        + bar.get_width() / 2,
        value + 0.2,
        f"{value:.2f}",
        ha="center",
        va="bottom",
    )

plt.tight_layout()

overall_path = (
    OUTPUT_DIR
    / "overall_score.png"
)

plt.savefig(
    overall_path,
    dpi=180,
)

plt.close()


# ============================================================
# 2. 세부 평가 항목 비교
# ============================================================

plt.figure(
    figsize=(11, 6)
)

models = summary["model"].tolist()

x = list(
    range(len(models))
)

width = 0.15

for index, metric in enumerate(
    METRICS
):

    positions = [
        value
        + (
            index
            - (
                len(METRICS) - 1
            ) / 2
        )
        * width
        for value in x
    ]

    plt.bar(
        positions,
        summary[metric],
        width=width,
        label=METRIC_LABELS[metric],
    )

plt.xticks(
    x,
    models,
)

plt.ylabel(
    "Average Score / 5"
)

plt.title(
    "Human Evaluation by Criterion"
)

plt.ylim(
    0,
    5.5,
)

plt.legend(
    fontsize=8,
)

plt.tight_layout()

criteria_path = (
    OUTPUT_DIR
    / "criteria_comparison.png"
)

plt.savefig(
    criteria_path,
    dpi=180,
)

plt.close()


# ============================================================
# 3. 모델별 총점 순위
# ============================================================

plt.figure(
    figsize=(8, 5)
)

ranked = summary.sort_values(
    "total_score",
    ascending=True,
)

bars = plt.barh(
    ranked["model"],
    ranked["total_score"],
)

plt.xlabel(
    "Average Score / 25"
)

plt.title(
    "Rewrite Model Ranking"
)

plt.xlim(
    0,
    25,
)

for bar, value in zip(
    bars,
    ranked["total_score"],
):

    plt.text(
        value + 0.2,
        bar.get_y()
        + bar.get_height() / 2,
        f"{value:.2f}",
        va="center",
    )

plt.tight_layout()

ranking_path = (
    OUTPUT_DIR
    / "model_ranking.png"
)

plt.savefig(
    ranking_path,
    dpi=180,
)

plt.close()


# ============================================================
# 완료
# ============================================================

print()
print("=" * 70)
print("REWRITE BENCHMARK VISUALIZATION COMPLETE")
print("=" * 70)

print(
    "overall_score.png"
)

print(
    "criteria_comparison.png"
)

print(
    "model_ranking.png"
)

print()