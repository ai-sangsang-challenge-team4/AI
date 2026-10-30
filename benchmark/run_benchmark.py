import json
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv


# 프로젝트 루트를 Python import path에 추가
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


from app.llm.gemini_client import GeminiLlmClient


load_dotenv()


SYSTEM_PROMPT = """
너는 학교 민원 위험 분석 AI다.

민원 내용을 읽고 다음 위험 요소가 존재하는지 판단한다.

가능한 태그:
- THREAT: 협박, 보복, 위해 또는 불이익을 암시하는 표현
- UNFAIR_REQUEST: 규정이나 일반적인 절차를 벗어난 특혜, 예외, 일방적 조치를 요구하는 표현

위험 요소가 없으면 빈 배열을 반환한다.

반드시 다음 JSON 형식으로만 응답한다.

{
  "tags": [
    {
      "code": "THREAT 또는 UNFAIR_REQUEST",
      "confidence": 0.0,
      "evidence": "판단 근거가 되는 원문"
    }
  ]
}

주의:
- 민원 내용에 없는 사실을 추론하지 않는다.
- 단순한 문의나 불만은 위험 요소로 분류하지 않는다.
- 일반적인 행정 절차 문의는 위험 요소가 아니다.
- 법률적 판단을 단정하지 않는다.
"""


def build_prompt(complaint: str) -> str:
    return f"""
{SYSTEM_PROMPT}

[민원 내용]
{complaint}
""".strip()


def load_cases():
    with open(
        "benchmark/cases.json",
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f)


def run_gemini(cases):
    client = GeminiLlmClient()

    results = []

    for case in cases:
        print(f"Running {case['id']}...")

        start = time.perf_counter()

        try:
            response = client.generate(
                build_prompt(case["complaint"])
            )

            elapsed = time.perf_counter() - start

            results.append({
                "case_id": case["id"],
                "category": case["category"],
                "complaint": case["complaint"],
                "model": client.model,
                "response": response,
                "latency_seconds": round(elapsed, 3),
                "success": True,
                "error": None
            })

        except Exception as e:
            elapsed = time.perf_counter() - start

            results.append({
                "case_id": case["id"],
                "category": case["category"],
                "complaint": case["complaint"],
                "model": client.model,
                "response": None,
                "latency_seconds": round(elapsed, 3),
                "success": False,
                "error": str(e)
            })

    return results


def save_results(results):
    os.makedirs("benchmark/results", exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    path = (
        f"benchmark/results/"
        f"gemini_{timestamp}.json"
    )

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            results,
            f,
            ensure_ascii=False,
            indent=2
        )

    return path


if __name__ == "__main__":
    cases = load_cases()

    print(f"테스트 케이스: {len(cases)}개")

    results = run_gemini(cases)

    path = save_results(results)

    success_count = sum(
        1
        for result in results
        if result["success"]
    )

    print()
    print("===== BENCHMARK RESULT =====")
    print(f"모델: {results[0]['model']}")
    print(f"성공: {success_count}/{len(results)}")
    print(f"결과 파일: {path}")
