import copy
import json
from pathlib import Path

import pytest

from scripts.validate_operational_logs import check_logs, main, validate_event

SAMPLE = Path(__file__).parent / "fixtures/operational_log_samples.jsonl"
EVENT = json.loads(SAMPLE.read_text().splitlines()[0])
SECRET = "RAW_BODY_sk-SECRET_CANARY"


def test_synthetic_success_timeout_and_error_samples_are_valid():
    result = check_logs(SAMPLE)
    assert result["status"] == "passed"
    assert result["valid_events"] == 3
    assert result["invalid_lines"] == 0


@pytest.mark.parametrize("key,value", [
    ("request_id", SECRET), ("endpoint", "/api/v1/ai/analyze?token=" + SECRET),
    ("model_name", SECRET), ("prompt_version", SECRET), ("error_code", SECRET),
    ("latency_ms", SECRET), ("latency_ms", float("nan")), ("latency_ms", float("inf")),
    ("latency_ms", True), ("success", SECRET), ("success", False),
    ("complaint", SECRET), ("metadata", {"api_key": SECRET}),
])
def test_untrusted_or_inconsistent_fields_fail_without_echoing_values(tmp_path, key, value, capsys):
    event = copy.deepcopy(EVENT)
    event[key] = value
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps(event) + "\n")
    result = check_logs(path)
    assert result["status"] == "failed"
    assert result["invalid_lines"] == 1
    assert SECRET not in json.dumps(result)
    assert main(["--input", str(path)]) == 1
    captured = capsys.readouterr()
    assert SECRET not in captured.out + captured.err


def test_duplicate_keys_invalid_json_and_oversize_lines_are_rejected(tmp_path):
    duplicate = json.dumps(EVENT).replace('"success": true', '"success": "' + SECRET + '", "success": true')
    path = tmp_path / "events.jsonl"
    path.write_text(duplicate + '\n' + SECRET + '\n' + 'x' * 70_000 + '\n' + json.dumps(EVENT) + '\n')
    result = check_logs(path)
    assert result["valid_events"] == 1
    assert result["invalid_lines"] == 3
    assert [error["line"] for error in result["errors"]] == [1, 2, 3]
    assert SECRET not in json.dumps(result)


def test_empty_and_missing_files_do_not_claim_log_verification(tmp_path, capsys):
    path = tmp_path / "empty.jsonl"
    path.touch()
    assert check_logs(path)["status"] == "failed"
    assert check_logs(path)["empty"] is True
    assert main(["--input", str(tmp_path / SECRET)]) == 2
    assert SECRET not in capsys.readouterr().err


def test_typed_fields_and_error_listing_remain_bounded(tmp_path):
    assert validate_event({**EVENT, "endpoint": []}) == "invalid_field_type"
    assert validate_event([]) == "invalid_fields"
    path = tmp_path / "events.jsonl"
    path.write_text((SECRET + '\n') * 105)
    result = check_logs(path)
    assert result["invalid_lines"] == 105
    assert len(result["errors"]) == 100
    assert result["errors_truncated"] is True
