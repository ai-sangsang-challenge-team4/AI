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

CSV_PATH = RESULT_DIR / "benchmark_results.csv"


def plot_metric(
    df,
    metric,
    title,
    ylabel,
    filename,
):
    summary = (
        df.groupby("model")[metric]
        .mean()
        .dropna()
    )

    if summary.empty:
        print(
            f"[SKIP] {metric}: 데이터 없음"
        )
        return

    plt.figure(figsize=(8, 5))

    summary.plot(
        kind="bar"
    )

    plt.title(title)
    plt.ylabel(ylabel)
    plt.xlabel("Model")

    plt.xticks(
        rotation=0
    )

    plt.grid(
        axis="y",
        alpha=0.2,
    )

    plt.tight_layout()

    output_path = FIGURE_DIR / filename

    plt.savefig(
        output_path,
        dpi=200,
        bbox_inches="tight",
    )

    plt.close()

    print(
        f"[저장] {output_path}"
    )


def main():

    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"결과 파일이 없습니다: {CSV_PATH}"
        )

    df = pd.read_csv(
        CSV_PATH
    )

    # ----------------------------------------
    # 응답 시간
    # ----------------------------------------

    plot_metric(
        df,
        "latency_ms",
        "Average Response Latency",
        "Milliseconds",
        "latency.png",
    )

    # ----------------------------------------
    # JSON 출력 성공률
    # ----------------------------------------

    plot_metric(
        df,
        "json_success",
        "JSON Output Success Rate",
        "Success Rate",
        "json_success.png",
    )

    # ----------------------------------------
    # 토큰 사용량
    # ----------------------------------------

    plot_metric(
        df,
        "input_tokens",
        "Average Input Tokens",
        "Tokens",
        "input_tokens.png",
    )

    plot_metric(
        df,
        "output_tokens",
        "Average Output Tokens",
        "Tokens",
        "output_tokens.png",
    )


if __name__ == "__main__":
    main()