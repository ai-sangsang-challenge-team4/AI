#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


RISK_FACTOR_TO_BACKEND = {
    "GENERAL_PROFANITY_EMOTION": "PROFANITY",
    "DIRECT_INSULT_PERSONAL_ATTACK": "INSULT",
    "THREAT_INTIMIDATION": "THREAT",
    "LEGAL_ADMIN_ACTION_MENTION": "LEGAL",
    "PUBLIC_DISCLOSURE_THREAT": "EXPOSURE",
    "REPETITION": "REPEAT",
    "UNREASONABLE_DEMAND": "UNFAIR_REQUEST",
    "PERSONAL_INFO_MISUSE_RISK": "PRIVACY",
}

BACKEND_CODES = list(RISK_FACTOR_TO_BACKEND.values())

# Claude 단독 프롬프트 평가에서는 REPEAT를 성능 지표에서 제외한다.
# REPEAT는 과거 민원/처리 이력 또는 Backend Rule/History 신호가 있어야
# 의미 있게 평가할 수 있기 때문이다.
EVALUATED_CODES = [
    code
    for code in BACKEND_CODES
    if code != "REPEAT"
]

BACKEND_TO_RISK_FACTOR = {
    backend: source
    for source, backend in RISK_FACTOR_TO_BACKEND.items()
}

ALLOWED_STATES = {"PRESENT", "ABSENT", "BOUNDARY", "UNKNOWN"}

DEFAULT_DATA_DIR = Path("data/dev")
DEFAULT_REPORT_DIR = Path("reports/risk_prompt_eval")
DEFAULT_BASE_URL = "http://localhost:8000"
ANALYZE_PATH = "/api/v1/ai/analyze"


def clean(value: str | None) -> str:
    return (value or "").strip()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return [
            {
                key: clean(value)
                for key, value in row.items()
                if key is not None
            }
            for row in reader
        ]


def load_cases(path: Path) -> list[dict[str, str]]:
    rows = read_csv(path)

    for row in rows:
        if not row.get("case_id"):
            raise ValueError("cases CSV에 case_id가 비어 있는 행이 있습니다.")
        if not row.get("message_text"):
            raise ValueError(
                f"{row['case_id']}: message_text가 비어 있습니다."
            )

    return rows


def load_labels(
    path: Path,
) -> dict[str, dict[str, dict[str, str]]]:
    rows = read_csv(path)
    result: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)

    for row in rows:
        case_id = row.get("case_id", "")
        risk_factor = row.get("risk_factor", "")
        status = row.get("status", "")

        if not case_id:
            raise ValueError("labels CSV에 case_id가 비어 있는 행이 있습니다.")

        if risk_factor not in RISK_FACTOR_TO_BACKEND:
            raise ValueError(
                f"{case_id}: 알 수 없는 risk_factor={risk_factor!r}"
            )

        if status not in ALLOWED_STATES:
            raise ValueError(
                f"{case_id}/{risk_factor}: 알 수 없는 status={status!r}"
            )

        code = RISK_FACTOR_TO_BACKEND[risk_factor]

        if code in result[case_id]:
            raise ValueError(
                f"{case_id}/{risk_factor}: 중복 라벨이 있습니다."
            )

        row["backend_code"] = code
        result[case_id][code] = row

    return result


def ensure_complete_labels(
    cases: list[dict[str, str]],
    labels: dict[str, dict[str, dict[str, str]]],
) -> None:
    for case in cases:
        case_id = case["case_id"]

        if case_id not in labels:
            raise ValueError(f"{case_id}: 위험 라벨이 없습니다.")

        missing = [
            code
            for code in BACKEND_CODES
            if code not in labels[case_id]
        ]

        if missing:
            raise ValueError(
                f"{case_id}: 다음 위험 라벨이 없습니다: "
                + ", ".join(missing)
            )


def post_json(
    url: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    body = json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")

    request = Request(
        url=url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8")
    except HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"AI 서버 HTTP {exc.code}: {error_body}"
        ) from exc
    except URLError as exc:
        raise RuntimeError(
            f"AI 서버에 연결할 수 없습니다: {exc}"
        ) from exc

    try:
        parsed = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "AI 서버 응답이 JSON이 아닙니다: "
            + response_body[:500]
        ) from exc

    if not isinstance(parsed, dict):
        raise RuntimeError(
            "AI 서버 응답 최상위 값이 JSON 객체가 아닙니다."
        )

    return parsed


def analyze_case(
    base_url: str,
    complaint: str,
    timeout_seconds: float,
) -> tuple[dict[str, Any], float]:
    url = base_url.rstrip("/") + ANALYZE_PATH

    started = time.perf_counter()

    response = post_json(
        url=url,
        payload={
            "complaint": complaint,
            # 현재는 Claude 프롬프트 자체 성능을 평가한다.
            # Rule 결과는 의도적으로 비운다.
            "ruleResults": [],
        },
        timeout_seconds=timeout_seconds,
    )

    latency_ms = (time.perf_counter() - started) * 1000.0

    return response, latency_ms


def parse_predictions(
    response: dict[str, Any],
) -> tuple[
    dict[str, str],
    dict[str, float | None],
    dict[str, list[str]],
    dict[str, str],
]:
    # 출력되지 않은 태그는 프롬프트 계약상 ABSENT로 해석한다.
    states = {code: "ABSENT" for code in BACKEND_CODES}
    confidences = {code: None for code in BACKEND_CODES}
    evidences = {code: [] for code in BACKEND_CODES}
    reasons = {code: "" for code in BACKEND_CODES}

    tags = response.get("tags", [])

    if not isinstance(tags, list):
        raise ValueError("AI 응답 tags가 list가 아닙니다.")

    for tag in tags:
        if not isinstance(tag, dict):
            raise ValueError("AI 응답 tags 내부 값이 객체가 아닙니다.")

        code = clean(str(tag.get("code", "")))
        state = clean(str(tag.get("state", "")))

        if code not in BACKEND_CODES:
            raise ValueError(
                f"AI가 허용되지 않은 code를 반환했습니다: {code!r}"
            )

        if state not in ALLOWED_STATES:
            raise ValueError(
                f"AI가 허용되지 않은 state를 반환했습니다: "
                f"{code}={state!r}"
            )

        states[code] = state

        confidence = tag.get("confidence")
        if isinstance(confidence, (int, float)):
            confidences[code] = float(confidence)

        spans = tag.get("evidenceSpans", [])
        if isinstance(spans, list):
            evidences[code] = [
                clean(str(span.get("text", "")))
                for span in spans
                if isinstance(span, dict)
                and clean(str(span.get("text", "")))
            ]

        reasons[code] = clean(str(tag.get("reason", "")))

    return states, confidences, evidences, reasons


def safe_divide(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator


def calculate_present_metrics(
    gold_states: list[str],
    predicted_states: list[str],
) -> dict[str, float | int]:
    tp = fp = fn = tn = 0

    for gold, predicted in zip(
        gold_states,
        predicted_states,
        strict=True,
    ):
        gold_present = gold == "PRESENT"
        pred_present = predicted == "PRESENT"

        if gold_present and pred_present:
            tp += 1
        elif not gold_present and pred_present:
            fp += 1
        elif gold_present and not pred_present:
            fn += 1
        else:
            tn += 1

    precision = safe_divide(tp, tp + fp)
    recall = safe_divide(tp, tp + fn)
    f1 = (
        0.0
        if precision + recall == 0
        else 2 * precision * recall / (precision + recall)
    )

    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def evidence_match(
    gold_evidence: str,
    predicted_evidences: list[str],
) -> str:
    if not gold_evidence:
        return ""

    if not predicted_evidences:
        return "NO_PREDICTED_EVIDENCE"

    gold = "".join(gold_evidence.split())

    for predicted in predicted_evidences:
        pred = "".join(predicted.split())

        if gold in pred or pred in gold:
            return "MATCH"

    return "MISMATCH"


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        path.write_text("", encoding="utf-8")
        return

    fieldnames: list[str] = []

    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    with path.open(
        "w",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        writer.writerows(rows)


def build_tag_metrics(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    metrics = []

    for code in EVALUATED_CODES:
        tag_rows = [
            row
            for row in rows
            if row["code"] == code
            and row["request_success"] == 1
        ]

        gold_states = [row["gold_state"] for row in tag_rows]
        pred_states = [row["predicted_state"] for row in tag_rows]

        exact_matches = sum(
            1
            for gold, pred in zip(
                gold_states,
                pred_states,
                strict=True,
            )
            if gold == pred
        )

        binary = calculate_present_metrics(
            gold_states,
            pred_states,
        )

        gold_distribution = Counter(gold_states)
        pred_distribution = Counter(pred_states)

        metrics.append(
            {
                "code": code,
                "risk_factor": BACKEND_TO_RISK_FACTOR[code],
                "evaluated_cases": len(tag_rows),
                "exact_state_accuracy": round(
                    safe_divide(exact_matches, len(tag_rows)),
                    4,
                ),
                "present_precision": round(binary["precision"], 4),
                "present_recall": round(binary["recall"], 4),
                "present_f1": round(binary["f1"], 4),
                "tp": binary["tp"],
                "fp": binary["fp"],
                "fn": binary["fn"],
                "tn": binary["tn"],
                "gold_present": gold_distribution["PRESENT"],
                "gold_boundary": gold_distribution["BOUNDARY"],
                "gold_absent": gold_distribution["ABSENT"],
                "gold_unknown": gold_distribution["UNKNOWN"],
                "pred_present": pred_distribution["PRESENT"],
                "pred_boundary": pred_distribution["BOUNDARY"],
                "pred_absent": pred_distribution["ABSENT"],
                "pred_unknown": pred_distribution["UNKNOWN"],
            }
        )

    return metrics


def print_metrics(
    metrics: list[dict[str, Any]],
) -> None:
    print()
    print("========================================")
    print("태그별 평가 결과")
    print("========================================")

    header = (
        f"{'CODE':<16}"
        f"{'ACC':>8}"
        f"{'P':>8}"
        f"{'R':>8}"
        f"{'F1':>8}"
        f"{'FP':>6}"
        f"{'FN':>6}"
    )

    print(header)
    print("-" * len(header))

    for metric in metrics:
        print(
            f"{metric['code']:<16}"
            f"{metric['exact_state_accuracy']:>8.3f}"
            f"{metric['present_precision']:>8.3f}"
            f"{metric['present_recall']:>8.3f}"
            f"{metric['present_f1']:>8.3f}"
            f"{metric['fp']:>6}"
            f"{metric['fn']:>6}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "개발용 100건을 현재 Claude 위험 분석 프롬프트에 실행하고 "
            "개발 라벨과 비교합니다."
        )
    )

    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
    )
    parser.add_argument(
        "--report-dir",
        default=str(DEFAULT_REPORT_DIR),
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="앞에서부터 N건만 평가. 처음에는 --limit 5 권장",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        dest="case_ids",
        help="특정 case_id만 평가. 여러 번 지정 가능",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.2,
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
    )

    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    report_dir = Path(args.report_dir)

    cases_path = data_dir / "teachercare_dev_cases_100.csv"
    labels_path = data_dir / "teachercare_dev_risk_labels_100.csv"

    for path in [cases_path, labels_path]:
        if not path.exists():
            print(
                f"❌ 파일을 찾을 수 없습니다: {path}",
                file=sys.stderr,
            )
            return 1

    cases = load_cases(cases_path)
    labels = load_labels(labels_path)
    ensure_complete_labels(cases, labels)

    if args.case_ids:
        wanted = set(args.case_ids)
        cases = [
            case
            for case in cases
            if case["case_id"] in wanted
        ]

        found = {case["case_id"] for case in cases}
        missing = wanted - found

        if missing:
            print(
                "❌ 존재하지 않는 case_id: "
                + ", ".join(sorted(missing)),
                file=sys.stderr,
            )
            return 1

    if args.limit is not None:
        if args.limit <= 0:
            print("❌ --limit은 1 이상이어야 합니다.", file=sys.stderr)
            return 1
        cases = cases[:args.limit]

    if not cases:
        print("❌ 평가할 사례가 없습니다.", file=sys.stderr)
        return 1

    print(f"평가 대상: {len(cases)}건")
    print(f"AI 서버: {args.base_url.rstrip('/')}{ANALYZE_PATH}")
    print(
        "평가 모드: Claude 단독 프롬프트 평가 "
        "(ruleResults=[], REPEAT 제외)\n"
    )

    result_rows: list[dict[str, Any]] = []
    case_rows: list[dict[str, Any]] = []

    request_failures = 0
    total_latency_ms = 0.0
    model_names = Counter()

    for index, case in enumerate(cases, start=1):
        case_id = case["case_id"]

        print(
            f"[{index}/{len(cases)}] {case_id} ... ",
            end="",
            flush=True,
        )

        try:
            response, latency_ms = analyze_case(
                base_url=args.base_url,
                complaint=case["message_text"],
                timeout_seconds=args.timeout,
            )

            (
                predicted_states,
                confidences,
                predicted_evidences,
                predicted_reasons,
            ) = parse_predictions(response)

            metadata = response.get("metadata", {})
            model_name = ""

            if isinstance(metadata, dict):
                model_name = clean(str(metadata.get("modelName", "")))

            if model_name:
                model_names[model_name] += 1

            total_latency_ms += latency_ms
            mismatch_count = 0

            for code in BACKEND_CODES:
                gold = labels[case_id][code]
                predicted_state = predicted_states[code]
                is_match = gold["status"] == predicted_state

                evaluation_in_scope = (
                    code in EVALUATED_CODES
                )

                if (
                    evaluation_in_scope
                    and not is_match
                ):
                    mismatch_count += 1

                result_rows.append(
                    {
                        "case_id": case_id,
                        "code": code,
                        "risk_factor": gold["risk_factor"],
                        "gold_state": gold["status"],
                        "predicted_state": predicted_state,
                        "state_match": int(is_match),
                        "evaluation_in_scope": int(
                            evaluation_in_scope
                        ),
                        "gold_evidence": gold.get("evidence_span", ""),
                        "predicted_evidence": " | ".join(
                            predicted_evidences[code]
                        ),
                        "evidence_match": evidence_match(
                            gold.get("evidence_span", ""),
                            predicted_evidences[code],
                        ),
                        "gold_reason": gold.get("reason", ""),
                        "predicted_reason": predicted_reasons[code],
                        "confidence": confidences[code],
                        "review_required": gold.get("review_required", ""),
                        "label_origin": gold.get("label_origin", ""),
                        "history_available": case.get("history_available", ""),
                        "history_context": case.get("history_context", ""),
                        "message_text": case["message_text"],
                        "model_name": model_name,
                        "latency_ms": round(latency_ms, 2),
                        "request_success": 1,
                        "error": "",
                    }
                )

            case_rows.append(
                {
                    "case_id": case_id,
                    "message_text": case["message_text"],
                    "mismatch_count": mismatch_count,
                    "all_evaluated_states_match": int(
                        mismatch_count == 0
                    ),
                    "model_name": model_name,
                    "latency_ms": round(latency_ms, 2),
                    "request_success": 1,
                    "error": "",
                }
            )

            print(
                f"OK ({mismatch_count}/{len(EVALUATED_CODES)} 불일치, "
                f"{latency_ms:.0f}ms)"
            )

        except Exception as exc:
            request_failures += 1
            error_message = str(exc)

            print(f"FAIL: {error_message}")

            case_rows.append(
                {
                    "case_id": case_id,
                    "message_text": case["message_text"],
                    "mismatch_count": "",
                    "all_evaluated_states_match": 0,
                    "model_name": "",
                    "latency_ms": "",
                    "request_success": 0,
                    "error": error_message,
                }
            )

            for code in BACKEND_CODES:
                gold = labels[case_id][code]

                result_rows.append(
                    {
                        "case_id": case_id,
                        "code": code,
                        "risk_factor": gold["risk_factor"],
                        "gold_state": gold["status"],
                        "predicted_state": "",
                        "state_match": 0,
                        "evaluation_in_scope": int(
                            code in EVALUATED_CODES
                        ),
                        "gold_evidence": gold.get("evidence_span", ""),
                        "predicted_evidence": "",
                        "evidence_match": "",
                        "gold_reason": gold.get("reason", ""),
                        "predicted_reason": "",
                        "confidence": "",
                        "review_required": gold.get("review_required", ""),
                        "label_origin": gold.get("label_origin", ""),
                        "history_available": case.get("history_available", ""),
                        "history_context": case.get("history_context", ""),
                        "message_text": case["message_text"],
                        "model_name": "",
                        "latency_ms": "",
                        "request_success": 0,
                        "error": error_message,
                    }
                )

            if args.stop_on_error:
                break

        if index < len(cases) and args.sleep > 0:
            time.sleep(args.sleep)

    successful_rows = [
        row
        for row in result_rows
        if row["request_success"] == 1
    ]

    evaluated_rows = [
        row
        for row in successful_rows
        if row.get("evaluation_in_scope") == 1
    ]

    mismatches = [
        row
        for row in evaluated_rows
        if row["state_match"] == 0
    ]

    metrics = build_tag_metrics(result_rows)

    successful_cases = sum(
        1
        for row in case_rows
        if row["request_success"] == 1
    )

    perfect_cases = sum(
        1
        for row in case_rows
        if row["request_success"] == 1
        and row["all_evaluated_states_match"] == 1
    )

    exact_matches = sum(
        row["state_match"]
        for row in evaluated_rows
    )

    exact_state_accuracy = safe_divide(
        exact_matches,
        len(evaluated_rows),
    )

    macro_present_f1 = safe_divide(
        sum(metric["present_f1"] for metric in metrics),
        len(metrics),
    )

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "evaluation_mode": (
            "claude_prompt_only_rule_results_empty_repeat_excluded"
        ),
        "base_url": args.base_url,
        "cases_requested": len(cases),
        "cases_succeeded": successful_cases,
        "cases_failed": request_failures,
        "evaluated_codes": EVALUATED_CODES,
        "excluded_codes": ["REPEAT"],
        "perfect_evaluated_tag_cases": perfect_cases,
        "perfect_evaluated_tag_case_rate": round(
            safe_divide(perfect_cases, successful_cases),
            4,
        ),
        "total_tag_comparisons": len(evaluated_rows),
        "exact_state_matches": exact_matches,
        "exact_state_accuracy": round(exact_state_accuracy, 4),
        "state_mismatches": len(mismatches),
        "macro_present_f1": round(macro_present_f1, 4),
        "average_latency_ms": round(
            safe_divide(total_latency_ms, successful_cases),
            2,
        ),
        "model_names": dict(model_names),
        "note": (
            "현재 개발 라벨은 AI_DRAFT/AI_PROPOSED 기반 Silver Set입니다. "
            "최종 Gold Set 성능으로 해석하면 안 됩니다. "
            "Rule 결과는 비워 두고 Claude 프롬프트 자체를 평가했습니다. "
            "REPEAT는 이력 의존 태그이므로 Claude 단독 평가 지표와 "
            "mismatch 집계에서 제외했습니다."
        ),
    }

    report_dir.mkdir(parents=True, exist_ok=True)

    write_csv(report_dir / "results.csv", result_rows)
    write_csv(report_dir / "cases.csv", case_rows)
    write_csv(report_dir / "mismatches.csv", mismatches)
    write_csv(report_dir / "tag_metrics.csv", metrics)

    with (report_dir / "summary.json").open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            summary,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print_metrics(metrics)

    print()
    print("========================================")
    print("전체 요약")
    print("========================================")
    print(f"성공 사례: {successful_cases}/{len(cases)}")
    print(
        f"평가 대상 {len(EVALUATED_CODES)}개 태그 전부 일치 사례: "
        f"{perfect_cases}/{successful_cases}"
    )
    print(f"전체 state 정확도: {exact_state_accuracy:.3f}")
    print(f"PRESENT macro F1: {macro_present_f1:.3f}")
    print(f"불일치 라벨 수: {len(mismatches)}")

    if successful_cases:
        print(
            f"평균 응답시간: "
            f"{summary['average_latency_ms']:.0f}ms"
        )

    print()
    print("결과 저장:")
    print(f"- {report_dir / 'summary.json'}")
    print(f"- {report_dir / 'tag_metrics.csv'}")
    print(f"- {report_dir / 'mismatches.csv'}")
    print(f"- {report_dir / 'results.csv'}")
    print(f"- {report_dir / 'cases.csv'}")

    return 0 if request_failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
