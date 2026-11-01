
import csv
import json
import os
import time
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from rouge_score import rouge_scorer
from bert_score import score as bert_score

from openai import OpenAI
from anthropic import Anthropic
from google import genai


# ============================================================
# 기본 설정
# ============================================================

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

GOLD_PATH = (
    BASE_DIR
    / "summary_results"
    / "summary_gold.csv"
)

RESULT_DIR = (
    BASE_DIR
    / "summary_results"
)

RESULT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

RESULT_CSV = (
    RESULT_DIR
    / "summary_benchmark_results.csv"
)


# ============================================================
# 모델 설정
# ============================================================

MODELS = {
    "GPT": os.getenv("OPENAI_MODEL"),
    "Claude": os.getenv("ANTHROPIC_MODEL"),
    "Gemini": os.getenv("GEMINI_MODEL"),
}


# ============================================================
# API Client
# ============================================================

openai_client = OpenAI(
    api_key=os.environ["OPENAI_API_KEY"]
)

anthropic_client = Anthropic(
    api_key=os.environ["ANTHROPIC_API_KEY"]
)

gemini_client = genai.Client(
    api_key=os.environ["GEMINI_API_KEY"]
)


# ============================================================
# 완충 요약 Prompt
# ============================================================

SUMMARY_PROMPT = """
당신은 학교 학부모 민원 내용을 교사가 검토하기 쉽게 정리하는 AI입니다.

입력된 민원을 감정적으로 완화하여 요약하십시오.

반드시 다음 원칙을 지키십시오.

1. 민원인의 핵심 의도와 요구사항을 반드시 유지하십시오.
2. 사건의 핵심 사실과 요청사항을 누락하지 마십시오.
3. 욕설, 비난, 감정적 표현은 중립적인 표현으로 완화하십시오.
4. 원문에 없는 사실이나 판단을 추가하지 마십시오.
5. 민원인의 주장을 사실로 확정하지 마십시오.
6. 반복적인 표현과 불필요한 감정 표현은 제거하십시오.
7. 지나치게 짧게 요약하여 핵심 요구사항이 사라지지 않도록 하십시오.
8. 교사가 민원의 핵심 내용을 빠르게 파악할 수 있는 문장으로 작성하십시오.

출력은 요약문만 반환하십시오.
"""


# ============================================================
# 데이터 로드
# ============================================================

def load_gold_data() -> list[dict[str, Any]]:
    data = []

    with open(
        GOLD_PATH,
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as f:

        reader = csv.DictReader(f)

        for row in reader:
            data.append(row)

    return data


# ============================================================
# GPT
# ============================================================

def call_gpt(
    message: str,
) -> dict[str, Any]:

    start = time.perf_counter()

    response = openai_client.responses.create(
        model=MODELS["GPT"],
        instructions=SUMMARY_PROMPT,
        input=message,
    )

    latency = (
        time.perf_counter() - start
    ) * 1000

    usage = response.usage

    return {
        "summary": response.output_text.strip(),
        "latency_ms": latency,
        "input_tokens": getattr(
            usage,
            "input_tokens",
            None,
        ),
        "output_tokens": getattr(
            usage,
            "output_tokens",
            None,
        ),
    }


# ============================================================
# Claude
# ============================================================

def call_claude(
    message: str,
) -> dict[str, Any]:

    start = time.perf_counter()

    response = anthropic_client.messages.create(
        model=MODELS["Claude"],
        max_tokens=500,
        system=SUMMARY_PROMPT,
        messages=[
            {
                "role": "user",
                "content": message,
            }
        ],
    )

    latency = (
        time.perf_counter() - start
    ) * 1000

    text = ""

    for block in response.content:
        if hasattr(block, "text"):
            text += block.text

    return {
        "summary": text.strip(),
        "latency_ms": latency,
        "input_tokens": getattr(
            response.usage,
            "input_tokens",
            None,
        ),
        "output_tokens": getattr(
            response.usage,
            "output_tokens",
            None,
        ),
    }


# ============================================================
# Gemini
# ============================================================

def call_gemini(
    message: str,
) -> dict[str, Any]:

    start = time.perf_counter()

    response = gemini_client.models.generate_content(
        model=MODELS["Gemini"],
        contents=message,
        config={
            "system_instruction": SUMMARY_PROMPT,
        },
    )

    latency = (
        time.perf_counter() - start
    ) * 1000

    usage = getattr(
        response,
        "usage_metadata",
        None,
    )

    return {
        "summary": response.text.strip(),
        "latency_ms": latency,
        "input_tokens": getattr(
            usage,
            "prompt_token_count",
            None,
        ),
        "output_tokens": getattr(
            usage,
            "candidates_token_count",
            None,
        ),
    }


# ============================================================
# 모델 호출
# ============================================================

def call_model(
    model_name: str,
    message: str,
) -> dict[str, Any]:

    if model_name == "GPT":
        return call_gpt(message)

    if model_name == "Claude":
        return call_claude(message)

    if model_name == "Gemini":
        return call_gemini(message)

    raise ValueError(
        f"Unknown model: {model_name}"
    )


# ============================================================
# ROUGE 계산
# ============================================================

def calculate_rouge(
    reference: str,
    candidate: str,
) -> dict[str, float]:

    scorer = rouge_scorer.RougeScorer(
        [
            "rouge1",
            "rougeL",
        ],
        use_stemmer=False,
    )

    scores = scorer.score(
        reference,
        candidate,
    )

    return {
        "rouge1": scores["rouge1"].fmeasure,
        "rougeL": scores["rougeL"].fmeasure,
    }


# ============================================================
# 메인
# ============================================================

def main():

    data = load_gold_data()

    print()
    print("=" * 60)
    print("완충 요약 LLM BENCHMARK")
    print("=" * 60)
    print(f"총 데이터: {len(data)}건")
    print()

    results = []

    for index, row in enumerate(
        data,
        start=1,
    ):

        case_id = row["caseId"]
        message = row["message"]
        gold_summary = row["gold_summary"]

        print(
            f"[{index}/{len(data)}] {case_id}"
        )

        for model_name in MODELS:

            print(
                f"  → {model_name}"
            )

            try:

                result = call_model(
                    model_name,
                    message,
                )

                rouge = calculate_rouge(
                    gold_summary,
                    result["summary"],
                )

                results.append({
                    "case_id": case_id,
                    "model": model_name,
                    "gold_summary": gold_summary,
                    "generated_summary": result[
                        "summary"
                    ],
                    "rouge1": rouge[
                        "rouge1"
                    ],
                    "rougeL": rouge[
                        "rougeL"
                    ],
                    "latency_ms": result[
                        "latency_ms"
                    ],
                    "input_tokens": result[
                        "input_tokens"
                    ],
                    "output_tokens": result[
                        "output_tokens"
                    ],
                })

            except Exception as e:

                print(
                    f"    ERROR: {e}"
                )

                results.append({
                    "case_id": case_id,
                    "model": model_name,
                    "gold_summary": gold_summary,
                    "generated_summary": "",
                    "rouge1": None,
                    "rougeL": None,
                    "latency_ms": None,
                    "input_tokens": None,
                    "output_tokens": None,
                })

    df = pd.DataFrame(results)

    df.to_csv(
        RESULT_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    # ========================================================
    # BERTScore
    # ========================================================

    print()
    print("=" * 60)
    print("BERTScore 계산")
    print("=" * 60)

    df["bertscore_f1"] = None

    for model_name in MODELS:

        mask = (
            df["model"]
            == model_name
        )

        valid = (
            mask
            & df["generated_summary"]
            .fillna("")
            .ne("")
        )

        candidates = df.loc[
            valid,
            "generated_summary",
        ].tolist()

        references = df.loc[
            valid,
            "gold_summary",
        ].tolist()

        if not candidates:
            continue

        _, _, f1 = bert_score(
            candidates,
            references,
            lang="ko",
            verbose=False,
        )

        df.loc[
            valid,
            "bertscore_f1",
        ] = f1.tolist()

    df.to_csv(
        RESULT_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    # ========================================================
    # Summary
    # ========================================================

    summary = (
        df.groupby("model")
        .agg(
            rouge1=(
                "rouge1",
                "mean",
            ),
            rougeL=(
                "rougeL",
                "mean",
            ),
            bertscore_f1=(
                "bertscore_f1",
                "mean",
            ),
            avg_latency_ms=(
                "latency_ms",
                "mean",
            ),
            avg_input_tokens=(
                "input_tokens",
                "mean",
            ),
            avg_output_tokens=(
                "output_tokens",
                "mean",
            ),
        )
        .reset_index()
    )

    summary_path = (
        RESULT_DIR
        / "summary_benchmark_summary.csv"
    )

    summary.to_csv(
        summary_path,
        index=False,
        encoding="utf-8-sig",
    )

    print()
    print("=" * 70)
    print("SUMMARY BENCHMARK RESULT")
    print("=" * 70)

    print(
        summary.to_string(
            index=False,
        )
    )

    print()
    print(
        f"결과 저장: {RESULT_CSV}"
    )

    print(
        f"요약 저장: {summary_path}"
    )


if __name__ == "__main__":
    main()
