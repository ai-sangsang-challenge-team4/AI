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
