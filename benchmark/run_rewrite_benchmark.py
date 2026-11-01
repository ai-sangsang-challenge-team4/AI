import json
import os
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from openai import OpenAI
from anthropic import Anthropic
from google import genai


# ============================================================
# 기본 설정
# ============================================================

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

CASES_PATH = BASE_DIR / "cases.json"

RESULT_DIR = BASE_DIR / "results"
RESULT_DIR.mkdir(parents=True, exist_ok=True)

RESULT_CSV = RESULT_DIR / "rewrite_benchmark_results.csv"
HUMAN_EVAL_CSV = RESULT_DIR / "rewrite_human_eval.csv"


# ============================================================
# 모델 설정
# ============================================================

MODELS = [
    "GPT",
    "Claude",
    "Gemini",
]

GPT_MODEL = os.getenv(
    "GPT_MODEL",
    "gpt-5-mini",
)

CLAUDE_MODEL = os.getenv(
    "CLAUDE_MODEL",
    "claude-sonnet-5-5",
)

GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.5-flash-lite",
)


# ============================================================
# API Client
# ============================================================

openai_client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY")
)

anthropic_client = Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY")
)

gemini_client = genai.Client(
    api_key=os.getenv("GEMINI_API_KEY")
)


# ============================================================
# Prompt
# ============================================================

SYSTEM_PROMPT = """
당신은 학교 학부모 민원의 표현을 개선하는 보조 AI입니다.

학부모가 작성한 민원의 핵심 의도와 요구사항은 유지하면서
공격적이거나 감정적인 표현을 보다 중립적이고 건설적인 표현으로 수정합니다.

다음 원칙을 반드시 지킵니다.

1. 원문의 핵심 의도와 요구사항을 유지합니다.
2. 중요한 사실관계를 삭제하지 않습니다.
3. 욕설, 모욕, 비난, 공격적 표현은 중립적으로 완화합니다.
4. 정당한 문제 제기나 민원인의 요구를 임의로 삭제하지 않습니다.
5. 민원인이 제기한 문제를 임의로 사실로 확정하지 않습니다.
6. 원문에 없는 새로운 사실을 추가하지 않습니다.
7. 법률적 판단이나 학교의 책임을 임의로 확정하지 않습니다.
8. 위협이나 강한 표현이 있는 경우에도 그 의미 자체를 임의로 삭제하지 않습니다.
9. 개인정보가 포함되어 있더라도 불필요하게 반복하지 않습니다.
10. 실제 학교 민원에 사용할 수 있는 정중하고 명확한 문장으로 작성합니다.

출력은 반드시 다음 JSON 형식을 따릅니다.

{
  "revised_message": "수정된 민원 내용"
}
"""


# ============================================================
# 데이터 로드
# ============================================================

def load_cases():
    with open(
        CASES_PATH,
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)


# ============================================================
# JSON 파싱
# ============================================================

def parse_json_response(text: str) -> dict:

    text = text.strip()

    # ```json ... ``` 제거
    if text.startswith("```"):
        lines = text.splitlines()

        if lines[0].startswith("```"):
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        text = "\n".join(lines).strip()

    return json.loads(text)


# ============================================================
# GPT
# ============================================================

def call_gpt(message: str):

    start = time.perf_counter()

    response = openai_client.chat.completions.create(
        model=GPT_MODEL,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": message,
            },
        ],
        temperature=0,
    )

    latency_ms = (
        time.perf_counter() - start
    ) * 1000

    text = response.choices[0].message.content

    result = parse_json_response(text)

    return {
        "revised_message": result["revised_message"],
        "latency_ms": latency_ms,
        "input_tokens": getattr(
            response.usage,
            "prompt_tokens",
            None,
        ),
        "output_tokens": getattr(
            response.usage,
            "completion_tokens",
            None,
        ),
    }


# ============================================================
# Claude
# ============================================================

def call_claude(message: str):

    start = time.perf_counter()

    response = anthropic_client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=1000,
        temperature=0,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": message,
            }
        ],
    )

    latency_ms = (
        time.perf_counter() - start
    ) * 1000

    text = response.content[0].text

    result = parse_json_response(text)

    return {
        "revised_message": result["revised_message"],
        "latency_ms": latency_ms,
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

def call_gemini(message: str):

    start = time.perf_counter()

    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=message,
        config={
            "system_instruction": SYSTEM_PROMPT,
            "temperature": 0,
            "response_mime_type": "application/json",
        },
    )

    latency_ms = (
        time.perf_counter() - start
    ) * 1000

    text = response.text

    result = parse_json_response(text)

    usage = getattr(
        response,
        "usage_metadata",
        None,
    )

    input_tokens = getattr(
        usage,
        "prompt_token_count",
        None,
    )

    output_tokens = getattr(
        usage,
        "candidates_token_count",
        None,
    )

    return {
        "revised_message": result["revised_message"],
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }


# ============================================================
# 모델 호출
# ============================================================

def call_model(
    model_name: str,
    message: str,
):

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
# Human Evaluation CSV 생성
# ============================================================

def create_human_eval_file(df: pd.DataFrame):

    rows = []

    for _, row in df.iterrows():

        rows.append({
            "case_id": row["case_id"],
            "model": row["model"],
            "original_message": row["original_message"],
            "revised_message": row["revised_message"],

            # 사람이 직접 입력
            "intent_preservation": "",
            "information_preservation": "",
            "emotion_moderation": "",
            "expression_appropriateness": "",
            "over_smoothing_prevention": "",

            "total_score": "",
            "evaluator_note": "",
        })

    human_df = pd.DataFrame(rows)

    human_df.to_csv(
        HUMAN_EVAL_CSV,
        index=False,
        encoding="utf-8-sig",
    )


# ============================================================
# Main
# ============================================================

def main():

    cases = load_cases()

    print()
    print("=" * 60)
    print("민원 표현 수정 LLM BENCHMARK")
    print("=" * 60)
    print(
        f"총 데이터: {len(cases)}건"
    )
    print()

    results = []

    for index, case in enumerate(
        cases,
        start=1,
    ):

        case_id = case.get(
            "caseId",
            case.get("case_id"),
        )

        message = case.get(
            "message",
            case.get("original_message"),
        )

        print(
            f"[{index}/{len(cases)}] {case_id}"
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

                results.append({
                    "case_id": case_id,
                    "model": model_name,
                    "original_message": message,
                    "revised_message": result[
                        "revised_message"
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
                    "status": "SUCCESS",
                })

            except Exception as e:

                print(
                    f"    ERROR: {e}"
                )

                results.append({
                    "case_id": case_id,
                    "model": model_name,
                    "original_message": message,
                    "revised_message": "",
                    "latency_ms": None,
                    "input_tokens": None,
                    "output_tokens": None,
                    "status": f"FAILED: {e}",
                })

    df = pd.DataFrame(results)

    df.to_csv(
        RESULT_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    create_human_eval_file(df)

    print()
    print("=" * 60)
    print("REWRITE BENCHMARK COMPLETE")
    print("=" * 60)

    print(
        f"결과 저장: {RESULT_CSV}"
    )

    print(
        f"사람 평가 파일: {HUMAN_EVAL_CSV}"
    )

    print()
    print(
        "사람 평가 기준:"
    )
    print(
        "1. 의도 보존"
    )
    print(
        "2. 핵심 정보 보존"
    )
    print(
        "3. 감정 완화"
    )
    print(
        "4. 표현 적절성"
    )
    print(
        "5. 과도한 순화 방지"
    )


if __name__ == "__main__":
    main()