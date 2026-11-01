from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt


BASE_DIR = Path(__file__).resolve().parent
RESULT_DIR = BASE_DIR / "results"
FIGURE_DIR = RESULT_DIR / "figures"

FIGURE_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

RESULT_PATH = RESULT_DIR / "benchmark_results.csv"


def bar_chart(
    data,
    title,
    ylabel,
    filename,
):

    plt.figure(
        figsize=(8, 5)
    )

    data.plot(
        kind="bar"
    )

    plt.title(title)
    plt.ylabel(ylabel)
    plt.xlabel("Model")

    plt.xticks(
        rotation=0
    )

    plt.ylim(
        0,
        1
    )

    plt.grid(
        axis="y",
        alpha=0.2,
    )

    plt.tight_layout()

    plt.savefig(
        FIGURE_DIR / filename,
        dpi=200,
    )

    plt.close()


def main():

    df = pd.read_csv(
        RESULT_PATH
    )

    summary = (
        df.groupby("model")
        .agg(
            tag_precision=(
                "tag_precision",
                "mean",
            ),
            tag_recall=(
                "tag_recall",
                "mean",
            ),
            tag_f1=(
                "tag_f1",
                "mean",
            ),
            intent_accuracy=(
                "intent_correct",
                "mean",
            ),
            json_success_rate=(
                "json_success",
                "mean",
            ),
        )
    )

    # ------------------------------------------
    # 위험요소 분류 F1
    # ------------------------------------------

    bar_chart(
        summary["tag_f1"],
        "Risk Tag Classification F1",
        "F1",
        "risk_tag_f1.png",
    )

    # ------------------------------------------
    # 위험요소 Precision
    # ------------------------------------------

    bar_chart(
        summary["tag_precision"],
        "Risk Tag Precision",
        "Precision",
        "risk_tag_precision.png",
    )

    # ------------------------------------------
    # 위험요소 Recall
    # ------------------------------------------

    bar_chart(
        summary["tag_recall"],
        "Risk Tag Recall",
        "Recall",
        "risk_tag_recall.png",
    )

    # ------------------------------------------
    # 민원 유형 분류
    # ------------------------------------------

    bar_chart(
        summary["intent_accuracy"],
        "Communication Intent Accuracy",
        "Accuracy",
        "intent_accuracy.png",
    )

    # ------------------------------------------
    # JSON 출력 안정성
    # ------------------------------------------

    bar_chart(
        summary["json_success_rate"],
        "JSON Output Success Rate",
        "Success Rate",
        "json_success_rate.png",
    )

    # ------------------------------------------
    # 응답시간
    # ------------------------------------------

    latency = (
        df.groupby("model")[
            "latency_ms"
        ]
        .mean()
    )

    plt.figure(
        figsize=(8, 5)
    )

    latency.plot(
        kind="bar"
    )

    plt.title(
        "Average Response Latency"
    )

    plt.ylabel(
        "Milliseconds"
    )

    plt.xlabel(
        "Model"
    )

    plt.xticks(
        rotation=0
    )

    plt.grid(
        axis="y",
        alpha=0.2,
    )

    plt.tight_layout()

    plt.savefig(
        FIGURE_DIR / "latency.png",
        dpi=200,
    )

    plt.close()

    print(
        f"\n그래프 저장 위치:"
        f"\n{FIGURE_DIR}"
    )


if __name__ == "__main__":
    main()