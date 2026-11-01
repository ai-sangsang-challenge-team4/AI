import json
import os
import time
from pathlib import Path
from typing import Any

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

# 기존 Risk Tagging 벤치마크와 동일한 데이터 사용
DATA_PATH = (
    PROJECT_DIR
    / "data"
    / "context_examples.json"
)

RESULT_DIR = (
    BASE_DIR
    / "results"
)

RESULT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

RESULT_CSV = (
    RESULT_DIR
    / "rewrite_benchmark_results.csv"
)

HUMAN_EVAL_CSV = (
    RESULT_DIR
    / "rewrite_human_eval.csv"
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
# 클라이언트
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
# Prompt
# ============================================================

SYSTEM_PROMPT = """
당신은 학교 학부모 민원의 표현을 개선하는 보조 AI입니다.

학부모가 작성한 민원의 핵심 의도와 요구사항은 유지하면서
공격적이거나 감정적인 표현을 보다 중립적이고 건설적인 표현으로 수정합니다.

반드시 다음 원칙을 지키십시오.

1. 원문의 핵심 의도와 요구사항을 유지하십시오.
2. 중요한 사실관계를 삭제하지 마십시오.
3. 욕설, 모욕, 비난, 공격적인 표현은 중립적이고 정중한 표현으로 완화하십시오.
4. 민원인의 정당한 문제 제기나 요구를 임의로 삭제하지 마십시오.
5. 원문에 없는 새로운 사실을 추가하지 마십시오.
6. 민원인이 제기한 주장을 확인된 사실처럼 단정하지 마십시오.
7. 법률적 판단이나 학교의 책임을 임의로 확정하지 마십시오.
8. 교육청 민원, 공식 민원 제기 등의 의사표시는
   감정적인 표현만 완화하고 그 의미 자체는 유지하십시오.
9. 개인정보가 포함되어 있는 경우 불필요하게 반복하지 마십시오.
10. 실제 학교 민원에 사용할 수 있는 정중하고 명확한 문장으로 작성하십시오.
11. 원문의 의미를 지나치게 순화하여 민원인의 요구를 약화시키지 마십시오.

출력은 반드시 JSON만 반환하십시오.

반환 형식:

{
  "revised_message": "수정된 민원 내용"
}

JSON 이외의 설명은 출력하지 마십시오.
"""


# ============================================================
# 데이터 로드
# ============================================================

def load_dataset() -> list[dict[str, Any]]:

    with open(
        DATA_PATH,
        "r",
        encoding="utf-8",
    ) as f:
        return json.load(f)


# ============================================================
# JSON 파싱
# ============================================================

def parse_json_response(
    text: str,
) -> dict[str, Any]:

    text = text.strip()

    # 혹시 모델이 markdown code fence를 붙인 경우 제거
    if text.startswith("```"):

        lines = text.splitlines()

        if lines:
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        text = "\n".join(lines).strip()

    return json.loads(text)


# ============================================================
# GPT
# ============================================================

def call_gpt(
    message: str,
) -> dict[str, Any]:

    start = time.perf_counter()

    response = openai_client.responses.create(
        model=MODELS["GPT"],
        instructions=SYSTEM_PROMPT,
        input=message,
    )

    latency = (
        time.perf_counter() - start
    ) * 1000

    usage = response.usage

    result = parse_json_response(
        response.output_text
    )

    return {
        "text": result["revised_message"],
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
        max_tokens=1000,
        system=SYSTEM_PROMPT,
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

    result = parse_json_response(text)

    return {
        "text": result["revised_message"],
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
            "system_instruction": SYSTEM_PROMPT,
            "response_mime_type": "application/json",
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

    result = parse_json_response(
        response.text
    )

    return {
        "text": result["revised_message"],
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
# Main
# ============================================================

def main():

    data = load_dataset()

    print()
    print("=" * 60)
    print("민원 표현 수정 LLM BENCHMARK")
    print("=" * 60)
    print(
        f"총 데이터: {len(data)}건"
    )
    print()

    results = []

    for index, row in enumerate(
        data,
        start=1,
    ):

        # 기존 context_examples.json의 필드 사용
        case_id = row.get(
            "caseId"
        )

        message = row.get(
            "message"
        )

        if not case_id:
            case_id = row.get(
                "case_id"
            )

        if not message:
            message = row.get(
                "original_message"
            )

        if not case_id or not message:

            print(
                f"[{index}/{len(data)}] "
                "ERROR: 데이터 형식 확인 필요"
            )

            print(row)

            continue

        print(
            f"[{index}/{len(data)}] "
            f"{case_id}"
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
                        "text"
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
                    f"    ERROR: {type(e).__name__}"
                )
                print(
                    f"    {e}"
                )

                results.append({
                    "case_id": case_id,
                    "model": model_name,
                    "original_message": message,
                    "revised_message": "",
                    "latency_ms": None,
                    "input_tokens": None,
                    "output_tokens": None,
                    "status": "FAILED",
                })

    # ========================================================
    # 결과 저장
    # ========================================================

    df = pd.DataFrame(results)

    df.to_csv(
        RESULT_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    # ========================================================
    # 사람 평가용 CSV
    # ========================================================

    human_eval = df[
        [
            "case_id",
            "model",
            "original_message",
            "revised_message",
        ]
    ].copy()

    human_eval[
        "intent_preservation"
    ] = ""

    human_eval[
        "information_preservation"
    ] = ""

    human_eval[
        "emotion_moderation"
    ] = ""

    human_eval[
        "expression_appropriateness"
    ] = ""

    human_eval[
        "over_smoothing_prevention"
    ] = ""

    human_eval[
        "total_score"
    ] = ""

    human_eval[
        "evaluator_note"
    ] = ""

    human_eval.to_csv(
        HUMAN_EVAL_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    # ========================================================
    # Summary
    # ========================================================

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

    success_count = (
        df["status"]
        == "SUCCESS"
    ).sum()

    print(
        f"성공: {success_count}"
    )

    print(
        f"전체: {len(df)}"
    )


if __name__ == "__main__":
    main()