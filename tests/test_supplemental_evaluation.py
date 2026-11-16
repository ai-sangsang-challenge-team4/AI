"""Synthetic integration scenarios, never Golden Set risk/subtype ground truth."""
import csv
import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts.evaluation.data import json_hash, load_dataset
from scripts.evaluation.runner import evaluate
from scripts.evaluation.supplemental import (LEVELS, read_targets, risk_metrics, write_target_template)
from tests.test_tagging_evaluation import fixture_dataset, options, response, csv_write


@pytest.fixture
def dataset_dir(tmp_path):
    fixture_dataset(tmp_path)
    return tmp_path


def target_file(directory, *, pending=False):
    dataset = load_dataset(directory)
    path = directory / "targets.csv"
    write_target_template(dataset, path)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    for index, row in enumerate(rows):
        row.update(review_status="PENDING" if pending else "CONFIRMED", risk_level=LEVELS[index],
                   is_legitimate="TRUE" if index == 0 else "FALSE",
                   threat_context_subtypes="PHYSICAL_HARM;COERCIVE_PRESSURE" if index == 0 else "COERCIVE_PRESSURE",
                   privacy_context_subtypes="PII_INCLUDED")
    csv_write(path, rows)
    return path


def backend_file(directory, records, levels=LEVELS):
    dataset = load_dataset(directory)
    path = directory / "backend.json"
    path.write_text(json.dumps({"schema_version": 1, "dataset_sha256": dataset.digest, "mode": "llm",
                                "risk_engine": {"version": "synthetic-test-engine", "source_commit": "a" * 40},
                                "predictions": [{"case_id": r["case_id"], "risk_level": level,
                                                 "risk_input_sha256": r["risk_input_sha256"]}
                                                for r, level in zip(records, levels)]}))
    return path


def first_run(directory):
    _, run, _ = evaluate(options(directory), lambda *args: response({"THREAT": "PRESENT"}))
    return run, [json.loads(line) for line in (run / "predictions.jsonl").read_text().splitlines()]


def test_template_has_no_invented_targets_and_never_overwrites(dataset_dir):
    destination = dataset_dir / "blank.csv"
    args = options(dataset_dir); args.write_target_template = str(destination)
    never = Mock(side_effect=AssertionError("no HTTP"))
    value, _, status = evaluate(args, never)
    assert (status, value["confirmed_targets"]) == (0, 0)
    rows, artifact = read_targets(destination, load_dataset(dataset_dir))
    assert len(rows) == 4 and artifact["pending_cases"] == 4
    assert all(not row["risk_level"] and not row["is_legitimate"] for row in rows.values())
    with pytest.raises(FileExistsError):
        evaluate(args, never)
    never.assert_not_called()


def test_full_backend_risk_and_context_cohorts_without_answer_leakage(dataset_dir):
    run, records = first_run(dataset_dir)
    args = options(dataset_dir); args.targets = str(target_file(dataset_dir))
    args.predictions = str(run / "predictions.jsonl")
    args.risk_predictions = str(backend_file(dataset_dir, records, ("MEDIUM", "MEDIUM", "HIGH", "LOW")))
    never = Mock(side_effect=AssertionError("replay must not call HTTP"))
    metrics, output, status = evaluate(args, never)
    assert status == 0
    risk = metrics["final_risk"]
    assert risk["confusion_matrix"]["LOW"]["MEDIUM"] == 1
    assert risk["class_recall"]["HIGH"]["recall"] == 1
    assert risk["class_recall"]["EMERGENCY"]["recall"] == 0
    assert risk["high_or_emergency_recall"] == .5
    assert risk["emergency_missed_case_ids"] == ["T4"]
    assert risk["legitimate_overestimation"]["rate"] == 1
    cohort = metrics["context_subtypes"]["per_tag"]["THREAT"]
    assert cohort["PHYSICAL_HARM"]["annotated_labels"] == 1
    assert cohort["COERCIVE_PRESSURE"]["annotated_labels"] == 4
    assert (output / "emergency_misses.csv").is_file()
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["backend_risk_predictions"]["risk_engine"]["source_commit"] == "a" * 40
    saved = [json.loads(line) for line in (output / "predictions.jsonl").read_text().splitlines()]
    assert all("risk_level" not in r["risk_input"] and "context_subtypes" not in r["risk_input"] for r in saved)
    assert all(r["risk_input_sha256"] == json_hash(r["risk_input"]) for r in saved)
    never.assert_not_called()


def test_pending_labels_and_absent_targets_do_not_become_zero_quality(dataset_dir):
    args = options(dataset_dir); args.targets = str(target_file(dataset_dir, pending=True))
    metrics, _, status = evaluate(args, lambda *args: response())
    assert status == 0
    assert metrics["final_risk"]["status"] == "not_evaluated"
    assert metrics["final_risk"]["class_recall"]["HIGH"]["recall"] is None
    assert metrics["final_risk"]["legitimate_overestimation"]["rate"] is None
    assert metrics["context_subtypes"]["per_tag"]["PRIVACY"]["PII_INCLUDED"]["binary"]["present"]["f1"] is None


@pytest.mark.parametrize("field,value", [("dataset_sha256", "b"*64), ("review_status", "DONE"),
                                          ("risk_level", "URGENT"), ("is_legitimate", "yes"),
                                          ("threat_context_subtypes", "PHYSICAL_HARM;PHYSICAL_HARM"),
                                          ("privacy_context_subtypes", "TYPO")])
def test_invalid_target_contract_stops_before_requests(dataset_dir, field, value):
    path = target_file(dataset_dir)
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rows[0][field] = value
    csv_write(path, rows)
    args = options(dataset_dir); args.targets = str(path)
    never = Mock()
    with pytest.raises(ValueError):
        evaluate(args, never)
    never.assert_not_called()


@pytest.mark.parametrize("mutation", ["mode", "dataset", "engine", "duplicate", "unknown", "level", "hash", "shape"])
def test_invalid_backend_contract_stops_before_requests(dataset_dir, mutation):
    _, records = first_run(dataset_dir)
    path = backend_file(dataset_dir, records)
    value = json.loads(path.read_text())
    if mutation == "mode": value["mode"] = "rule_llm"
    elif mutation == "dataset": value["dataset_sha256"] = "b" * 64
    elif mutation == "engine": value["risk_engine"]["source_commit"] = "unknown"
    elif mutation == "duplicate": value["predictions"].append(value["predictions"][0])
    elif mutation == "unknown": value["predictions"][0]["case_id"] = "MISSING"
    elif mutation == "level": value["predictions"][0]["risk_level"] = "URGENT"
    elif mutation == "hash": value["predictions"][0]["risk_input_sha256"] = []
    elif mutation == "shape": value = []
    path.write_text(json.dumps(value))
    args = options(dataset_dir); args.risk_predictions = str(path); args.targets = str(target_file(dataset_dir))
    never = Mock()
    with pytest.raises(ValueError): evaluate(args, never)
    never.assert_not_called()


@pytest.mark.parametrize("extra", ['"credential":"SECRET_CANARY"', '"extra":NaN', '"extra":Infinity', '"extra":1e400'])
def test_backend_provenance_rejects_extra_or_nonfinite_values_before_requests(dataset_dir, extra):
    _, records = first_run(dataset_dir)
    path = backend_file(dataset_dir, records)
    raw = path.read_text().replace('"source_commit":', extra + ',"source_commit":')
    path.write_text(raw)
    args = options(dataset_dir); args.targets = str(target_file(dataset_dir)); args.risk_predictions = str(path)
    never = Mock()
    with pytest.raises(ValueError): evaluate(args, never)
    never.assert_not_called()


def test_wrong_backend_input_and_missing_predictions_are_coverage_failures(dataset_dir):
    run, records = first_run(dataset_dir)
    path = backend_file(dataset_dir, records)
    value = json.loads(path.read_text())
    value["predictions"][0]["risk_input_sha256"] = "0" * 64
    value["predictions"].pop()
    path.write_text(json.dumps(value))
    args = options(dataset_dir); args.targets = str(target_file(dataset_dir)); args.risk_predictions = str(path)
    args.predictions = str(run / "predictions.jsonl")
    metrics, _, status = evaluate(args)
    assert status == 1
    assert metrics["final_risk"]["successful_cases"] == 2
    assert metrics["final_risk"]["failure_codes"] == {"backend_input_hash_mismatch": 1, "missing_backend_prediction": 1}
    assert sum(sum(row.values()) for row in metrics["final_risk"]["confusion_matrix"].values()) == 2


def test_stop_on_error_preserves_unattempted_cohort_and_risk_denominators(dataset_dir):
    args = options(dataset_dir); args.targets = str(target_file(dataset_dir)); args.stop_on_error = True
    def unavailable(*args): raise TimeoutError()
    metrics, _, status = evaluate(args, unavailable)
    assert status == 1
    assert metrics["coverage"]["not_attempted_cases"] == 3
    group = metrics["context_subtypes"]["per_tag"]["THREAT"]["COERCIVE_PRESSURE"]
    assert group["annotated_labels"] == group["failed_labels"] == 4
    assert metrics["final_risk"]["annotated_cases"] == 4
    assert metrics["final_risk"]["failure_codes"] == {"tagging_failed": 1, "not_attempted": 3}


def test_supplemental_comparison_pairs_successes_and_rejects_changed_gold(dataset_dir):
    run, records = first_run(dataset_dir)
    path = backend_file(dataset_dir, records)
    targets = target_file(dataset_dir)
    args = options(dataset_dir); args.targets = str(targets); args.risk_predictions = str(path)
    args.predictions = str(run / "predictions.jsonl")
    _, before, _ = evaluate(args)
    value = json.loads(path.read_text()); value["predictions"][3]["risk_level"] = "LOW"
    path.write_text(json.dumps(value)); args.previous = str(before)
    _, after, status = evaluate(args)
    assert status == 0
    diff = json.loads((after / "diff.json").read_text())
    assert diff["final_risk"]["newly_wrong_case_ids"] == ["T4"]
    assert diff["final_risk"]["paired_cases"] == 4
    assert diff["final_risk"]["deltas"]["class_recall"]["EMERGENCY"] == -1
    args.case_ids = ["T1"]
    _, subset, status = evaluate(args)
    assert status == 0
    assert json.loads((subset / "diff.json").read_text())["final_risk"]["newly_failed_case_ids"] == []
    args.case_ids = None
    with targets.open(encoding="utf-8-sig", newline="") as stream: rows = list(csv.DictReader(stream))
    rows[0]["risk_level"] = "MEDIUM"; csv_write(targets, rows)
    _, after, status = evaluate(args)
    assert status == 1
    assert json.loads((after / "diff.json").read_text())["status"] == "incompatible"


def test_graphs_are_real_pngs_and_do_not_imply_unavailable_risk_metrics(dataset_dir, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(dataset_dir / "matplotlib"))
    pytest.importorskip("matplotlib")
    args = options(dataset_dir); args.charts = True
    _, output, status = evaluate(args, lambda *args: response())
    assert status == 0
    for name in ("tag_f1.png", "tag_state_confusion.png"):
        assert (output / name).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert not (output / "risk_confusion.png").exists()
    run, records = first_run(dataset_dir)
    args.predictions = str(run / "predictions.jsonl")
    args.targets = str(target_file(dataset_dir)); args.risk_predictions = str(backend_file(dataset_dir, records))
    _, output, status = evaluate(args)
    assert status == 0
    for name in ("risk_confusion.png", "context_subtype_f1.png"):
        assert (output / name).is_file()
        assert name in json.loads((output / "manifest.json").read_text())["artifacts"]


def test_chart_failure_preserves_evaluation_results(dataset_dir, monkeypatch):
    from scripts.evaluation import charts
    monkeypatch.setattr(charts, "check_available", lambda: None)
    def broken(*args): raise RuntimeError("untrusted renderer details")
    monkeypatch.setattr(charts, "render_charts", broken)
    args = options(dataset_dir); args.charts = True
    metrics, output, status = evaluate(args, lambda *args: response())
    assert status == 1 and metrics["coverage"]["succeeded_cases"] == 4
    assert (output / "results.csv").is_file() and (output / "predictions.jsonl").is_file()
    manifest_text = (output / "manifest.json").read_text()
    assert "untrusted renderer details" not in manifest_text
    assert json.loads(manifest_text)["charts"]["status"] == "failed"
