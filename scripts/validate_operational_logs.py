#!/usr/bin/env python3
"""Validate the operational log allowlist without echoing unsafe lines (#33)."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.errors import ErrorCode
from app.core.operational_logging import ENDPOINTS, FIELDS, MODELS


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def validate_event(event):
    if not isinstance(event, dict) or set(event) != set(FIELDS):
        return "invalid_fields"
    strings = ("request_id", "endpoint", "model_name", "prompt_version", "error_code")
    if any(not isinstance(event[key], str) for key in strings):
        return "invalid_field_type"
    if not re.fullmatch(r"[0-9a-f]{32}", event["request_id"]):
        return "invalid_request_id"
    if event["endpoint"] not in ENDPOINTS | {"unmatched"}:
        return "invalid_endpoint"
    if event["model_name"] not in MODELS:
        return "invalid_model"
    if event["prompt_version"] != "unknown" and not re.fullmatch(r"sha256:[0-9a-f]{64}", event["prompt_version"]):
        return "invalid_prompt_version"
    latency = event["latency_ms"]
    if type(latency) not in (int, float) or not 0 <= latency < float("inf"):
        return "invalid_latency"
    if type(event["success"]) is not bool or event["error_code"] not in {code.value for code in ErrorCode}:
        return "invalid_outcome"
    if event["success"] != (event["error_code"] == ErrorCode.OK.value):
        return "inconsistent_outcome"
    return None


def check_logs(path):
    valid, invalid, errors, lines = 0, 0, [], 0
    digest, checked_bytes = hashlib.sha256(), 0
    with Path(path).open("rb") as stream:
        while raw := stream.readline(65_537):
            digest.update(raw)
            checked_bytes += len(raw)
            lines += 1
            error = None
            if len(raw) > 65_536:
                error = "line_too_large"
                while raw and not raw.endswith(b"\n"):
                    raw = stream.readline(65_537)
                    digest.update(raw)
                    checked_bytes += len(raw)
            else:
                try:
                    event = json.loads(raw, object_pairs_hook=unique_object)
                    error = validate_event(event)
                except (ValueError, UnicodeError, RecursionError):
                    error = "invalid_json"
            if error:
                invalid += 1
                if len(errors) < 100:
                    errors.append({"line": lines, "error_code": error})
            else:
                valid += 1
    return {"status": "passed" if valid and not invalid else "failed", "valid_events": valid,
            "invalid_lines": invalid, "empty": lines == 0, "errors": errors,
            "errors_truncated": invalid > len(errors), "contains_raw_log_lines": False,
            "checked_sha256": digest.hexdigest(), "checked_bytes": checked_bytes,
            "input_scope": "bytes_read_until_eof; subsequent_appends_not_checked"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = check_logs(args.input)
    except OSError:
        print("LOG_INPUT_ERROR", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return int(result["status"] != "passed")


if __name__ == "__main__":
    sys.exit(main())
