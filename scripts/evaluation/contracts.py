"""Prediction/Rule contracts and an allowlisted model request builder for #25."""
from __future__ import annotations

import json
import math
from pathlib import Path

from .data import ALLOWED_STATES, BACKEND_CODES


class ContractError(ValueError):
    pass


def validate_tags(tags, *, complete=True):
    if not isinstance(tags, list):
        raise ContractError("tags_not_list")
    result = {}
    for tag in tags:
        if not isinstance(tag, dict):
            raise ContractError("tag_not_object")
        code, state = tag.get("code"), tag.get("state")
        if not isinstance(code, str) or code not in BACKEND_CODES:
            raise ContractError("invalid_code")
        if not isinstance(state, str) or state not in ALLOWED_STATES:
            raise ContractError("invalid_state")
        if code in result:
            raise ContractError("duplicate_tag")
        spans = tag.get("evidenceSpans", [])
        if not isinstance(spans, list) or any(
            not isinstance(span, dict) or not isinstance(span.get("text"), str)
            or not span["text"].strip() for span in spans
        ):
            raise ContractError("invalid_evidence_spans")
        confidence = tag.get("confidence")
        if confidence is not None and (
            type(confidence) not in (int, float) or not math.isfinite(confidence)
            or not 0 <= confidence <= 1
        ):
            raise ContractError("invalid_confidence")
        result[code] = tag
    if complete and set(result) != set(BACKEND_CODES):
        raise ContractError("missing_tags")
    return result


def prediction_tags(response):
    if not isinstance(response, dict):
        raise ContractError("response_not_object")
    return validate_tags(response.get("tags"))


def parse_predictions(response):
    """Legacy tuple interface, now strict: never invent ABSENT predictions."""
    tags = prediction_tags(response)
    return (
        {code: tag["state"] for code, tag in tags.items()},
        {code: tag.get("confidence") for code, tag in tags.items()},
        {code: [span["text"] for span in tag.get("evidenceSpans", [])] for code, tag in tags.items()},
        {code: tag.get("reason", "") for code, tag in tags.items()},
    )


def build_payload(case, mode="llm", rule_results=None):
    # Never serialize a case dict: golden labels and AI_proposed fields live in it.
    if mode not in ("llm", "rule_llm"):
        raise ValueError("invalid mode")
    if mode == "rule_llm" and rule_results is None:
        raise ValueError("rule_llm requires separately captured Backend rule results")
    rules = [] if mode == "llm" else rule_results
    validate_tags(rules, complete=False)
    allowed = {"code", "state", "confidence", "severity", "repeatCount", "evidenceSpans", "reason"}
    return {"complaint": case["message_text"],
            "ruleResults": [{key: value for key, value in tag.items() if key in allowed} for tag in rules]}


def read_predictions(path):
    path = Path(path)
    if path.suffix == ".jsonl":
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        records = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("predictions must be a JSON list or JSONL records")
    result = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("case_id"), str) or not record["case_id"]:
            raise ValueError("prediction record requires case_id")
        if record["case_id"] in result:
            raise ValueError("duplicate prediction case_id")
        result[record["case_id"]] = record
    return result
