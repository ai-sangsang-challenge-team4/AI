import pandas as pd
import matplotlib.pyplot as plt
from matplotlib import font_manager
from pathlib import Path


# ============================================================
# macOS 한글 폰트 설정
# ============================================================

korean_font = "AppleGothic"

plt.rcParams["font.family"] = korean_font
plt.rcParams["axes.unicode_minus"] = False

# ============================================================
# 설정
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

INPUT_CSV = BASE_DIR / "results" / "response_human_eval.csv"
OUTPUT_DIR = BASE_DIR / "results"

OUTPUT_DIR.mkdir(exist_ok=True)


# ============================================================
# 데이터 불러오기
# ============================================================

df = pd.read_csv(INPUT_CSV, encoding="utf-8-sig")

# 점수 컬럼
score_columns = [
    "근거충실성",
    "질문대응성",
    "안전성",
    "교사검토용이성",
    "간결성",
]

# 숫자형 변환
for col in score_columns:
    df[col] = pd.to_numeric(df[col], errors="coerce")

# 총점 계산
df["총점"] = df[score_columns].sum(axis=1)


# ============================================================
# 모델별 평균
# ============================================================

summary = (
    df.groupby("model")[score_columns + ["총점"]]
    .mean()
    .round(2)
)

print()
print("=" * 70)
print("RAG RESPONSE HUMAN EVALUATION")
print("=" * 70)
print()
print(summary)
print()

summary.to_csv(
    OUTPUT_DIR / "response_human_eval_summary.csv",
    encoding="utf-8-sig",
)


# ============================================================
# 1. 모델별 총점 비교
# ============================================================

plt.figure(figsize=(8, 5))

summary["총점"].sort_values().plot(
    kind="bar",
)

plt.title("RAG Response Human Evaluation - Total Score")
plt.ylabel("Score (out of 25)")
plt.xlabel("Model")
plt.ylim(0, 25)
plt.xticks(rotation=0)
plt.tight_layout()

plt.savefig(
    OUTPUT_DIR / "response_human_eval_total.png",
    dpi=200,
)

plt.close()


# ============================================================
# 2. 평가 항목별 비교
# ============================================================

plot_df = summary[score_columns]

ax = plot_df.plot(
    kind="bar",
    figsize=(10, 6),
)

ax.set_title("RAG Response Human Evaluation by Criterion")
ax.set_ylabel("Average Score (1-5)")
ax.set_xlabel("Model")
ax.set_ylim(0, 5)
ax.tick_params(axis="x", rotation=0)

plt.tight_layout()

plt.savefig(
    OUTPUT_DIR / "response_human_eval_criteria.png",
    dpi=200,
)

plt.close()


# ============================================================
# 완료
# ============================================================

print("결과 저장:")
print(OUTPUT_DIR / "response_human_eval_summary.csv")
print(OUTPUT_DIR / "response_human_eval_total.png")
print(OUTPUT_DIR / "response_human_eval_criteria.png")