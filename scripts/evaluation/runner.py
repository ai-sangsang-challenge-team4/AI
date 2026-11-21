"""Transport-independent evaluation; only post_json performs network I/O."""
from __future__ import annotations

import json
import hashlib
import math
import os
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .contracts import ContractError, build_payload, prediction_tags, read_predictions
from .data import (BACKEND_CODES, EVALUATED_CODES, FILENAMES, check_disjoint,
                   file_hash, json_hash, load_dataset)
from .metrics import compute_metrics, evidence_columns
from .reporting import REPO_ROOT, build_manifest, compare_run, save_run
from .supplemental import (SUBTYPES, read_targets, read_backend_predictions, risk_input, risk_rows,
                           risk_metrics, subtype_metrics, target_subtypes, write_target_template)

ANALYZE_PATH = "/api/v1/ai/analyze"


class RequestFailure(RuntimeError):
    pass


SAFE_FAILURE_CODES = frozenset({
    "contract:" + code for code in (
        "tags_not_list", "tag_not_object", "invalid_code", "invalid_state", "duplicate_tag",
        "invalid_evidence_spans", "invalid_confidence", "missing_tags", "response_not_object",
        "prediction_mode_mismatch", "prediction_input_hash_mismatch", "prediction_complaint_hash_mismatch",
        "invalid_latency", "invalid_rag_snapshot_id", "response_not_json_serializable",
    )
} | {
    "request:" + code for code in (
        "connection_or_timeout", "invalid_json", "response_not_object", "missing_prediction",
        "recorded_request_failure", "unexpected_error", "backend_rule_only",
        "capture_interrupted", "response_too_large", "invalid_json_shape", "invalid_login_response",
        "invalid_token_expiry", "invalid_created_draft", "invalid_analysis_summary",
    )
})


def safe_recorded_failure_code(value):
    if isinstance(value, str) and (value in SAFE_FAILURE_CODES or re.fullmatch(r"request:http_[1-5][0-9]{2}", value)):
        return value
    return "request:recorded_request_failure"


class RecordedFailure(RequestFailure):
    """A previous failure remains a failure without copying arbitrary exception text."""
    def __init__(self, code):
        self.code = safe_recorded_failure_code(code)
        super().__init__(self.code)


def post_json(url, payload, timeout_seconds):
    request = Request(url=url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json", "Accept": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            value = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        # Do not persist an error body containing the request or upstream credentials.
        raise RequestFailure(f"http_{exc.code}") from None
    except (URLError, TimeoutError, OSError):
        raise RequestFailure("connection_or_timeout") from None
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise RequestFailure("invalid_json") from None
    if not isinstance(value, dict):
        raise RequestFailure("response_not_object")
    return value


def analyze_case(base_url, complaint, timeout_seconds, rule_results=None):
    payload = {"complaint": complaint, "ruleResults": rule_results or []}
    started = time.perf_counter()
    response = post_json(base_url.rstrip("/") + ANALYZE_PATH, payload, timeout_seconds)
    return response, (time.perf_counter() - started) * 1000


def prepare_dataset(options):
    data_dir = options.data_dir or REPO_ROOT / "data" / ("goldenset" if options.dataset == "goldenset" else "dev")
    dataset = load_dataset(data_dir, options.dataset)
    other_dir = Path(options.overlap_data_dir) if options.overlap_data_dir else REPO_ROOT / "data" / (
        "dev" if dataset.schema == "goldenset" else "goldenset")
    other_schema = "dev" if dataset.schema == "goldenset" else "goldenset"
    other = load_dataset(other_dir, other_schema)
    overlap = check_disjoint(dataset.cases, other.cases)
    overlap.update(other_dataset_sha256=other.digest, other_data_dir=str(other_dir))
    if not overlap["passed"]:
        raise ValueError("dev/gold overlap detected: " + json.dumps(overlap, ensure_ascii=False))
    # Validate complete datasets BEFORE selecting a small evaluation subset.
    cases = dataset.cases
    if options.case_ids:
        wanted = set(options.case_ids)
        missing = wanted - {case["case_id"] for case in cases}
        if missing:
            raise ValueError("unknown case_id: " + ", ".join(sorted(missing)))
        cases = [case for case in cases if case["case_id"] in wanted]
    if options.limit is not None:
        if options.limit < 1:
            raise ValueError("--limit must be positive")
        cases = cases[:options.limit]
    return dataset, cases, overlap


def evaluate(options, transport=None):
    dataset, cases, overlap = prepare_dataset(options)
    if options.write_target_template:
        destination = Path(options.write_target_template)
        destination.parent.mkdir(parents=True, exist_ok=True)
        write_target_template(dataset, destination)
        return {"template": str(destination), "cases": len(dataset.cases), "confirmed_targets": 0}, None, 0
    targets, target_artifact = read_targets(options.targets, dataset)
    backend_predictions, backend_artifact = read_backend_predictions(options.risk_predictions, dataset, options.mode)
    if options.risk_predictions and not options.targets:
        raise ValueError("--risk-predictions requires --targets")
    if options.checkpoint_file and options.predictions:
        raise ValueError("--checkpoint-file only supports live HTTP evaluation")
    if options.validate_only:
        return {"validated": True, "schema": dataset.schema, "cases": len(dataset.cases),
                "labels": sum(len(v) for v in dataset.labels.values()), "overlap": overlap,
                "supplemental_targets": target_artifact, "backend_predictions": backend_artifact}, None, 0
    if options.charts:
        from .charts import check_available
        check_available()
    rules = {}
    rule_sha256 = None
    if options.rule_results:
        rule_bytes = Path(options.rule_results).read_bytes()
        rule_sha256 = hashlib.sha256(rule_bytes).hexdigest()
        rules = json.loads(rule_bytes)
        if not isinstance(rules, dict):
            raise ValueError("rule-results must map case_id to Backend RiskTagResult arrays")
    if options.mode == "llm" and options.rule_results:
        raise ValueError("--rule-results is only valid with --mode rule_llm")
    # Fail before the first request if any condition is missing or malformed.
    payloads = {case["case_id"]: build_payload(case, options.mode, rules.get(case["case_id"])) for case in cases}
    replay = read_predictions(options.predictions) if options.predictions else None
    if replay is not None and set(replay) - {case["case_id"] for case in dataset.cases}:
        raise ValueError("prediction file contains unknown dataset case_ids")
    transport = transport or post_json
    checkpoint = Path(options.checkpoint_file) if options.checkpoint_file else None
    if checkpoint:
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        with checkpoint.open("x", encoding="utf-8"):
            pass
    rows, case_rows, records = [], [], []
    for index, case in enumerate(cases):
        case_id = case["case_id"]
        payload = payloads[case_id]
        record = {"case_id": case_id, "mode": options.mode, "attempt": 1,
                  "input_sha256": json_hash(payload), "complaint_sha256": json_hash(payload["complaint"]),
                  "input_hash_origin": "reconstructed_for_replay" if replay is not None else "captured_request",
                  "source_provenance_verified": replay is None,
                  "response": None, "request_success": 0, "error_code": "", "latency_ms": None}
        tags = {}
        started = time.perf_counter()
        try:
            if replay is not None:
                if case_id not in replay:
                    raise RequestFailure("missing_prediction")
                source = replay[case_id]
                if source.get("mode", options.mode) != options.mode:
                    raise ContractError("prediction_mode_mismatch")
                if source.get("input_sha256", record["input_sha256"]) != record["input_sha256"]:
                    raise ContractError("prediction_input_hash_mismatch")
                if source.get("complaint_sha256", record["complaint_sha256"]) != record["complaint_sha256"]:
                    raise ContractError("prediction_complaint_hash_mismatch")
                # Resaving an unverified replay adds evaluator-derived hashes, not
                # new evidence about the original producer's actual inference input.
                record["source_provenance_verified"] = (
                    all(key in source for key in ("mode", "input_sha256", "complaint_sha256"))
                    and source.get("source_provenance_verified", True) is True
                )
                failed_source = source.get("request_success", 1) != 1
                response = source.get("response")
                try:
                    json.dumps(response, allow_nan=False)
                except (ValueError, TypeError):
                    if not failed_source:
                        raise ContractError("response_not_json_serializable") from None
                    response = None
                    record["recorded_response_sanitized"] = True
                record["response"] = response
                snapshot = source.get("rag_snapshot_id")
                if snapshot is not None and not isinstance(snapshot, str):
                    if not failed_source:
                        raise ContractError("invalid_rag_snapshot_id")
                    snapshot = None
                record["rag_snapshot_id"] = snapshot
                latency = source.get("latency_ms")
                if latency is not None and (type(latency) not in (int, float) or not math.isfinite(latency) or latency < 0):
                    if not failed_source:
                        raise ContractError("invalid_latency")
                    latency = None
                record["latency_ms"] = latency
                if failed_source:
                    raise RecordedFailure(source.get("error_code"))
            else:
                response = transport(options.base_url.rstrip("/") + ANALYZE_PATH, payload, options.timeout)
                record["latency_ms"] = (time.perf_counter() - started) * 1000
            try:
                json.dumps(response, allow_nan=False)
            except (ValueError, TypeError):
                raise ContractError("response_not_json_serializable") from None
            record["response"] = response
            tags = prediction_tags(response)
            record["risk_input"] = risk_input(response, payload["ruleResults"])
            record["risk_input_sha256"] = json_hash(record["risk_input"])
            record["request_success"] = 1
        except ContractError as exc:
            record["error_code"] = "contract:" + str(exc)
        except RecordedFailure as exc:
            record["error_code"] = exc.code
        except RequestFailure as exc:
            record["error_code"] = "request:" + str(exc)
        except (TimeoutError, OSError):
            record["error_code"] = "request:connection_or_timeout"
        except Exception:
            record["error_code"] = "request:unexpected_error"
        if replay is None and record["latency_ms"] is None:
            record["latency_ms"] = (time.perf_counter() - started) * 1000
        # Even parseable non-object replies may be retained, but never turned into tags.
        records.append(record)
        if checkpoint:
            with checkpoint.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        metadata = record["response"].get("metadata", {}) if isinstance(record["response"], dict) else {}
        model = metadata.get("modelName", "") if isinstance(metadata, dict) else ""
        mismatches = 0
        for code in BACKEND_CODES:
            gold = dataset.labels[case_id][code]
            tag = tags.get(code) if record["request_success"] else None
            state = tag["state"] if tag else ""
            match = int(bool(tag) and gold["status"] == state)
            in_scope = code in EVALUATED_CODES
            mismatches += int(in_scope and tag is not None and not match)
            rows.append({"case_id": case_id, "code": code, "risk_factor": gold["risk_factor"],
                         "gold_state": gold["status"], "predicted_state": state, "state_match": match,
                         "evaluation_in_scope": int(in_scope),
                         "context_subtypes": target_subtypes(targets, case_id, code),
                         "scope_exclusion_reason": "" if in_scope else "history_not_supplied",
                         **evidence_columns(gold, tag, payload["complaint"]),
                         "gold_reason": gold.get("reason", ""), "predicted_reason": tag.get("reason", "") if tag else "",
                         "confidence": tag.get("confidence") if tag else None,
                         "severity": tag.get("severity") if tag else None,
                         "repeatCount": tag.get("repeatCount") if tag else None,
                         "review_required": gold.get("review_required", ""),
                         "review_group": gold["review_group"], "label_origin": gold.get("label_origin", ""),
                         "message_text": case["message_text"], "model_name": model,
                         "history_available": case.get("history_available", ""),
                         "history_context": case.get("history_context", ""),
                         "latency_ms": record["latency_ms"], "request_success": record["request_success"],
                         "error": record["error_code"]})
        case_rows.append({"case_id": case_id, "message_text": case["message_text"],
                          "request_success": record["request_success"],
                          "error": record["error_code"], "model_name": model,
                          "latency_ms": record["latency_ms"],
                          "mismatch_count": mismatches if record["request_success"] else None,
                          "all_evaluated_states_match": int(bool(record["request_success"]) and mismatches == 0)})
        if not record["request_success"] and options.stop_on_error:
            break
        if replay is None and index + 1 < len(cases) and options.sleep:
            time.sleep(options.sleep)
    manifest = build_manifest(dataset, cases, records, options, overlap, rule_sha256=rule_sha256)
    backend_capture = getattr(options, 'backend_capture', None)
    if backend_capture:
        manifest['backend_capture'] = {**backend_capture['manifest'], 'prediction_view': backend_capture['view'],
                                       'journal_path': backend_capture['journal_path']}
        manifest['evaluation']['input_scope'] = backend_capture['manifest']['input_scope']
        manifest['evaluation']['evidence_input'] = 'original_golden_complaint; actual_masked_model_input_unavailable'
        if backend_capture['view'] == 'final':
            for row in rows:
                row.update(evidence_evaluable=0, evidence_exclusion_reason='backend_final_evidence_unavailable',
                           evidence_match='NOT_EVALUABLE')
    if checkpoint:
        manifest["checkpoint"] = {"path": str(checkpoint), "sha256": file_hash(checkpoint)}
    manifest["supplemental_targets"] = target_artifact
    manifest["backend_risk_predictions"] = backend_artifact
    if target_artifact:
        manifest["evaluation"]["supplemental_targets_sha256"] = target_artifact["sha256"]
        manifest["evaluation"]["context_subtype_policy"] = "human_confirmed_overlapping_cohorts_v1"
        manifest["evaluation"]["context_subtype_vocabulary"] = {code: list(values) for code, values in SUBTYPES.items()}
        if any(row["context_subtypes"] for row in rows):
            manifest["not_evaluated"].pop("context_subtype", None)
    risk_results = risk_rows(targets, records, backend_predictions, [case["case_id"] for case in cases])
    if backend_capture:
        from .backend import captured_risk_rows
        risk_results = (captured_risk_rows(targets, backend_capture['states'], [case['case_id'] for case in cases])
                        if backend_capture['view'] == 'final' else [])
    metrics = compute_metrics(rows, len(cases), options.policies)
    cohort_rows = list(rows)
    attempted = {record["case_id"] for record in records}
    for case in cases:
        if case["case_id"] not in attempted:
            cohort_rows.extend({"code": code, "request_success": 0,
                                "context_subtypes": target_subtypes(targets, case["case_id"], code)}
                               for code in SUBTYPES)
    metrics["context_subtypes"] = subtype_metrics(cohort_rows, options.policies)
    metrics["final_risk"] = risk_metrics(risk_results)
    if backend_capture:
        metrics['backend_prediction_distribution'] = {
            level: sum(state['summary']['riskLevel'] == level for state in backend_capture['states'].values())
            for level in ('LOW', 'MEDIUM', 'HIGH', 'EMERGENCY')}
        if backend_capture['view'] == 'final':
            metrics['evidence']['status'] = 'not_evaluated_final_evidence_unavailable'
    metrics['versions'] = {key: manifest[key] for key in ('models', 'prompt', 'rule', 'dataset', 'rag', 'codebook')}
    if backend_capture:
        metrics['versions']['backend'] = backend_capture['manifest']
        if metrics['final_risk']['successful_cases']:
            manifest['not_evaluated'].pop('final_risk', None)
    if backend_artifact and metrics["final_risk"]["successful_cases"]:
        manifest["not_evaluated"].pop("final_risk", None)
    metrics["review_groups"] = {
        group: compute_metrics([row for row in rows if row["review_group"] == group],
                               len({row["case_id"] for row in rows if row["review_group"] == group}), options.policies)
        for group in sorted({row["review_group"] for row in rows})
    }
    metrics["coverage"] = {"requested_cases": len(cases), "processed_cases": len(records),
                           "succeeded_cases": sum(r["request_success"] for r in records),
                           "failed_cases": sum(not r["request_success"] for r in records),
                           "not_attempted_cases": len(cases) - len(records),
                           "failure_codes": {code: sum(r["error_code"] == code for r in records)
                                             for code in sorted({r["error_code"] for r in records if r["error_code"]})}}
    if backend_capture:
        not_started = set(backend_capture['manifest']['not_started_case_ids'])
        for row in (*rows, *case_rows):
            row['collection_attempted'] = int(row['case_id'] not in not_started)
        replay_coverage = dict(metrics['coverage'])
        attempted_count = len(cases) - len(not_started)
        failure_codes = dict(replay_coverage['failure_codes'])
        missing = failure_codes.get('request:missing_prediction', 0) - len(not_started)
        failure_codes.pop('request:missing_prediction', None)
        if missing > 0:
            failure_codes['request:missing_prediction'] = missing
        metrics['coverage'].update(processed_cases=attempted_count, attempted_cases=attempted_count,
                                   failed_cases=attempted_count - replay_coverage['succeeded_cases'],
                                   not_attempted_cases=len(not_started), failure_codes=failure_codes,
                                   replay_processing=replay_coverage)
        metrics['coverage']['backend_capture'] = {
            key: backend_capture['manifest'][key]
            for key in ('selected_cases', 'captured_cases', 'model_success_cases', 'collection_stage_counts', 'incomplete_case_ids')}
    comparison = None
    comparison_failed = False
    if options.previous:
        try:
            comparison = compare_run(options.previous, manifest, rows, current_risk_rows=risk_results)
        except (ValueError, OSError, KeyError) as exc:
            comparison = {"status": "incompatible", "reason": str(exc)}
            comparison_failed = True
    directory = save_run(options.report_dir, options.run_version, manifest, metrics, rows, case_rows, records,
                         comparison, risk_results=risk_results, charts=options.charts)
    status = 1 if (any(not record["request_success"] for record in records) or comparison_failed
                   or metrics["final_risk"]["failed_cases"]
                   or manifest.get("charts", {}).get("status") == "failed") else 0
    return metrics, directory, status
