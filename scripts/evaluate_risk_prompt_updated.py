#!/usr/bin/env python3
"""Backward-compatible CLI for dev/Golden Set tagging evaluation (#26)."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Re-export the old helpers for callers while keeping shared logic out of the CLI.
from scripts.evaluation.data import (
    ALLOWED_STATES, BACKEND_CODES, BACKEND_TO_RISK_FACTOR, EVALUATED_CODES,
    RISK_FACTOR_TO_BACKEND, clean, ensure_complete_labels, load_cases, load_labels,
    read_csv as _read_csv,
)
from scripts.evaluation.contracts import parse_predictions
from scripts.evaluation.metrics import (
    build_tag_metrics, calculate_present_metrics, evidence_match, safe_divide,
)
from scripts.evaluation.reporting import write_csv
from scripts.evaluation.runner import ANALYZE_PATH, analyze_case, evaluate, post_json

DEFAULT_DATA_DIR = Path("data/dev")
DEFAULT_REPORT_DIR = Path("reports/risk_prompt_eval")
DEFAULT_BASE_URL = "http://localhost:8000"


def read_csv(path):
    return _read_csv(path)[1]


def build_parser():
    parser = argparse.ArgumentParser(description="개발셋/골든셋 태깅 평가, 검증, 결과 저장 및 비교")
    parser.add_argument("--data-dir", help="생략하면 선택한 데이터셋의 기존 저장소 경로 사용")
    parser.add_argument("--dataset", choices=("auto", "dev", "goldenset"), default="auto")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--case-id", action="append", dest="case_ids")
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--validate-only", action="store_true", help="CSV·중복만 검증, HTTP 호출 없음")
    parser.add_argument("--predictions", help="저장된 JSON/JSONL 예측으로 평가, HTTP 호출 없음")
    parser.add_argument("--mode", choices=("llm", "rule_llm"), default="llm")
    parser.add_argument("--rule-results", help="case_id -> 백엔드 규칙 결과 배열인 JSON 파일")
    parser.add_argument("--overlap-data-dir", help="개발셋/골든셋 중 반대쪽 데이터 폴더")
    parser.add_argument("--positive-policy", choices=("present", "present_boundary", "both"), default="both")
    parser.add_argument("--previous", help="비교할 불변 실행 디렉터리(manifest.json 포함)")
    parser.add_argument("--run-version", default="tagging-v1")
    parser.add_argument("--prompt-version")
    parser.add_argument("--rule-version")
    parser.add_argument("--dataset-version")
    parser.add_argument("--rag-version")
    parser.add_argument("--codebook-version", default="v1-2026-11-09")
    parser.add_argument("--codebook-file", help="공유 코드북 파일이 있으면 해시 기록")
    parser.add_argument("--targets", help="사람이 검토한 위험도·세부 유형 정답 CSV")
    parser.add_argument("--risk-predictions", help="Backend Risk Engine이 계산한 위험도 JSON")
    parser.add_argument("--write-target-template", metavar="CSV", help="정답을 생성하지 않고 빈 검토 양식 저장; HTTP 호출 없음")
    parser.add_argument("--charts", action="store_true", help="matplotlib로 F1·혼동행렬 PNG 저장")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or not math.isfinite(args.sleep) or args.timeout <= 0 or args.sleep < 0:
        parser.error("--timeout must be positive; --sleep must be nonnegative")
    args.policies = ["present", "present_boundary"] if args.positive_policy == "both" else [args.positive_policy]
    try:
        metrics, directory, status = evaluate(args)
    except (ValueError, OSError, KeyError) as exc:
        print(f"평가 설정/데이터 오류: {exc}", file=sys.stderr)
        return 2
    if args.validate_only or args.write_target_template:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
    else:
        print("평가 범위: 7종 태그, REPEAT 제외(history_not_supplied)")
        print(json.dumps(metrics["coverage"], ensure_ascii=False))
        for policy, result in metrics["binary"].items():
            print(f"{policy}: Macro F1={result['macro_f1']}, Micro F1={result['micro']['f1']}")
        print(f"결과 저장: {directory}")
    return status


if __name__ == "__main__":
    sys.exit(main())
