#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


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

ALLOWED_STATUSES = {
    "PRESENT",
    "ABSENT",
    "BOUNDARY",
    "UNKNOWN",
}

ALLOWED_YES_NO = {
    "YES",
    "NO",
}

ALLOWED_RULE_MATCH_TYPES = {
    "KEYWORD",
    "PHRASE",
    "REGEX",
}

EXPECTED_CASE_COUNT = 100
EXPECTED_RISK_FACTOR_COUNT = 8
EXPECTED_LABEL_COUNT = EXPECTED_CASE_COUNT * EXPECTED_RISK_FACTOR_COUNT

CASE_REQUIRED_COLUMNS = {
    "case_id",
    "message_text",
    "history_context",
    "history_available",
    "same_topic_count_7d",
    "prior_teacher_responses",
    "prior_resolution_status",
    "days_since_first_contact",
    "regulation_context",
    "domain",
    "sender_role",
    "receiver_role",
    "source_type",
    "communication_intent",
    "primary_topic",
    "secondary_topics",
    "boundary_case",
    "obfuscation_type",
    "pii_present",
    "student_safety_signal",
    "generation_bucket",
    "review_status",
}

LABEL_REQUIRED_COLUMNS = {
    "case_id",
    "risk_factor",
    "status",
    "evidence_span",
    "reason",
    "context_subtype",
    "history_required",
    "review_required",
    "label_origin",
}

RULE_REQUIRED_COLUMNS = {
    "rule_id",
    "risk_factor",
    "match_type",
    "pattern",
    "detection_role",
    "context_required",
    "exclusion_conditions",
    "positive_case_ids",
    "negative_contrast_case_ids",
    "weight_proposal",
    "review_status",
}


@dataclass
class ValidationMessage:
    level: str
    message: str


class ValidationReport:
    def __init__(self) -> None:
        self.messages: list[ValidationMessage] = []

    def error(self, message: str) -> None:
        self.messages.append(ValidationMessage("ERROR", message))

    def warn(self, message: str) -> None:
        self.messages.append(ValidationMessage("WARN", message))

    def info(self, message: str) -> None:
        self.messages.append(ValidationMessage("INFO", message))

    @property
    def errors(self) -> list[ValidationMessage]:
        return [item for item in self.messages if item.level == "ERROR"]

    @property
    def warnings(self) -> list[ValidationMessage]:
        return [item for item in self.messages if item.level == "WARN"]

    def print(self) -> None:
        for item in self.messages:
            prefix = {
                "ERROR": "❌",
                "WARN": "⚠️ ",
                "INFO": "✅",
            }[item.level]
            print(f"{prefix} {item.message}")

        print()
        print("========================================")
        print("검증 결과")
        print("========================================")
        print(f"ERROR: {len(self.errors)}")
        print(f"WARN : {len(self.warnings)}")

        if not self.errors:
            print("RESULT: PASS")
        else:
            print("RESULT: FAIL")


def clean(value: str | None) -> str:
    return (value or "").strip()


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        reader = csv.DictReader(file)
        headers = reader.fieldnames or []

        rows = []
        for raw_row in reader:
            rows.append(
                {
                    key: clean(value)
                    for key, value in raw_row.items()
                    if key is not None
                }
            )

        return headers, rows


def check_required_columns(
    report: ValidationReport,
    file_name: str,
    headers: list[str],
    required: set[str],
) -> None:
    missing = sorted(required - set(headers))

    if missing:
        report.error(
            f"{file_name}: 필수 컬럼 누락 -> {', '.join(missing)}"
        )
    else:
        report.info(
            f"{file_name}: 필수 컬럼 확인 완료"
        )


def split_case_ids(value: str) -> list[str]:
    if not value:
        return []

    return [
        item.strip()
        for item in re.split(r"[;,]", value)
        if item.strip()
    ]


def validate_cases(
    report: ValidationReport,
    rows: list[dict[str, str]],
) -> dict[str, dict[str, str]]:

    case_ids = [
        row.get("case_id", "")
        for row in rows
    ]

    if len(rows) != EXPECTED_CASE_COUNT:
        report.warn(
            "cases: 예상 사례 수 "
            f"{EXPECTED_CASE_COUNT}건과 다름 -> {len(rows)}건"
        )
    else:
        report.info(
            f"cases: 사례 수 {EXPECTED_CASE_COUNT}건 확인"
        )

    duplicates = [
        case_id
        for case_id, count in Counter(case_ids).items()
        if case_id and count > 1
    ]

    if duplicates:
        report.error(
            "cases: 중복 case_id -> "
            + ", ".join(sorted(duplicates))
        )

    blank_case_ids = [
        index + 2
        for index, row in enumerate(rows)
        if not row.get("case_id")
    ]

    if blank_case_ids:
        report.error(
            "cases: case_id 누락 행 -> "
            + ", ".join(map(str, blank_case_ids))
        )

    blank_messages = [
        row.get("case_id") or f"row:{index + 2}"
        for index, row in enumerate(rows)
        if not row.get("message_text")
    ]

    if blank_messages:
        report.error(
            "cases: message_text 누락 -> "
            + ", ".join(blank_messages)
        )

    for field in [
        "history_available",
        "boundary_case",
        "pii_present",
    ]:
        invalid = [
            f"{row.get('case_id')}={row.get(field)}"
            for row in rows
            if row.get(field)
            and row.get(field) not in ALLOWED_YES_NO
        ]

        if invalid:
            report.error(
                f"cases: {field} 허용되지 않은 값 -> "
                + ", ".join(invalid)
            )

    draft_count = sum(
        1
        for row in rows
        if row.get("review_status") == "AI_DRAFT"
    )

    if draft_count:
        report.warn(
            f"cases: review_status=AI_DRAFT {draft_count}건 "
            "(Gold Label 확정 전 개발용 데이터)"
        )

    return {
        row["case_id"]: row
        for row in rows
        if row.get("case_id")
    }


def validate_labels(
    report: ValidationReport,
    rows: list[dict[str, str]],
    cases_by_id: dict[str, dict[str, str]],
) -> None:

    if len(rows) != EXPECTED_LABEL_COUNT:
        report.warn(
            "labels: 예상 행 수 "
            f"{EXPECTED_LABEL_COUNT}행과 다름 -> {len(rows)}행"
        )
    else:
        report.info(
            f"labels: {EXPECTED_LABEL_COUNT}행 확인"
        )

    unknown_case_ids = sorted(
        {
            row.get("case_id", "")
            for row in rows
            if row.get("case_id")
            and row.get("case_id") not in cases_by_id
        }
    )

    if unknown_case_ids:
        report.error(
            "labels: cases 파일에 없는 case_id -> "
            + ", ".join(unknown_case_ids)
        )
    else:
        report.info(
            "labels: 모든 case_id가 cases 파일과 연결됨"
        )

    allowed_risk_factors = set(
        RISK_FACTOR_TO_BACKEND.keys()
    )

    invalid_risk_factors = sorted(
        {
            row.get("risk_factor", "")
            for row in rows
            if row.get("risk_factor")
            and row.get("risk_factor")
            not in allowed_risk_factors
        }
    )

    if invalid_risk_factors:
        report.error(
            "labels: 허용되지 않은 risk_factor -> "
            + ", ".join(invalid_risk_factors)
        )

    invalid_statuses = sorted(
        {
            row.get("status", "")
            for row in rows
            if row.get("status")
            and row.get("status")
            not in ALLOWED_STATUSES
        }
    )

    if invalid_statuses:
        report.error(
            "labels: 허용되지 않은 status -> "
            + ", ".join(invalid_statuses)
        )

    duplicate_pairs = [
        pair
        for pair, count in Counter(
            (
                row.get("case_id", ""),
                row.get("risk_factor", ""),
            )
            for row in rows
        ).items()
        if count > 1
    ]

    if duplicate_pairs:
        report.error(
            "labels: 중복 case_id/risk_factor 조합 -> "
            + ", ".join(
                f"{case_id}:{risk_factor}"
                for case_id, risk_factor in duplicate_pairs
            )
        )
    else:
        report.info(
            "labels: case_id/risk_factor 중복 없음"
        )

    factors_by_case: dict[str, set[str]] = defaultdict(set)

    for row in rows:
        case_id = row.get("case_id", "")
        risk_factor = row.get("risk_factor", "")

        if case_id and risk_factor:
            factors_by_case[case_id].add(risk_factor)

    incomplete_cases = []

    for case_id in cases_by_id:
        factors = factors_by_case.get(case_id, set())

        if factors != allowed_risk_factors:
            missing = sorted(
                allowed_risk_factors - factors
            )
            extra = sorted(
                factors - allowed_risk_factors
            )

            incomplete_cases.append(
                (
                    case_id,
                    missing,
                    extra,
                )
            )

    if incomplete_cases:
        for case_id, missing, extra in incomplete_cases:
            detail = []

            if missing:
                detail.append(
                    "missing="
                    + ",".join(missing)
                )

            if extra:
                detail.append(
                    "extra="
                    + ",".join(extra)
                )

            report.error(
                f"labels: {case_id} 위험요소 8종 불완전 -> "
                + " / ".join(detail)
            )
    else:
        report.info(
            "labels: 모든 사례에 위험요소 8종이 정확히 존재"
        )

    evidence_mismatches = []

    for row in rows:
        case_id = row.get("case_id", "")
        evidence = row.get("evidence_span", "")

        if not evidence:
            continue

        case = cases_by_id.get(case_id)

        if not case:
            continue

        message = case.get(
            "message_text",
            "",
        )

        if evidence not in message:
            evidence_mismatches.append(
                (
                    case_id,
                    row.get("risk_factor", ""),
                    evidence,
                )
            )

    if evidence_mismatches:
        for case_id, risk_factor, evidence in evidence_mismatches:
            report.error(
                "labels: evidence_span이 원문에 존재하지 않음 -> "
                f"{case_id} / {risk_factor} / {evidence!r}"
            )
    else:
        report.info(
            "labels: 모든 evidence_span이 해당 민원 원문에 존재"
        )

    invalid_history_required = [
        f"{row.get('case_id')}:{row.get('risk_factor')}="
        f"{row.get('history_required')}"
        for row in rows
        if row.get("history_required")
        and row.get("history_required")
        not in ALLOWED_YES_NO
    ]

    if invalid_history_required:
        report.error(
            "labels: history_required 허용되지 않은 값 -> "
            + ", ".join(invalid_history_required)
        )

    invalid_review_required = [
        f"{row.get('case_id')}:{row.get('risk_factor')}="
        f"{row.get('review_required')}"
        for row in rows
        if row.get("review_required")
        and row.get("review_required")
        not in ALLOWED_YES_NO
    ]

    if invalid_review_required:
        report.error(
            "labels: review_required 허용되지 않은 값 -> "
            + ", ".join(invalid_review_required)
        )

    review_required_count = sum(
        1
        for row in rows
        if row.get("review_required") == "YES"
    )

    report.warn(
        f"labels: 사람 교차 검토 필요(review_required=YES) "
        f"{review_required_count}행"
    )

    label_origins = Counter(
        row.get("label_origin", "")
        for row in rows
    )

    if label_origins.get("AI_PROPOSED"):
        report.warn(
            "labels: label_origin=AI_PROPOSED "
            f"{label_origins['AI_PROPOSED']}행 "
            "(정답셋으로 사용 전 사람 검토 필요)"
        )

    print()
    print("위험요소 매핑")
    print("----------------------------------------")
    for source, backend in RISK_FACTOR_TO_BACKEND.items():
        print(f"{source:<32} -> {backend}")

    print()
    print("라벨 상태 분포")
    print("----------------------------------------")

    status_by_factor: dict[str, Counter[str]] = defaultdict(Counter)

    for row in rows:
        status_by_factor[
            row.get("risk_factor", "")
        ][
            row.get("status", "")
        ] += 1

    for risk_factor in RISK_FACTOR_TO_BACKEND:
        counter = status_by_factor[risk_factor]

        values = " ".join(
            f"{status}={counter.get(status, 0)}"
            for status in [
                "PRESENT",
                "BOUNDARY",
                "ABSENT",
                "UNKNOWN",
            ]
        )

        print(
            f"{risk_factor:<32} {values}"
        )


def validate_rules(
    report: ValidationReport,
    rows: list[dict[str, str]],
    cases_by_id: dict[str, dict[str, str]],
) -> None:

    rule_ids = [
        row.get("rule_id", "")
        for row in rows
    ]

    duplicate_rule_ids = [
        rule_id
        for rule_id, count in Counter(rule_ids).items()
        if rule_id and count > 1
    ]

    if duplicate_rule_ids:
        report.error(
            "rules: 중복 rule_id -> "
            + ", ".join(duplicate_rule_ids)
        )
    else:
        report.info(
            f"rules: Rule 후보 {len(rows)}건, rule_id 중복 없음"
        )

    allowed_risk_factors = set(
        RISK_FACTOR_TO_BACKEND.keys()
    )

    invalid_risk_factors = sorted(
        {
            row.get("risk_factor", "")
            for row in rows
            if row.get("risk_factor")
            and row.get("risk_factor")
            not in allowed_risk_factors
        }
    )

    if invalid_risk_factors:
        report.error(
            "rules: 허용되지 않은 risk_factor -> "
            + ", ".join(invalid_risk_factors)
        )

    invalid_match_types = sorted(
        {
            row.get("match_type", "")
            for row in rows
            if row.get("match_type")
            and row.get("match_type")
            not in ALLOWED_RULE_MATCH_TYPES
        }
    )

    if invalid_match_types:
        report.error(
            "rules: 허용되지 않은 match_type -> "
            + ", ".join(invalid_match_types)
        )

    invalid_case_refs = []

    for row in rows:
        for field in [
            "positive_case_ids",
            "negative_contrast_case_ids",
        ]:
            for case_id in split_case_ids(
                row.get(field, "")
            ):
                if case_id not in cases_by_id:
                    invalid_case_refs.append(
                        (
                            row.get("rule_id", ""),
                            field,
                            case_id,
                        )
                    )

    if invalid_case_refs:
        for rule_id, field, case_id in invalid_case_refs:
            report.error(
                f"rules: 존재하지 않는 case_id 참조 -> "
                f"{rule_id} / {field} / {case_id}"
            )
    else:
        report.info(
            "rules: 모든 positive/negative case_id 참조 정상"
        )

    invalid_regex = []

    for row in rows:
        if row.get("match_type") != "REGEX":
            continue

        try:
            re.compile(
                row.get("pattern", "")
            )
        except re.error as exc:
            invalid_regex.append(
                (
                    row.get("rule_id", ""),
                    str(exc),
                )
            )

    if invalid_regex:
        for rule_id, error in invalid_regex:
            report.error(
                f"rules: REGEX 컴파일 실패 -> "
                f"{rule_id} / {error}"
            )
    else:
        report.info(
            "rules: REGEX 후보 문법 검사 통과"
        )

    proposed_count = sum(
        1
        for row in rows
        if row.get("review_status") == "AI_PROPOSED"
    )

    if proposed_count:
        report.warn(
            f"rules: review_status=AI_PROPOSED "
            f"{proposed_count}건 "
            "(Backend Rule 확정본 아님)"
        )


def main() -> int:

    parser = argparse.ArgumentParser(
        description=(
            "TeacherCare 개발용 위험 분석 데이터셋의 "
            "구조와 참조 무결성을 검증합니다."
        )
    )

    parser.add_argument(
        "--data-dir",
        default="data/dev",
        help="개발용 CSV 폴더 경로 (기본값: data/dev)",
    )

    args = parser.parse_args()

    data_dir = Path(
        args.data_dir
    )

    cases_path = (
        data_dir
        / "teachercare_dev_cases_100.csv"
    )

    labels_path = (
        data_dir
        / "teachercare_dev_risk_labels_100.csv"
    )

    rules_path = (
        data_dir
        / "teachercare_dev_rule_candidates.csv"
    )

    report = ValidationReport()

    for path in [
        cases_path,
        labels_path,
        rules_path,
    ]:
        if not path.exists():
            report.error(
                f"파일을 찾을 수 없음: {path}"
            )

    if report.errors:
        report.print()
        return 1

    case_headers, case_rows = read_csv(
        cases_path
    )

    label_headers, label_rows = read_csv(
        labels_path
    )

    rule_headers, rule_rows = read_csv(
        rules_path
    )

    check_required_columns(
        report,
        cases_path.name,
        case_headers,
        CASE_REQUIRED_COLUMNS,
    )

    check_required_columns(
        report,
        labels_path.name,
        label_headers,
        LABEL_REQUIRED_COLUMNS,
    )

    check_required_columns(
        report,
        rules_path.name,
        rule_headers,
        RULE_REQUIRED_COLUMNS,
    )

    if report.errors:
        report.print()
        return 1

    cases_by_id = validate_cases(
        report,
        case_rows,
    )

    validate_labels(
        report,
        label_rows,
        cases_by_id,
    )

    validate_rules(
        report,
        rule_rows,
        cases_by_id,
    )

    print()
    report.print()

    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
