"""Run with: python3 -m unittest discover -s tests -v (no SDK/network needed)."""
from __future__ import annotations

import csv
import fcntl
import hashlib
import importlib
import io
import json
import math
import socket
import sys
import tempfile
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.evaluate_risk_prompt_updated import build_parser, main
from scripts.evaluation.contracts import ContractError, build_payload, parse_predictions
from scripts.evaluation.data import (BACKEND_CODES, BACKEND_TO_RISK_FACTOR, FILENAMES,
                                     check_disjoint, file_hash, load_dataset, normalize_message)
from scripts.evaluation.metrics import binary_metrics, evidence_columns
from scripts.evaluation.reporting import REPO_ROOT, read_result_rows
from scripts.evaluation.runner import evaluate, post_json, RequestFailure


def response(states=None, spans=None):
    states, spans = states or {}, spans or {}
    return {"tags": [{"code": code, "state": states.get(code, "UNKNOWN" if code == "REPEAT" else "ABSENT"),
                      "evidenceSpans": [{"text": text} for text in spans.get(code, [])]}
                     for code in BACKEND_CODES],
            "metadata": {"modelName": "test-double", "generationSettings": {"temperature": 0, "max_tokens": 4096}}}


def csv_write(path, rows):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def fixture_dataset(directory, schema="dev", count=4):
    directory.mkdir(parents=True, exist_ok=True)
    cases, labels = [], []
    for number in range(1, count + 1):
        case_id = f"T{number}"
        case = {"case_id": case_id, "message_text": f"독립 테스트 {number} 위협 경계",
                "history_available": "False" if schema == "goldenset" else "NO"}
        states = {code: "ABSENT" for code in BACKEND_CODES}
        states["REPEAT"] = "UNKNOWN"
        states["THREAT"] = ["PRESENT", "BOUNDARY", "ABSENT", "UNKNOWN"][(number - 1) % 4]
        if schema == "goldenset":
            case.update(states)
            case["primaryTopic_AI_proposed"] = "DO_NOT_SEND_AI_PROPOSED"
        cases.append(case)
        for code in BACKEND_CODES:
            evidence = "위협" if code == "THREAT" and states[code] in ("PRESENT", "BOUNDARY") else ""
            if schema == "dev":
                label = {"case_id": case_id, "risk_factor": BACKEND_TO_RISK_FACTOR[code],
                         "status": states[code], "evidence_span": evidence,
                         "reason": "DO_NOT_SEND_GOLD_REASON", "review_required": "NO", "label_origin": "AI_PROPOSED"}
            else:
                label = {"case_id": case_id, "riskTagCode": code, "state": states[code], "evidence": evidence,
                         "reason": "DO_NOT_SEND_GOLD_REASON", "initial_v02_first_pass_state": "DO_NOT_SEND_PAST",
                         "teacher_review_status": "TEACHER_REVIEWED_1P" if number == 1 else "AI_PROPOSED_UNCONFIRMED"}
            labels.append(label)
    case_path, label_path = (directory / name for name in FILENAMES[schema])
    csv_write(case_path, cases)
    csv_write(label_path, labels)
    return cases, labels, case_path, label_path


def options(directory, schema="dev", *extra):
    args = build_parser().parse_args(["--data-dir", str(directory), "--dataset", schema,
                                      "--report-dir", str(directory / "reports"), "--sleep", "0", *extra])
    args.policies = ["present", "present_boundary"] if args.positive_policy == "both" else [args.positive_policy]
    return args


class OfflineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        # Any accidental real connection fails every test, including SDK tests.
        connection = patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden"))
        connection.start()
        self.addCleanup(connection.stop)


class DatasetTests(OfflineTest):
    def test_real_schemas_and_disjointness(self):
        dev = load_dataset(REPO_ROOT / "data/dev")
        gold = load_dataset(REPO_ROOT / "data/goldenset")
        self.assertEqual((len(dev.cases), len(gold.cases)), (100, 200))
        self.assertEqual(sum(len(x) for x in gold.labels.values()), 1600)
        self.assertTrue(check_disjoint(dev.cases, gold.cases)["passed"])
        self.assertEqual(sum(label["review_group"] == "teacher_reviewed"
                             for labels in gold.labels.values() for label in labels.values()), 411)

    def test_adapters(self):
        for schema in ("dev", "goldenset"):
            with self.subTest(schema=schema):
                fixture_dataset(self.directory / schema, schema)
                dataset = load_dataset(self.directory / schema)
                self.assertEqual(dataset.labels["T1"]["THREAT"]["status"], "PRESENT")
                self.assertEqual(dataset.labels["T2"]["THREAT"]["evidence_span"], "위협")

    def test_rejects_invalid_datasets(self):
        mutations = {
            "duplicate_case_id": lambda c, l: c.append(dict(c[0])),
            "duplicate_label": lambda c, l: l.append(dict(l[0])),
            "missing_tag": lambda c, l: l.pop(),
            "invalid_state": lambda c, l: l[0].update(status="INVALID"),
            "blank_state": lambda c, l: l[0].update(status=""),
            "invalid_code": lambda c, l: l[0].update(risk_factor="INVALID"),
            "orphan_label": lambda c, l: l.append({**l[0], "case_id": "ORPHAN"}),
            "blank_case_id": lambda c, l: c[0].update(case_id=""),
            "blank_message": lambda c, l: c[0].update(message_text=""),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                cases, labels, cp, lp = fixture_dataset(self.directory / name)
                mutate(cases, labels)
                csv_write(cp, cases)
                csv_write(lp, labels)
                with self.assertRaises(ValueError):
                    load_dataset(cp.parent)

    def test_golden_disagreement_and_missing_wide_state(self):
        for value in ("PRESENT", "INVALID", ""):
            with self.subTest(value=value):
                cases, labels, cp, lp = fixture_dataset(self.directory, "goldenset")
                cases[0]["LEGAL"] = value
                csv_write(cp, cases)
                with self.assertRaises(ValueError):
                    load_dataset(self.directory)

    def test_golden_checks_do_not_treat_context_evidence_as_message(self):
        _, labels, _, lp = fixture_dataset(self.directory, "goldenset")
        next(r for r in labels if r["riskTagCode"] == "REPEAT")["evidence"] = "이력 설명"
        csv_write(lp, labels)
        self.assertEqual(len(load_dataset(self.directory).cases), 4)

    def test_overlap_id_and_unicode_normalization(self):
        self.assertEqual(normalize_message("Ａ\u3000B\nＣ"), "ABC")
        result = check_disjoint([{"case_id": "D", "message_text": "Ａ B\nＣ"}],
                                [{"case_id": "G", "message_text": "ABC"}])
        self.assertFalse(result["passed"])
        self.assertEqual(result["text_overlaps"], [{"case_id": "D", "other_case_id": "G"}])
        self.assertFalse(check_disjoint([{"case_id": "X", "message_text": "one"}],
                                       [{"case_id": "X", "message_text": "two"}])["passed"])

    def test_malformed_csv_and_duplicate_headers(self):
        for content in ("case_id,case_id\nx,y\n", "case_id,message_text\nx,text,extra\n",
                        "case_id,message_text\nx\n"):
            with self.subTest(content=content):
                fixture_dataset(self.directory)
                (self.directory / FILENAMES["dev"][0]).write_text(content, encoding="utf-8")
                with self.assertRaises(ValueError):
                    load_dataset(self.directory)


class ContractTests(OfflineTest):
    def test_missing_duplicate_and_invalid_predictions_fail(self):
        bad = []
        sample = response(); sample["tags"].pop(); bad.append(sample)
        sample = response(); sample["tags"].append(sample["tags"][0]); bad.append(sample)
        for key, value in (("code", "FAKE"), ("state", "BAD"), ("confidence", math.nan),
                           ("confidence", True), ("evidenceSpans", ["not-an-object"])):
            sample = response(); sample["tags"][0][key] = value; bad.append(sample)
        bad.extend([{}, {"tags": []}, {"tags": {}}, []])
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(ContractError):
                    parse_predictions(value)

    def test_correct_prediction_tuple(self):
        states, confidence, spans, reason = parse_predictions(response({"THREAT": "PRESENT"}, {"THREAT": ["위협"]}))
        self.assertEqual(len(states), 8)
        self.assertEqual((states["THREAT"], spans["THREAT"]), ("PRESENT", ["위협"]))

    def test_input_allowlist_and_preserved_rule_states(self):
        case = {"message_text": "입력", "THREAT": "PRESENT", "reason": "SECRET", "evidence": "SECRET",
                "prior_v04_state": "SECRET", "primaryTopic_AI_proposed": "SECRET", "history_context": "SECRET"}
        self.assertEqual(build_payload(case), {"complaint": "입력", "ruleResults": []})
        rules = [{"code": "THREAT", "state": "BOUNDARY"}, {"code": "PRIVACY", "state": "UNKNOWN"}]
        self.assertEqual(build_payload(case, "rule_llm", rules)["ruleResults"], rules)
        with self.assertRaises(ValueError):
            build_payload(case, "rule_llm")


class MetricTests(unittest.TestCase):
    def test_binary_policies_unknown_and_zero_support(self):
        rows = [{"gold_state": g, "predicted_state": p} for g, p in
                [("PRESENT", "PRESENT"), ("BOUNDARY", "PRESENT"), ("ABSENT", "BOUNDARY"), ("UNKNOWN", "PRESENT")]]
        present = binary_metrics(rows, "present")
        boundary = binary_metrics(rows, "present_boundary")
        self.assertEqual((present["tp"], present["fp"], present["tn"], present["fn"]), (1, 1, 1, 0))
        self.assertAlmostEqual(present["f1"], 2 / 3)
        self.assertEqual((boundary["tp"], boundary["fp"], boundary["evaluated_labels"]), (2, 1, 3))
        self.assertAlmostEqual(boundary["f1"], 0.8)
        self.assertEqual(present["excluded_gold_unknown"], 1)
        self.assertIsNone(binary_metrics(rows[-1:], "present")["f1"])
        self.assertEqual(binary_metrics([{"gold_state": "ABSENT", "predicted_state": "ABSENT"}], "present")["f1"], 0)
        self.assertEqual(binary_metrics([{"gold_state": "PRESENT", "predicted_state": "UNKNOWN"}], "present")["fn"], 1)

    def test_grounding_and_evidence_denominators(self):
        label = {"status": "PRESENT", "evidence_span": "위협"}
        hit = evidence_columns(label, {"evidenceSpans": [{"text": "직접 위협"}]}, "직접 위협 입니다")
        self.assertEqual((hit["evidence_match"], hit["grounded_span_count"]), ("MATCH", 1))
        hallucination = evidence_columns(label, {"evidenceSpans": [{"text": "없는 위협"}]}, "직접 위협 입니다")
        self.assertEqual((hallucination["evidence_match"], hallucination["grounded_span_count"]), ("NO_PREDICTED_EVIDENCE", 0))
        for label, expected in (({"status": "ABSENT", "evidence_span": "이력"}, "gold_state_not_present_or_boundary"),
                                ({"status": "PRESENT", "evidence_span": "이력"}, "gold_evidence_not_in_complaint"),
                                ({"status": "BOUNDARY", "evidence_span": ""}, "gold_evidence_missing")):
            self.assertEqual(evidence_columns(label, None, "원문")["evidence_exclusion_reason"], expected)


class PipelineTests(OfflineTest):
    def setUp(self):
        super().setUp()
        fixture_dataset(self.directory)

    def run_mock(self, states=None, **changes):
        args = options(self.directory)
        for name, value in changes.items():
            setattr(args, name, value)
        captured = []
        def transport(url, payload, timeout):
            captured.append(payload)
            return response(states)
        result = evaluate(args, transport)
        return result, captured

    def test_full_report_metrics_manifest_and_latest_compatibility(self):
        (metrics, directory, status), captured = self.run_mock({"THREAT": "PRESENT"})
        self.assertEqual(status, 0)
        self.assertEqual(len(captured), 4)
        self.assertTrue(all(set(p) == {"complaint", "ruleResults"} and not p["ruleResults"] for p in captured))
        self.assertEqual(metrics["tag_exact_match"]["denominator"], 28)
        self.assertAlmostEqual(metrics["binary"]["present"]["micro"]["f1"], 0.5)
        self.assertEqual(metrics["binary"]["present"]["micro"]["excluded_gold_unknown"], 1)
        self.assertAlmostEqual(metrics["binary"]["present"]["macro_f1"], 0.5 / 7)
        self.assertEqual(metrics["all_tags_exact_match"]["matched_cases"], 1)
        self.assertEqual(metrics["confusion_matrix"]["UNKNOWN"]["PRESENT"], 1)
        self.assertEqual(metrics["evidence"]["evaluable_labels"], 2)
        self.assertEqual(metrics["evidence"]["match_rate"], 0)
        with (directory / "evidence_mismatches.csv").open(encoding="utf-8-sig") as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 2)
        manifest = json.loads((directory / "manifest.json").read_text())
        self.assertEqual(manifest["actual_generation_settings"], [{"temperature": 0, "max_tokens": 4096}])
        self.assertEqual(manifest["models"], {"test-double": 4})
        self.assertEqual(len(manifest["git"]["sha"]), 40)
        self.assertEqual(manifest["evaluation"]["excluded_codes"], {"REPEAT": "history_not_supplied"})
        for filename, digest in manifest["artifacts"].items():
            self.assertEqual(file_hash(directory / filename), digest)
        self.assertEqual((directory / "results.csv").read_bytes(), (directory.parent / "results.csv").read_bytes())
        self.assertEqual(len(read_result_rows(directory / "results.csv")), 32)
        summary = json.loads((directory / "summary.json").read_text())
        self.assertEqual(summary["core_review_required_no"]["stable_cases"], 4)

    def test_contract_failures_not_absent_or_success(self):
        args = options(self.directory)
        result = response(); result["tags"].pop()
        metrics, directory, status = evaluate(args, lambda *args: result)
        self.assertEqual(status, 1)
        self.assertEqual(metrics["coverage"]["failed_cases"], 4)
        self.assertIsNone(metrics["tag_exact_match"]["rate"])
        self.assertEqual(metrics["denominators"]["failed_labels"], 28)
        self.assertTrue(all(r["predicted_state"] == "" for r in read_result_rows(directory / "results.csv")))
        with (directory / "failures.csv").open(encoding="utf-8-sig") as stream:
            self.assertEqual(len(list(csv.DictReader(stream))), 4)

    def test_failure_after_one_success_and_stop(self):
        args = options(self.directory); args.stop_on_error = True
        calls = []
        def transport(*unused):
            calls.append(True)
            if len(calls) == 2:
                raise TimeoutError("DO_NOT_PERSIST_SECRET")
            return response()
        metrics, directory, status = evaluate(args, transport)
        self.assertEqual((status, metrics["coverage"]["not_attempted_cases"]), (1, 2))
        self.assertEqual(metrics["tag_exact_match"]["denominator"], 7)
        self.assertEqual(metrics["all_tags_exact_match"]["requested_cases"], 4)
        self.assertNotIn("DO_NOT_PERSIST_SECRET", (directory / "predictions.jsonl").read_text())

    def test_replay_never_calls_transport_and_checks_hash(self):
        (_, original, _), _ = self.run_mock()
        args = options(self.directory); args.predictions = str(original / "predictions.jsonl")
        blocked = Mock(side_effect=AssertionError("transport forbidden"))
        _, replay, status = evaluate(args, blocked)
        self.assertEqual(status, 0)
        blocked.assert_not_called()
        self.assertNotEqual(original, replay)
        records = [json.loads(line) for line in (original / "predictions.jsonl").read_text().splitlines()]
        records[0]["input_sha256"] = "wrong"
        path = self.directory / "changed.json"; path.write_text(json.dumps(records))
        args.predictions = str(path)
        metrics, _, status = evaluate(args, blocked)
        self.assertEqual(status, 1)
        self.assertEqual(metrics["coverage"]["failure_codes"], {"contract:prediction_input_hash_mismatch": 1})

    def test_missing_and_duplicate_replay_records(self):
        path = self.directory / "predictions.json"
        path.write_text(json.dumps([{"case_id": "T1", "response": response()}]))
        args = options(self.directory); args.predictions = str(path)
        metrics, _, status = evaluate(args)
        self.assertEqual((status, metrics["coverage"]["failed_cases"]), (1, 3))
        self.assertEqual(metrics["coverage"]["failure_codes"], {"request:missing_prediction": 3})
        path.write_text(json.dumps([{"case_id": "T1"}, {"case_id": "T1"}]))
        with self.assertRaises(ValueError):
            evaluate(args)

    def test_unverified_provenance_stays_unverified_across_saved_replays(self):
        path = self.directory / "external.json"
        path.write_text(json.dumps([{"case_id": f"T{i}", "response": response()} for i in range(1, 5)]))
        args = options(self.directory)
        blocked = Mock(side_effect=AssertionError("transport forbidden"))
        for generation in range(3):
            args.predictions = str(path)
            _, directory, status = evaluate(args, blocked)
            self.assertEqual(status, 0)
            records = [json.loads(line) for line in (directory / "predictions.jsonl").read_text().splitlines()]
            self.assertTrue(all(record["source_provenance_verified"] is False for record in records), generation)
            path = directory / "predictions.jsonl"
        self.assertTrue(all(record["input_hash_origin"] == "reconstructed_for_replay" for record in records))
        blocked.assert_not_called()

    def test_captured_provenance_survives_saved_replays(self):
        (_, directory, _), _ = self.run_mock()
        records = [json.loads(line) for line in (directory / "predictions.jsonl").read_text().splitlines()]
        self.assertTrue(all(record["source_provenance_verified"] is True for record in records))
        self.assertTrue(all(record["input_hash_origin"] == "captured_request" for record in records))
        args = options(self.directory)
        for generation in range(2):
            args.predictions = str(directory / "predictions.jsonl")
            _, directory, status = evaluate(args)
            self.assertEqual(status, 0)
            records = [json.loads(line) for line in (directory / "predictions.jsonl").read_text().splitlines()]
            self.assertTrue(all(record["source_provenance_verified"] is True for record in records), generation)

    def test_recorded_contract_failure_preserves_code_and_response(self):
        invalid = response()
        invalid["tags"].pop()
        args = options(self.directory)
        _, directory, status = evaluate(args, lambda *unused: invalid)
        self.assertEqual(status, 1)
        blocked = Mock(side_effect=AssertionError("transport forbidden"))
        for generation in range(2):
            args.predictions = str(directory / "predictions.jsonl")
            metrics, directory, status = evaluate(args, blocked)
            self.assertEqual(status, 1)
            self.assertEqual(metrics["coverage"]["failure_codes"], {"contract:missing_tags": 4})
            records = [json.loads(line) for line in (directory / "predictions.jsonl").read_text().splitlines()]
            self.assertTrue(all(record["response"] == invalid and record["request_success"] == 0 for record in records), generation)
        blocked.assert_not_called()

    def test_recorded_failure_sanitizes_unknown_codes_and_non_json_values(self):
        invalid = response()
        invalid["metadata"]["temperature"] = math.nan
        path = self.directory / "failed.json"
        path.write_text(json.dumps([{"case_id": f"T{i}", "request_success": 0,
                                    "error_code": "request:exception DO_NOT_PERSIST_SECRET",
                                    "response": invalid, "latency_ms": math.nan, "rag_snapshot_id": math.nan}
                                   for i in range(1, 5)]))
        args = options(self.directory); args.predictions = str(path)
        metrics, directory, status = evaluate(args)
        self.assertEqual(status, 1)
        self.assertEqual(metrics["coverage"]["failure_codes"], {"request:recorded_request_failure": 4})
        saved = (directory / "predictions.jsonl").read_text()
        self.assertNotIn("DO_NOT_PERSIST_SECRET", saved)
        self.assertNotIn("NaN", saved)
        self.assertTrue(all(json.loads(line)["response"] is None for line in saved.splitlines()))

    def test_recorded_http_failure_keeps_allowlisted_code(self):
        path = self.directory / "failed.json"
        path.write_text(json.dumps([{"case_id": f"T{i}", "request_success": 0,
                                    "error_code": "request:http_503", "response": None}
                                   for i in range(1, 5)]))
        args = options(self.directory); args.predictions = str(path)
        metrics, _, status = evaluate(args)
        self.assertEqual(status, 1)
        self.assertEqual(metrics["coverage"]["failure_codes"], {"request:http_503": 4})

    def test_replay_mode_complaint_and_latency_contract_failures(self):
        for changed, expected in [({"mode": "rule_llm"}, "prediction_mode_mismatch"),
                                  ({"complaint_sha256": "wrong"}, "prediction_complaint_hash_mismatch"),
                                  ({"latency_ms": math.nan}, "invalid_latency")]:
            with self.subTest(expected=expected):
                records = [{"case_id": f"T{i}", "response": response()} for i in range(1, 5)]
                records[0].update(changed)
                path = self.directory / "tampered.json"; path.write_text(json.dumps(records))
                args = options(self.directory); args.predictions = str(path)
                metrics, _, status = evaluate(args)
                self.assertEqual(status, 1)
                self.assertEqual(metrics["coverage"]["failure_codes"], {"contract:" + expected: 1})

    def test_rule_mode_needs_complete_captured_inputs(self):
        args = options(self.directory); args.mode = "rule_llm"
        never = Mock(side_effect=AssertionError("transport forbidden"))
        with self.assertRaises(ValueError):
            evaluate(args, never)
        rules = {f"T{i}": [{"code": "THREAT", "state": "BOUNDARY"}] for i in range(1, 5)}
        path = self.directory / "rules.json"; path.write_text(json.dumps(rules))
        args.rule_results = str(path)
        captured = []
        def transport(url, payload, timeout):
            captured.append(payload)
            return response()
        _, directory, status = evaluate(args, transport)
        self.assertEqual(status, 0)
        self.assertTrue(all(p["ruleResults"][0]["state"] == "BOUNDARY" for p in captured))
        self.assertEqual(json.loads((directory / "manifest.json").read_text())["rule"]["sha256"], file_hash(path))

    def test_golden_no_answer_leakage_and_review_groups(self):
        fixture_dataset(self.directory, "goldenset")
        (metrics, _, status), captured = self.run_mock(dataset="goldenset")
        self.assertEqual(status, 0)
        self.assertTrue(all("DO_NOT_SEND" not in json.dumps(p) for p in captured))
        self.assertEqual(metrics["review_groups"]["teacher_reviewed"]["tag_exact_match"]["denominator"], 7)
        self.assertEqual(metrics["review_groups"]["unconfirmed"]["tag_exact_match"]["denominator"], 21)

    def test_comparison_new_errors_corrected_cases_and_failure_pairing(self):
        (_, before, _), _ = self.run_mock({"THREAT": "PRESENT"})
        (metrics, after, status), _ = self.run_mock({"THREAT": "ABSENT"}, previous=str(before))
        self.assertEqual(status, 0)
        diff = json.loads((after / "diff.json").read_text())
        self.assertEqual(diff["paired_cases"], 4)
        self.assertEqual([(r["case_id"], r["code"]) for r in diff["newly_wrong"]], [("T1", "THREAT")])
        self.assertEqual([(r["case_id"], r["code"]) for r in diff["corrected"]], [("T3", "THREAT")])
        args = options(self.directory); args.previous = str(before)
        def partial(url, payload, timeout):
            if " 1 " in payload["complaint"]:
                raise TimeoutError()
            return response({"THREAT": "ABSENT"})
        _, failed, status = evaluate(args, partial)
        diff = json.loads((failed / "diff.json").read_text())
        self.assertEqual((status, diff["paired_cases"], diff["newly_failed_cases"]), (1, 3, ["T1"]))
        self.assertEqual(diff["before"]["tag_exact_match"]["denominator"], 21)

    def test_incompatible_comparison_still_saves_current_run(self):
        (_, before, _), _ = self.run_mock()
        (metrics, after, status), _ = self.run_mock(previous=str(before), policies=["present"])
        self.assertEqual(status, 1)
        self.assertEqual(json.loads((after / "diff.json").read_text())["status"], "incompatible")
        self.assertTrue((after / "results.csv").is_file())

    def test_tampered_baseline_is_rejected(self):
        (_, before, _), _ = self.run_mock()
        with (before / "results.csv").open("a", encoding="utf-8") as stream:
            stream.write("tampered\n")
        (_, after, status), _ = self.run_mock(previous=str(before))
        self.assertEqual(status, 1)
        self.assertIn("hash", json.loads((after / "diff.json").read_text())["reason"])

    def test_malformed_previous_manifests_preserve_current_results(self):
        (_, before, _), _ = self.run_mock()
        valid = json.loads((before / "manifest.json").read_text())
        malformed = [[], None, 3, {**valid, "dataset": []}, {**valid, "evaluation": None},
                     {**valid, "artifacts": []}, {**valid, "dataset": {"sha256": []}}]
        for value in malformed:
            with self.subTest(value=value):
                (before / "manifest.json").write_text(json.dumps(value))
                (_, after, status), _ = self.run_mock(previous=str(before))
                self.assertEqual(status, 1)
                self.assertTrue((after / "results.csv").is_file())
                self.assertEqual(json.loads((after / "diff.json").read_text())["status"], "incompatible")

    def test_rule_hash_uses_bytes_captured_before_requests(self):
        rules = {f"T{i}": [] for i in range(1, 5)}
        path = self.directory / "rules.json"
        original = json.dumps(rules).encode()
        path.write_bytes(original)
        args = options(self.directory); args.mode = "rule_llm"; args.rule_results = str(path)
        def transport(*unused):
            path.write_text("changed during requests")
            return response()
        _, directory, status = evaluate(args, transport)
        self.assertEqual(status, 0)
        manifest = json.loads((directory / "manifest.json").read_text())
        self.assertEqual(manifest["rule"]["sha256"], hashlib.sha256(original).hexdigest())

    def test_shared_snapshot_publication_waits_for_interprocess_lock(self):
        from scripts.evaluation import reporting
        root = self.directory / "reports"
        root.mkdir()
        manifest_ready, copied = Event(), Event()
        original_manifest, original_copy = reporting.build_manifest, reporting.shutil.copyfile
        def build(*args, **kwargs):
            manifest_ready.set()
            return original_manifest(*args, **kwargs)
        def copy(*args, **kwargs):
            copied.set()
            return original_copy(*args, **kwargs)
        with (root / ".publish.lock").open("a") as lock, ThreadPoolExecutor(max_workers=1) as pool:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with patch("scripts.evaluation.runner.build_manifest", side_effect=build), patch.object(reporting.shutil, "copyfile", side_effect=copy):
                future = pool.submit(self.run_mock)
                try:
                    self.assertTrue(manifest_ready.wait(5))
                    self.assertFalse(copied.wait(0.2), "publication must wait for the other process")
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
                (_, directory, status), _ = future.result(timeout=5)
        self.assertEqual(status, 0)
        latest = json.loads((root / "latest.json").read_text())
        self.assertEqual(latest["run_id"], directory.name)
        self.assertEqual((root / "results.csv").read_bytes(), (directory / "results.csv").read_bytes())

    def test_legacy_metadata_does_not_invent_actual_settings(self):
        def transport(*unused):
            value = response()
            value["metadata"] = {"modelName": "legacy", "temperature": 0}
            return value
        _, directory, status = evaluate(options(self.directory), transport)
        self.assertEqual(status, 0)
        manifest = json.loads((directory / "manifest.json").read_text())
        self.assertEqual(manifest["actual_generation_settings"], [])
        self.assertEqual(manifest["records_without_generation_settings"], 4)

    def test_invalid_json_values_are_recorded_as_failure(self):
        value = response(); value["metadata"]["temperature"] = math.nan
        metrics, directory, status = evaluate(options(self.directory), lambda *unused: value)
        self.assertEqual(status, 1)
        self.assertEqual(metrics["coverage"]["failure_codes"], {"contract:response_not_json_serializable": 4})
        self.assertNotIn("NaN", (directory / "predictions.jsonl").read_text())

    def test_selected_boundary_policy(self):
        args = options(self.directory, "dev", "--positive-policy", "present_boundary")
        metrics, directory, status = evaluate(args, lambda *unused: response({"THREAT": "PRESENT"}))
        self.assertEqual(status, 0)
        self.assertEqual(set(metrics["binary"]), {"present_boundary"})
        self.assertAlmostEqual(metrics["binary"]["present_boundary"]["micro"]["f1"], 0.8)

    def test_real_300_cases_with_mock_predictions(self):
        for schema in ("dev", "goldenset"):
            with self.subTest(schema=schema):
                args = options(REPO_ROOT / "data" / schema, schema)
                args.report_dir = str(self.directory / schema)
                metrics, directory, status = evaluate(args, lambda *unused: response())
                count = 100 if schema == "dev" else 200
                self.assertEqual((status, metrics["coverage"]["succeeded_cases"]), (0, count))
                self.assertEqual(metrics["tag_exact_match"]["denominator"], count * 7)
                self.assertEqual(len(read_result_rows(directory / "results.csv")), count * 8)

    def test_cli_old_flags_and_validation_only_are_offline(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--data-dir", str(self.directory), "--limit", "1", "--case-id", "T1",
                                   "--timeout", "10", "--sleep", "0", "--validate-only"]), 0)
            self.assertEqual(main(["--data-dir", str(self.directory), "--case-id", "MISSING", "--validate-only"]), 2)

    def test_overlap_prevents_requests_even_with_case_filter(self):
        other = self.directory / "other"
        cases, labels, cp, lp = fixture_dataset(other, "goldenset")
        args = options(self.directory); args.overlap_data_dir = str(other); args.case_ids = ["T1"]
        never = Mock()
        with self.assertRaises(ValueError):
            evaluate(args, never)
        never.assert_not_called()


class TransportAndMetadataTests(OfflineTest):
    def test_http_errors_do_not_include_response_body(self):
        from urllib.error import HTTPError
        exc = HTTPError("http://invalid", 503, "upstream", {}, io.BytesIO(b"SECRET"))
        with patch("scripts.evaluation.runner.urlopen", side_effect=exc):
            with self.assertRaises(RequestFailure) as caught:
                post_json("http://invalid", {"complaint": "SECRET"}, 1)
        self.assertEqual(str(caught.exception), "http_503")

    def test_sdk_settings_recorded_are_exactly_the_arguments_sent(self):
        sdk = types.ModuleType("anthropic"); sdk.Anthropic = Mock()
        sdk.Anthropic.return_value.messages.create.return_value = types.SimpleNamespace(
            content=[types.SimpleNamespace(type="text", text="{}")])
        sys.modules.pop("app.llm.claude_client", None)
        with patch.dict(sys.modules, {"anthropic": sdk}), patch.dict("os.environ", {"ANTHROPIC_API_KEY": "not-a-real-key"}):
            module = importlib.import_module("app.llm.claude_client")
            client = module.ClaudeLlmClient(temperature=0.0)
            self.assertEqual(client.generate("test prompt"), "{}")
            kwargs = sdk.Anthropic.return_value.messages.create.call_args.kwargs
            self.assertEqual({k: v for k, v in kwargs.items() if k not in ("model", "messages")}, client.generation_settings)
            sdk.Anthropic.reset_mock()
            default_client = module.ClaudeLlmClient()
            default_client.generate("test")
            self.assertNotIn("temperature", sdk.Anthropic.return_value.messages.create.call_args.kwargs)
        sys.modules.pop("app.llm.claude_client", None)

    def test_server_provenance_is_content_hashes_not_raw_documents(self):
        from app.core.evaluation_metadata import evaluation_provenance
        retriever = types.SimpleNamespace(max_results=3, max_per_source=2, score_threshold=0.35, search_k=10)
        value = evaluation_provenance([{"content": "SECRET_DOCUMENT"}], retriever)
        self.assertNotIn("SECRET_DOCUMENT", json.dumps(value))
        self.assertEqual(len(value["rag_documents_sha256"]), 64)
        self.assertEqual(value["rag_config"]["search_k"], 10)


if __name__ == "__main__":
    unittest.main()
