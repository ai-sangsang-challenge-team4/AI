"""Offline contracts for three-way Golden Set comparisons."""
from __future__ import annotations

import csv
import hashlib
import json

import pytest

from scripts.compare_goldenset_three_way import (
    _mcnemar_exact, _risk_summary, compare, load_run,
)
from scripts.evaluation.data import EVALUATED_CODES


def _write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def fixture_run(tmp_path, name, *, gold="PRESENT", pred="PRESENT", failed=False):
    directory = tmp_path / name
    directory.mkdir()
    cases = [{"case_id": f"G{i:03}", "request_success": "0" if failed and i == 1 else "1",
              "latency_ms": "3.0"} for i in range(1, 201)]
    rows = [
        {"case_id": f"G{i:03}", "code": code, "gold_state": gold, "predicted_state": pred,
         "request_success": 0 if failed and i == 1 else 1,
         "evaluation_in_scope": 1, "state_match": int(gold == pred),
         "evidence_evaluable": 0, "evidence_exclusion_reason": "fixture",
         "predicted_span_count": 0, "grounded_span_count": 0}
        for i in range(1, 201) for code in EVALUATED_CODES
    ]
    _write_csv(directory / "cases.csv", cases)
    _write_csv(directory / "results.csv", rows)
    meta = {"schema_version": 1, "dataset_schema": "goldenset", "requested_cases": 200,
            "dataset": {"sha256": "a"*64},
            "mode": "llm" if name == "llm" else "rule_llm",
            "rule": {"source": "empty_rule_results"} if name == "llm" else {},
            "backend_capture": {"prediction_view": "rule"} if name == "rule" else None,
            "artifacts": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in directory.iterdir()}}
    (directory / "manifest.json").write_text(json.dumps(meta), encoding="utf-8")
    return directory


def test_three_way_comparison_preserves_paired_case_denominators(tmp_path):
    paths = {name: fixture_run(tmp_path, name, pred="ABSENT" if name == "rule" else "PRESENT",
                               failed=name == "service")
             for name in ("rule", "llm", "service")}
    runs = {name: load_run(path, name=name) for name, path in paths.items()}
    summary = compare(runs, bootstrap_rounds=0)
    assert summary["common_paired_cases"] == 199
    assert not summary["complete_200_case_comparison"]
    assert summary["runs"]["rule"]["macro"]["present"]["macro_f1"] == 0
    assert summary["runs"]["llm"]["macro"]["present"]["macro_f1"] == 1
    assert summary["comparisons"]["rule_vs_llm"]["mcnemar_case_exact"]["right_only_correct"] == 199
    assert summary["runs"]["service"]["final_risk"]["status"].startswith("not_evaluated")
    assert summary["excluded"] == ["REPEAT"]


def test_case_level_mcnemar_uses_case_not_label_count():
    cases = {"one", "two"}
    def make(value):
        return {"rows": [
            {"case_id": case, "code": code, "gold_state": "PRESENT",
             "predicted_state": "PRESENT" if value[case] else "ABSENT",
             "evaluation_in_scope": 1, "request_success": 1}
            for case in cases for code in EVALUATED_CODES]}
    summary = _mcnemar_exact(make({"one": True, "two": False}),
                             make({"one": False, "two": True}), cases)
    assert summary["left_only_correct"] == 1
    assert summary["right_only_correct"] == 1
    assert summary["exact_two_sided_p"] == 1


def test_rejects_tampered_or_incompatible_sources(tmp_path):
    path = fixture_run(tmp_path, "llm")
    (path / "results.csv").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_run(path, name="llm")
    path2 = fixture_run(tmp_path, "service")
    meta = json.loads((path2 / "manifest.json").read_text())
    meta["dataset"]["sha256"] = "b"*64
    (path2 / "manifest.json").write_text(json.dumps(meta))
    rule = fixture_run(tmp_path, "rule")
    new_llm = fixture_run(tmp_path, "llm-fresh")
    new_manifest = json.loads((new_llm / "manifest.json").read_text())
    new_manifest["mode"] = "llm"
    new_manifest["rule"] = {"source": "empty_rule_results"}
    (new_llm / "manifest.json").write_text(json.dumps(new_manifest))
    with pytest.raises(ValueError, match="same Golden Set"):
        compare({"rule": load_run(rule, name="rule"),
                 "llm": load_run(new_llm, name="llm"),
                 "service": load_run(path2, name="service")}, bootstrap_rounds=0)


def test_risk_requires_complete_confirmed_case_predictions():
    summary = _risk_summary({"risk": []}, {"G001"})
    assert summary["status"] == "not_evaluated_missing_case_level_risk_results"
