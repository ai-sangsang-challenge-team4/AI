import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from scripts import run_regression
from scripts.evaluation.contracts import build_payload
from scripts.evaluation.data import json_hash
from scripts.evaluation.regression import assess_records, load_core_suite
from tests.offline_support import risk_output

ROOT = Path(__file__).parents[1]
SUITE, DATASET = load_core_suite(ROOT / "tests/fixtures/regression_core20.json", ROOT / "data/dev")
CASES = {case["case_id"]: case for case in DATASET.cases}
MOCK = json.loads((ROOT / "tests/fixtures/regression_mock_outputs.json").read_text())["cases"]
SECRET = "RAW_MODEL_sk-SECRET_CANARY"


def predictions():
    # Synthetic transport data tests this runner; these are never model-quality results.
    return {spec["case_id"]: {"case_id": spec["case_id"], "mode": "llm", "request_success": 1,
                             "source_provenance_verified": True,
                             "input_sha256": json_hash(build_payload(CASES[spec["case_id"]])),
                             "complaint_sha256": json_hash(CASES[spec["case_id"]]["message_text"]),
                             "response": risk_output(MOCK[spec["case_id"]]["states"], MOCK[spec["case_id"]]["evidence"])}
            for spec in SUITE["cases"]}


def fake_offline(directory):
    return {"status": "passed", "pytest_exit_code": 0,
            "core20": run_regression.counts({"passed": 20}),
            "guardrails": run_regression.counts({"passed": 40, "xfailed": 3}),
            "operational_logs": run_regression.counts({"passed": 20}), "failed_case_ids": []}


def saved_input(tmp_path, records):
    path = tmp_path / "predictions.json"
    path.write_text(json.dumps(list(records.values()), ensure_ascii=False))
    return path


def summary(tmp_path):
    return json.loads(next((tmp_path / "reports").glob("*/summary.json")).read_text())


def test_real_state_changes_missing_requests_and_unverified_inputs_fail_partial_conditions():
    records = predictions()
    assert assess_records(SUITE, records)["conditions_checked"] == 33
    assert assess_records(SUITE, records)["passed_cases"] == 20
    wrong = next(row for row in records["DEV003"]["response"]["tags"] if row["code"] == "THREAT")
    wrong["state"] = "ABSENT"
    del records["DEV002"]
    records["DEV005"]["request_success"] = 0
    records["DEV007"]["source_provenance_verified"] = False
    records["DEV008"]["response"]["tags"] = []
    result = assess_records(SUITE, records)
    assert result["failed_case_ids"] == ["DEV002", "DEV003", "DEV005", "DEV007", "DEV008"]
    assert {row["error_code"] for row in result["failures"]} == {
        "condition_mismatch", "missing_prediction", "request_failed", "input_provenance_unverified", "prediction_contract_failed"}


def test_single_command_runs_core20_guardrails_and_safe_logging_without_model_calls(tmp_path, capsys):
    status = run_regression.main(["--report-dir", str(tmp_path / "reports"),
                                  "--log-file", str(ROOT / "tests/fixtures/operational_log_samples.jsonl")])
    assert status == 0
    result = summary(tmp_path)
    assert result["offline"]["core20"]["passed"] == 20
    assert result["offline"]["guardrails"]["passed"] > 0
    assert result["pending_guardrails"] == 3
    assert result["guardrails_complete"] is False
    assert result["model_regression"]["status"] == "not_run"
    assert result["log_validation"]["valid_events"] == 3
    assert result["human_expectation_review_complete"] is False
    aggregate = json.loads(next((tmp_path / "reports").glob("*/offline_aggregate.json")).read_text())
    assert "DEV" not in json.dumps(aggregate)
    assert "pending guardrails=3" in capsys.readouterr().out


def test_saved_inference_detects_regression_and_prints_only_case_id_and_safe_reason(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(run_regression, "run_offline", fake_offline)
    records = predictions()
    records["DEV003"]["response"] = risk_output({"THREAT": "ABSENT"})
    records["DEV003"]["response"]["tags"][0]["reason"] = SECRET
    path = saved_input(tmp_path, records)
    assert run_regression.main(["--predictions", str(path), "--report-dir", str(tmp_path / "reports")]) == 1
    result = summary(tmp_path)
    assert result["model_regression"]["failed_case_ids"] == ["DEV003"]
    assert result["model_regression"]["passed_cases"] == 19
    output = capsys.readouterr().out
    assert "DEV003: THREAT expected=PRESENT actual=ABSENT" in output
    assert SECRET not in output + json.dumps(result)


@pytest.mark.parametrize("change", ["missing", "wrong_hash", "unverified", "request_failed"])
def test_saved_response_cannot_hide_missing_or_unbound_inference(tmp_path, monkeypatch, change):
    monkeypatch.setattr(run_regression, "run_offline", fake_offline)
    records = predictions()
    if change == "missing":
        del records["DEV003"]
    elif change == "wrong_hash":
        records["DEV003"]["input_sha256"] = "0" * 64
    elif change == "unverified":
        records["DEV003"]["source_provenance_verified"] = False
    else:
        records["DEV003"].update(request_success=0, error_code=SECRET)
    path = saved_input(tmp_path, records)
    assert run_regression.main(["--predictions", str(path), "--report-dir", str(tmp_path / "reports")]) == 1
    assert summary(tmp_path)["model_regression"]["failed_case_ids"] == ["DEV003"]
    assert SECRET not in json.dumps(summary(tmp_path))


@pytest.mark.parametrize("strict,offline_failed", [(True, False), (False, True)])
def test_failing_offline_gate_prevents_paid_inference(tmp_path, monkeypatch, strict, offline_failed):
    calls = []
    def offline(directory):
        result = fake_offline(directory)
        if offline_failed:
            result["status"] = "failed"
            result["failed_case_ids"] = ["DEV003"]
        return result
    monkeypatch.setattr(run_regression, "run_offline", offline)
    monkeypatch.setattr(run_regression, "evaluate", lambda options: calls.append(options))
    command = ["--base-url", "https://ai.invalid", "--report-dir", str(tmp_path / "reports")]
    if strict:
        command.append("--require-complete-guardrails")
    assert run_regression.main(command) == 1
    assert calls == []
    assert summary(tmp_path)["model_regression"]["status"] == "not_run"


def test_live_transport_captures_only_the_selected_development_inputs(tmp_path, monkeypatch):
    monkeypatch.setattr(run_regression, "run_offline", fake_offline)
    records = predictions()
    by_text = {CASES[cid]["message_text"]: record["response"] for cid, record in records.items()}
    calls = []
    def transport(url, payload, timeout):
        assert url == "https://ai.invalid/api/v1/ai/analyze"
        assert set(payload) == {"complaint", "ruleResults"}
        assert payload["ruleResults"] == []
        calls.append(payload)
        return copy.deepcopy(by_text[payload["complaint"]])
    monkeypatch.setattr("scripts.evaluation.runner.post_json", transport)
    assert run_regression.main(["--base-url", "https://ai.invalid", "--sleep", "0",
                                "--report-dir", str(tmp_path / "reports")]) == 0
    result = summary(tmp_path)
    assert len(calls) == 20
    assert result["model_regression"]["passed_cases"] == 20
    assert result["model_regression"]["execution"] == "http"
    assert len(next((tmp_path / "reports").glob("*/inference_checkpoint.jsonl")).read_text().splitlines()) == 20


def test_live_request_failure_stops_further_calls_and_preserves_completed_checkpoint(tmp_path, monkeypatch):
    from scripts.evaluation.runner import RequestFailure
    monkeypatch.setattr(run_regression, "run_offline", fake_offline)
    calls = []
    def unavailable(*args):
        calls.append(args)
        raise RequestFailure("connection_or_timeout")
    monkeypatch.setattr("scripts.evaluation.runner.post_json", unavailable)
    assert run_regression.main(["--base-url", "https://ai.invalid", "--sleep", "0",
                                "--report-dir", str(tmp_path / "reports")]) == 1
    assert len(calls) == 1
    result = summary(tmp_path)
    assert result["model_regression"]["failed_cases"] == 20
    assert len(next((tmp_path / "reports").glob("*/inference_checkpoint.jsonl")).read_text().splitlines()) == 1


@pytest.mark.parametrize("core_passed,exit_code", [(0, 0), (19, 1)])
def test_offline_child_output_is_not_republished_and_missing_core_tests_cannot_pass(tmp_path, monkeypatch, core_passed, exit_code):
    def child(command, **kwargs):
        destination = Path(command[command.index("--aggregate-report") + 1])
        destination.write_text(json.dumps({"core20": {"passed": core_passed}, "tests": {"failed": exit_code},
                                           "groups": {"guardrails": {"passed": 40}, "operational_logs": {"passed": 20}}}))
        return subprocess.CompletedProcess(command, exit_code, "CORE20_FAILED: DEV003\n" + SECRET, SECRET)
    monkeypatch.setattr(run_regression.subprocess, "run", child)
    result = run_regression.run_offline(tmp_path)
    assert result["status"] == "failed"
    assert result["failed_case_ids"] == ["DEV003"]
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize("url", ["", "   "])
def test_empty_explicit_live_origin_cannot_silently_become_offline_success(tmp_path, monkeypatch, url):
    calls = []
    monkeypatch.setattr(run_regression, "run_offline", lambda directory: calls.append(directory))
    assert run_regression.main(["--base-url", url, "--report-dir", str(tmp_path / "reports")]) == 2
    assert calls == []
    assert not (tmp_path / "reports").exists()


def test_saved_rule_llm_uses_actual_rule_payload_hashes(tmp_path, monkeypatch):
    monkeypatch.setattr(run_regression, "run_offline", fake_offline)
    records = predictions()
    rules = {cid: [{"code": "THREAT", "state": "BOUNDARY", "confidence": .2, "reason": "synthetic",
                    "gold_answer": SECRET}] for cid in records}
    for cid, record in records.items():
        record["mode"] = "rule_llm"
        record["input_sha256"] = json_hash(build_payload(CASES[cid], "rule_llm", rules[cid]))
    path = saved_input(tmp_path, records)
    rule_path = tmp_path / "rules.json"
    rule_path.write_text(json.dumps(rules))
    assert run_regression.main(["--predictions", str(path), "--mode", "rule_llm", "--rule-results", str(rule_path),
                                "--report-dir", str(tmp_path / "reports")]) == 0
    result = summary(tmp_path)
    assert result["model_regression"]["passed_cases"] == 20
    output = next((tmp_path / "reports").glob("*/tagging/*/predictions.jsonl"))
    for line in output.read_text().splitlines():
        assert SECRET not in json.dumps(json.loads(line)["risk_input"])


@pytest.mark.parametrize("bad_rule", ["missing_file", "missing_case", "bad_shape"])
def test_invalid_rule_input_is_rejected_before_tests_or_paid_requests(tmp_path, monkeypatch, bad_rule):
    calls = []
    monkeypatch.setattr(run_regression, "run_offline", lambda directory: calls.append(directory))
    command = ["--base-url", "https://ai.invalid", "--mode", "rule_llm", "--report-dir", str(tmp_path / "reports")]
    if bad_rule != "missing_file":
        rule_path = tmp_path / "rules.json"
        rules = {cid: [] for cid in predictions() if cid != "DEV003"} if bad_rule == "missing_case" else []
        rule_path.write_text(json.dumps(rules))
        command.extend(["--rule-results", str(rule_path)])
    assert run_regression.main(command) == 2
    assert calls == []


def test_bad_log_file_prevents_paid_evaluation(tmp_path, monkeypatch):
    monkeypatch.setattr(run_regression, "run_offline", fake_offline)
    calls = []
    monkeypatch.setattr(run_regression, "evaluate", lambda options: calls.append(options))
    log = tmp_path / "bad-log.jsonl"
    log.write_text(json.dumps({"complaint": SECRET}) + '\n')
    assert run_regression.main(["--base-url", "https://ai.invalid", "--log-file", str(log),
                                "--report-dir", str(tmp_path / "reports")]) == 1
    assert calls == []
    assert summary(tmp_path)["model_regression"]["status"] == "not_run"
    assert SECRET not in json.dumps(summary(tmp_path))


def test_log_digest_covers_checked_bytes_only_when_active_file_grows(tmp_path, monkeypatch):
    content = (ROOT / "tests/fixtures/operational_log_samples.jsonl").read_bytes()
    log = tmp_path / "active-log.jsonl"
    log.write_bytes(content)
    def offline(directory):
        with log.open('a') as stream:
            stream.write(json.dumps({"complaint": SECRET}) + '\n')
        return fake_offline(directory)
    monkeypatch.setattr(run_regression, "run_offline", offline)
    assert run_regression.main(["--log-file", str(log), "--report-dir", str(tmp_path / "reports")]) == 0
    result = summary(tmp_path)
    manifest = json.loads(next((tmp_path / "reports").glob("*/manifest.json")).read_text())
    assert result["log_validation"]["checked_bytes"] == len(content)
    assert manifest["log_file_sha256"] == hashlib.sha256(content).hexdigest()
    assert manifest["log_file_sha256"] != hashlib.sha256(log.read_bytes()).hexdigest()
    assert SECRET not in json.dumps(result)


def test_saved_inference_uses_snapshot_even_if_original_changes_during_tests(tmp_path, monkeypatch):
    path = saved_input(tmp_path, predictions())
    original = path.read_bytes()
    def offline(directory):
        path.write_text(SECRET)
        return fake_offline(directory)
    monkeypatch.setattr(run_regression, "run_offline", offline)
    assert run_regression.main(["--predictions", str(path), "--report-dir", str(tmp_path / "reports")]) == 0
    manifest = json.loads(next((tmp_path / "reports").glob("*/manifest.json")).read_text())
    assert manifest["predictions_sha256"] == hashlib.sha256(original).hexdigest()
    assert summary(tmp_path)["model_regression"]["passed_cases"] == 20


@pytest.mark.parametrize("error", [OSError(SECRET), subprocess.TimeoutExpired("pytest", 120, output=SECRET)])
def test_child_execution_failure_never_exposes_exception_output(tmp_path, monkeypatch, error):
    def child(*args, **kwargs):
        raise error
    monkeypatch.setattr(run_regression.subprocess, "run", child)
    result = run_regression.run_offline(tmp_path)
    assert result["status"] == "failed"
    assert result["error_code"] == "offline_runner_failed"
    assert SECRET not in json.dumps(result)


@pytest.mark.parametrize("source", ["golden", "duplicate", "bad_json", "remote_http"])
def test_invalid_sources_fail_before_offline_or_model_calls(tmp_path, monkeypatch, capsys, source):
    calls = []
    monkeypatch.setattr(run_regression, "run_offline", lambda directory: calls.append(directory))
    command = ["--report-dir", str(tmp_path / "reports")]
    if source == "remote_http":
        command.extend(["--base-url", "http://remote.invalid"])
    else:
        records = list(predictions().values())
        if source == "golden":
            records[0]["case_id"] = "G001"
        if source == "duplicate":
            records.append(records[0])
        path = tmp_path / "predictions.json"
        path.write_text(SECRET if source == "bad_json" else json.dumps(records))
        command.extend(["--predictions", str(path)])
    assert run_regression.main(command) == 2
    assert calls == []
    assert not (tmp_path / "reports").exists()
    assert SECRET not in capsys.readouterr().err
