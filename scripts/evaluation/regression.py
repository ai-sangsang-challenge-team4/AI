"""Partial state invariants for development cases; never a model-quality oracle."""
from __future__ import annotations

import json
from pathlib import Path

from .contracts import prediction_tags
from .data import ALLOWED_STATES, BACKEND_CODES, load_dataset


def load_core_suite(path, dev_dir):
    suite = json.loads(Path(path).read_text(encoding="utf-8"))
    dataset = load_dataset(dev_dir, "dev")
    if suite["source_sha256"] != dataset.hashes:
        raise ValueError("core20: development data changed; review expectations before rebasing")
    cases = suite["cases"]
    ids = [case["case_id"] for case in cases]
    if len(cases) != 20 or len(set(ids)) != 20:
        raise ValueError("core20: exactly 20 unique development case IDs required")
    dev_by_id = {case["case_id"]: case for case in dataset.cases}
    categories = set()
    for case in cases:
        case_id = case["case_id"]
        if case_id not in dev_by_id or not case["selection_reason"] or not case["conditions"]:
            raise ValueError("core20: unknown development ID or missing selection rationale")
        categories.update(case["categories"])
        for condition in case["conditions"]:
            code = condition["code"]
            if code not in BACKEND_CODES or code == "REPEAT":
                raise ValueError("core20: invalid or history-dependent condition")
            if not condition["allowed_states"] or set(condition["allowed_states"]) - ALLOWED_STATES:
                raise ValueError("core20: invalid allowed states")
            source = dataset.labels[case_id][code]
            if source["status"] != condition["source_state"]:
                raise ValueError(f"{case_id}/{code}: source label drift")
            if condition["source_review_required"] != (source.get("review_required") == "YES"):
                raise ValueError(f"{case_id}/{code}: source review flag drift")
            if condition["source_label_origin"] != source.get("label_origin"):
                raise ValueError(f"{case_id}/{code}: label origin drift")
            if not condition["basis"] or condition["human_review_status"] != "pending":
                raise ValueError("core20: expectation basis/review status missing")
    if not {"threat", "urgent_response", "legitimate", "boundary", "obfuscation"} <= categories:
        raise ValueError("core20: required scenario coverage missing")
    return suite, dataset


def assert_conditions(case_spec, response):
    case_id = case_spec["case_id"]
    try:
        tags = prediction_tags(response)
    except ValueError:
        raise AssertionError(f"{case_id}: prediction_contract_failed") from None
    failures = []
    for condition in case_spec["conditions"]:
        actual = tags[condition["code"]]["state"]
        allowed = condition["allowed_states"]
        if actual not in allowed:
            failures.append(f"{condition['code']} expected={'|'.join(allowed)} actual={actual}")
    if failures:
        raise AssertionError(f"{case_id}: " + "; ".join(failures))


def assess_records(suite, records):
    """Check saved inference against partial dev invariants, never synthetic gold."""
    failures, passed = [], []
    conditions_checked = 0
    for spec in suite["cases"]:
        case_id = spec["case_id"]
        record = records.get(case_id)
        error = ""
        if record is None:
            error = "missing_prediction"
        elif record.get("request_success") != 1:
            error = "request_failed"
        elif record.get("source_provenance_verified") is not True:
            error = "input_provenance_unverified"
        if not error:
            try:
                tags = prediction_tags(record.get("response"))
            except ValueError:
                error = "prediction_contract_failed"
        if error:
            failures.append({"case_id": case_id, "code": "", "expected": "", "actual": "", "error_code": error})
            continue
        wrong = []
        for condition in spec["conditions"]:
            conditions_checked += 1
            code = condition["code"]
            state = tags[code]["state"]
            if state not in condition["allowed_states"]:
                wrong.append({"case_id": case_id, "code": code,
                              "expected": "|".join(condition["allowed_states"]), "actual": state,
                              "error_code": "condition_mismatch"})
        failures.extend(wrong)
        if not wrong:
            passed.append(case_id)
    failed_ids = sorted({row["case_id"] for row in failures})
    return {"status": "passed" if not failures else "failed", "requested_cases": len(suite["cases"]),
            "passed_cases": len(passed), "failed_cases": len(failed_ids), "failed_case_ids": failed_ids,
            "conditions_checked": conditions_checked, "failures": failures,
            "expectations": "AI_PROPOSED_partial_conditions_pending_human_review",
            "provenance_check": "recorded_input_hashes_match; not_authentication_of_model_execution"}
