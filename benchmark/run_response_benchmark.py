import json
import os
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI
from anthropic import Anthropic
from google import genai

from app.rag.retriever import RagRetriever


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

RESULT_PATH = (
    RESULT_DIR / "response_benchmark_results.json"
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
# RAG Retriever
# ============================================================

retriever = RagRetriever()


# ============================================================
# 답변 생성 Prompt
# ============================================================

SYSTEM_PROMPT = """
당신은 학교 학부모 민원에 답변하는 교사를 지원하는 AI입니다.

아래 학부모 민원과 학교·교육 관련 규정 문서를 참고하여
교사가 검토할 수 있는 답변 초안을 작성하십시오.

중요한 원칙:

1. 제공된 규정 문서를 근거로 답변하십시오.
2. 규정 문서에 없는 내용을 사실처럼 만들어내지 마십시오.
3. 학부모의 질문과 요구사항에 직접 답하십시오.
4. 법률적 판단이나 확정적인 판단이 필요한 경우 단정하지 마십시오.
5. 학부모의 감정적인 표현을 그대로 반복하지 말고 중립적이고 정중하게 작성하십시오.
6. 교사가 최종 검토 후 사용할 수 있는 답변 초안 형태로 작성하십시오.
7. 불필요하게 장황하게 작성하지 마십시오.

반드시 다음 형식으로 답변하십시오.

답변 초안:
[교사가 검토할 답변]

근거:
- [사용한 규정 또는 문서의 출처]
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
# RAG Context 생성
# ============================================================

def build_rag_context(
    documents: list[dict],
) -> str:

    parts = []

    for index, document in enumerate(
        documents,
        start=1,
    ):

        source = document.get(
            "source",
            "출처 미상",
        )

        page = document.get(
            "page",
            "",
        )

        content = document.get(
            "content",
            "",
        )

        parts.append(
            f"""
[규정 문서 {index}]
출처: {source}
페이지: {page}

{content}
"""
        )

    return "\n".join(parts)


# ============================================================
# 공통 입력 생성
# ============================================================

def build_prompt(
    message: str,
    rag_context: str,
) -> str:

    return f"""
[학부모 민원]

{message}


[검색된 학교·교육 관련 규정]

{rag_context}


위 민원과 검색된 규정만을 바탕으로
교사가 사용할 답변 초안을 작성하십시오.
"""


# ============================================================
# GPT
# ============================================================

def call_gpt(
    prompt: str,
) -> dict[str, Any]:

    start = time.perf_counter()

    response = openai_client.responses.create(
        model=MODELS["GPT"],
        instructions=SYSTEM_PROMPT,
        input=prompt,
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

def call_claude(
    prompt: str,
) -> dict[str, Any]:

    start = time.perf_counter()

    response = anthropic_client.messages.create(
        model=MODELS["Claude"],
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": prompt,
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

def call_gemini(
    prompt: str,
) -> dict[str, Any]:

    start = time.perf_counter()

    response = gemini_client.models.generate_content(
        model=MODELS["Gemini"],
        contents=prompt,
        config={
            "system_instruction": SYSTEM_PROMPT,
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
# 메인
# ============================================================

def main():

    dataset = load_dataset()

    print()
    print("=" * 60)
    print("RAG 기반 답변 초안 LLM BENCHMARK")
    print("=" * 60)
    print(f"총 데이터: {len(dataset)}건")
    print()

    results = []

    for index, item in enumerate(
        dataset,
        start=1,
    ):

        case_id = item["caseId"]
        message = item["message"]

        print(
            f"[{index}/{len(dataset)}] {case_id}"
        )

        # ----------------------------------------------------
        # RAG 검색
        # ----------------------------------------------------

        documents = retriever.search(
            message,
            k=3,
        )

        rag_context = build_rag_context(
            documents
        )

        prompt = build_prompt(
            message,
            rag_context,
        )

        # ----------------------------------------------------
        # 모델별 답변 생성
        # ----------------------------------------------------

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

                    result = call_gpt(
                        prompt
                    )

                elif model_name == "Claude":

                    result = call_claude(
                        prompt
                    )

                else:

                    result = call_gemini(
                        prompt
                    )

                results.append(
                    {
                        "case_id": case_id,
                        "model": model_name,
                        "model_name": MODELS[
                            model_name
                        ],
                        "message": message,
                        "retrieved_documents": documents,
                        "generated_response": result[
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
                    }
                )

            except Exception as e:

                print(
                    f"    ERROR: {e}"
                )

                results.append(
                    {
                        "case_id": case_id,
                        "model": model_name,
                        "model_name": MODELS[
                            model_name
                        ],
                        "message": message,
                        "retrieved_documents": documents,
                        "generated_response": "",
                        "latency_ms": None,
                        "input_tokens": None,
                        "output_tokens": None,
                        "error": str(e),
                    }
                )

    # ========================================================
    # 결과 저장
    # ========================================================

    with open(
        RESULT_PATH,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            results,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print()
    print("=" * 60)
    print("RAG RESPONSE BENCHMARK COMPLETE")
    print("=" * 60)

    print(
        f"결과 저장: {RESULT_PATH}"
    )


if __name__ == "__main__":
    main()