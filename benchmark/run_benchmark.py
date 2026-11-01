import json
import os
import time
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from sklearn.metrics import (
    accuracy_score,
    precision_recall_fscore_support,
)

from openai import OpenAI
from anthropic import Anthropic
from google import genai


# ============================================================
# 기본 설정
# ============================================================

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent

DATA_PATH = PROJECT_DIR / "data" / "context_examples.json"
RESULT_DIR = BASE_DIR / "results"

RESULT_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

RESULT_CSV = RESULT_DIR / "benchmark_results.csv"


# ============================================================
# 모델 설정
#
# 실제 사용할 모델명은 .env에서 지정
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
# 평가 대상
# ============================================================

RISK_TAGS = {
    "PROFANITY",
    "INSULT",
    "THREAT",
    "LEGAL_ADMIN_ACTION_MENTION",
    "EXPOSURE",
    "REPEAT",
    "UNREASONABLE_DEMAND",
    "PERSONAL_INFO_RISK",
}


# ============================================================
# 공통 Prompt
# ============================================================

SYSTEM_PROMPT = """
당신은 학교 학부모 민원 분석 AI입니다.

입력된 학부모 민원을 분석하고 반드시 JSON만 반환하십시오.

반환 형식:

{
  "communicationIntent": "민원 유형",
  "riskTags": [
    {
      "code": "위험요소 코드",
      "evidenceSpans": [
        {
          "text": "원문 근거"
        }
      ],
      "reason": "판단 이유"
    }
  ]
}

communicationIntent는 다음 중 하나를 사용하십시오.

- INFORMATION_INQUIRY
- COUNSELING_REQUEST
- ACTION_REQUEST
- OBJECTION_COMPLAINT
- STATUS_FOLLOWUP

riskTags의 code는 다음 중 실제 해당하는 것만 선택하십시오.

- PROFANITY
- INSULT
- THREAT
- LEGAL_ADMIN_ACTION_MENTION
- EXPOSURE
- REPEAT
- UNREASONABLE_DEMAND
- PERSONAL_INFO_RISK

해당 위험요소가 없다면 riskTags는 빈 배열로 반환하십시오.

중요:
- 원문에 없는 위험요소를 추측하지 마십시오.
- 명확한 근거가 있는 경우에만 위험요소를 선택하십시오.
- 반복성은 현재 문장만으로 명확하게 판단할 수 있는 경우에만 선택하십시오.
- JSON 이외의 설명은 출력하지 마십시오.
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
# GPT
# ============================================================

def call_gpt(message: str) -> dict[str, Any]:

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

    return {
        "text": response.output_text,
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

def call_claude(message: str) -> dict[str, Any]:

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

    return {
        "text": text,
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

def call_gemini(message: str) -> dict[str, Any]:

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

    return {
        "text": response.text,
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
# JSON 파싱
# ============================================================

def parse_response(text: str) -> dict[str, Any] | None:

    try:
        return json.loads(text)

    except json.JSONDecodeError:

        # 혹시 ```json ... ``` 형태로 반환한 경우
        text = text.strip()

        if text.startswith("```json"):
            text = text[7:]

        if text.endswith("```"):
            text = text[:-3]

        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            return None


# ============================================================
# 정답 태그 추출
# ============================================================

def get_gold_tags(item: dict[str, Any]) -> set[str]:

    return {
        tag["code"]
        for tag in item.get("tags", [])
    }


# ============================================================
# 모델 태그 추출
# ============================================================

def get_predicted_tags(
    parsed: dict[str, Any] | None,
) -> set[str]:

    if not parsed:
        return set()

    tags = parsed.get(
        "riskTags",
        [],
    )

    result = set()

    for tag in tags:

        if isinstance(tag, str):
            code = tag

        else:
            code = tag.get("code")

        if code in RISK_TAGS:
            result.add(code)

    return result


# ============================================================
# 위험 태그 평가
# ============================================================

def evaluate_tags(
    gold: set[str],
    predicted: set[str],
) -> tuple[float, float, float]:

    y_true = [
        int(tag in gold)
        for tag in RISK_TAGS
    ]

    y_pred = [
        int(tag in predicted)
        for tag in RISK_TAGS
    ]

    precision, recall, f1, _ = (
        precision_recall_fscore_support(
            y_true,
            y_pred,
            average="macro",
            zero_division=0,
        )
    )

    return (
        precision,
        recall,
        f1,
    )


# ============================================================
# 민원 유형 평가
# ============================================================

def evaluate_intent(
    gold: str,
    predicted: str | None,
) -> int:

    if not predicted:
        return 0

    return int(
        gold == predicted
    )


# ============================================================
# 메인
# ============================================================

def main():

    dataset = load_dataset()

    print(
        f"\n총 데이터: {len(dataset)}건"
    )

    rows = []

    for index, item in enumerate(
        dataset,
        start=1,
    ):

        case_id = item["caseId"]
        message = item["message"]

        gold_tags = get_gold_tags(item)

        gold_intent = item[
            "context"
        ]["communicationIntent"]

        print(
            f"\n[{index}/{len(dataset)}] "
            f"{case_id}"
        )

        for model_name in [
            "GPT",
            "Claude",
            "Gemini",
        ]:

            print(
                f"  → {model_name}"
            )

            try:

                if model_name == "GPT":
                    result = call_gpt(message)

                elif model_name == "Claude":
                    result = call_claude(message)

                else:
                    result = call_gemini(message)

                parsed = parse_response(
                    result["text"]
                )

                json_success = int(
                    parsed is not None
                )

                predicted_tags = (
                    get_predicted_tags(parsed)
                )

                predicted_intent = (
                    parsed.get(
                        "communicationIntent"
                    )
                    if parsed
                    else None
                )

                tag_precision, tag_recall, tag_f1 = (
                    evaluate_tags(
                        gold_tags,
                        predicted_tags,
                    )
                )

                intent_accuracy = (
                    evaluate_intent(
                        gold_intent,
                        predicted_intent,
                    )
                )

                rows.append(
                    {
                        "case_id": case_id,
                        "model": model_name,
                        "model_name": MODELS[model_name],

                        "json_success": json_success,

                        "tag_precision": tag_precision,
                        "tag_recall": tag_recall,
                        "tag_f1": tag_f1,

                        "intent_correct": intent_accuracy,

                        "latency_ms": result[
                            "latency_ms"
                        ],

                        "input_tokens": result[
                            "input_tokens"
                        ],

                        "output_tokens": result[
                            "output_tokens"
                        ],

                        "gold_tags": ",".join(
                            sorted(gold_tags)
                        ),

                        "predicted_tags": ",".join(
                            sorted(predicted_tags)
                        ),

                        "gold_intent": gold_intent,

                        "predicted_intent": (
                            predicted_intent
                            or ""
                        ),

                        "raw_response": result[
                            "text"
                        ],
                    }
                )

            except Exception as e:

                print(
                    f"    ERROR: {e}"
                )

                rows.append(
                    {
                        "case_id": case_id,
                        "model": model_name,
                        "model_name": MODELS[model_name],
                        "json_success": 0,
                        "tag_precision": 0,
                        "tag_recall": 0,
                        "tag_f1": 0,
                        "intent_correct": 0,
                        "latency_ms": None,
                        "input_tokens": None,
                        "output_tokens": None,
                        "gold_tags": ",".join(
                            sorted(gold_tags)
                        ),
                        "predicted_tags": "",
                        "gold_intent": gold_intent,
                        "predicted_intent": "",
                        "raw_response": f"ERROR: {e}",
                    }
                )

    df = pd.DataFrame(rows)

    df.to_csv(
        RESULT_CSV,
        index=False,
        encoding="utf-8-sig",
    )

    print(
        f"\n결과 저장: {RESULT_CSV}"
    )

    # ========================================================
    # 모델별 요약
    # ========================================================

    summary = (
        df.groupby("model")
        .agg(
            json_success_rate=(
                "json_success",
                "mean",
            ),
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

    print(
        "\n=============================="
    )
    print(
        "MODEL BENCHMARK SUMMARY"
    )
    print(
        "=============================="
    )

    print(
        summary.to_string(
            index=False
        )
    )

    summary.to_csv(
        RESULT_DIR / "model_summary.csv",
        index=False,
        encoding="utf-8-sig",
    )


if __name__ == "__main__":
    main()