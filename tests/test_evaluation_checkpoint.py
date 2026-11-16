import json
from unittest.mock import Mock

import pytest

from scripts.evaluation.runner import evaluate
from scripts.evaluation.checkpoint import read_checkpoint, recover_checkpoint
from tests.test_tagging_evaluation import fixture_dataset, options, response


def test_completed_requests_survive_later_process_interruption(tmp_path):
    fixture_dataset(tmp_path)
    checkpoint = tmp_path / "checkpoint.jsonl"
    args = options(tmp_path); args.checkpoint_file = str(checkpoint)
    calls = 0
    def transport(*unused):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt()
        return response()
    with pytest.raises(KeyboardInterrupt):
        evaluate(args, transport)
    records = [json.loads(line) for line in checkpoint.read_text().splitlines()]
    assert calls == 2 and len(records) == 1 and records[0]["case_id"] == "T1"
    assert records[0]["request_success"] == 1
    # Recover already paid responses without another HTTP call.
    args.checkpoint_file = None; args.predictions = str(checkpoint); args.case_ids = ["T1"]
    never = Mock()
    metrics, _, status = evaluate(args, never)
    assert status == 0 and metrics["coverage"]["succeeded_cases"] == 1
    never.assert_not_called()


def test_checkpoint_never_overwrites_existing_results(tmp_path):
    fixture_dataset(tmp_path)
    path = tmp_path / "checkpoint.jsonl"; path.write_text("previous results")
    args = options(tmp_path); args.checkpoint_file = str(path)
    never = Mock()
    with pytest.raises(FileExistsError): evaluate(args, never)
    assert path.read_text() == "previous results"
    never.assert_not_called()


def test_checkpoint_retains_safe_failure_and_matches_final_capture(tmp_path):
    fixture_dataset(tmp_path)
    path = tmp_path / "checkpoint.jsonl"
    args = options(tmp_path); args.checkpoint_file = str(path); args.stop_on_error = True
    def transport(*unused): raise TimeoutError("DO_NOT_PERSIST_SECRET")
    _, directory, status = evaluate(args, transport)
    assert status == 1
    assert path.read_bytes() == (directory / "predictions.jsonl").read_bytes()
    assert "DO_NOT_PERSIST_SECRET" not in path.read_text()
    assert json.loads(path.read_text())["request_success"] == 0


def test_replay_cannot_mutate_checkpoint(tmp_path):
    fixture_dataset(tmp_path)
    args = options(tmp_path); args.checkpoint_file = str(tmp_path / "new.jsonl")
    args.predictions = str(tmp_path / "saved.jsonl")
    never = Mock()
    with pytest.raises(ValueError, match="live HTTP"):
        evaluate(args, never)
    assert not (tmp_path / "new.jsonl").exists()
    never.assert_not_called()


@pytest.mark.parametrize("tail", [b'{"case_id":"T2","response":', b'{"text":"\xed\x95'])
def test_recovery_ignores_only_incomplete_unterminated_final_record(tmp_path, tail):
    source, output = tmp_path / "checkpoint.jsonl", tmp_path / "recovered.jsonl"
    record = {"case_id": "T1", "request_success": 1, "response": response()}
    source.write_bytes(json.dumps(record).encode() + b"\n" + tail)
    value = recover_checkpoint(source, output)
    assert value["recovered_records"] == 1 and value["ignored_incomplete_final_record"] is True
    assert json.loads(output.read_text()) == record
    assert source.read_bytes().endswith(tail)
    with pytest.raises(FileExistsError): recover_checkpoint(source, output)


@pytest.mark.parametrize("corrupt", [b'{broken}\n', b'{broken}\n{}', b'{"case_id":"T1","request_success":1,"response":NaN}'])
def test_recovery_rejects_corrupt_complete_or_nonfinite_records(tmp_path, corrupt):
    source, output = tmp_path / "checkpoint.jsonl", tmp_path / "recovered.jsonl"
    source.write_bytes(corrupt)
    with pytest.raises(ValueError): recover_checkpoint(source, output)
    assert not output.exists()


def test_complete_unterminated_record_is_counted_but_duplicates_are_rejected(tmp_path):
    source = tmp_path / "checkpoint.jsonl"
    raw = json.dumps({"case_id": "T1", "request_success": 0, "response": None}).encode()
    source.write_bytes(raw)
    records, ignored = read_checkpoint(source)
    assert len(records) == 1 and not ignored
    source.write_bytes(raw + b"\n" + raw + b"\n")
    with pytest.raises(ValueError): read_checkpoint(source)
