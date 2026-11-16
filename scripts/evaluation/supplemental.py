"""Human-reviewed targets and Backend Risk Engine exports; never infer gold labels."""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter
from pathlib import Path

from .metrics import binary_metrics, confusion, rate

LEVELS = ("LOW", "MEDIUM", "HIGH", "EMERGENCY")
SUBTYPES = {
    "PRIVACY": ("PII_INCLUDED", "MISUSE_OR_THIRD_PARTY_REQUEST", "OTHER"),
    "THREAT": ("COERCIVE_PRESSURE", "PHYSICAL_HARM", "OTHER"),
}
TARGET_COLUMNS = ("case_id", "dataset_sha256", "review_status", "risk_level", "is_legitimate",
                  "privacy_context_subtypes", "threat_context_subtypes")


def snapshot(path):
    raw = Path(path).read_bytes()
    return raw, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def write_target_template(dataset, destination):
    """Refuse overwriting annotations. All human decisions remain blank/pending."""
    with Path(destination).open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=TARGET_COLUMNS)
        writer.writeheader()
        writer.writerows({"case_id": case["case_id"], "dataset_sha256": dataset.digest,
                          "review_status": "PENDING"} for case in dataset.cases)


def read_targets(path, dataset):
    if not path:
        return {}, None
    raw, artifact = snapshot(path)
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))
    if reader.fieldnames != list(TARGET_COLUMNS):
        raise ValueError("targets require exactly the documented columns in template order")
    result = {}
    known = {case["case_id"] for case in dataset.cases}
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("malformed target CSV row")
        row = {key: value.strip() for key, value in row.items()}
        case_id = row["case_id"]
        if case_id not in known or case_id in result or row["dataset_sha256"] != dataset.digest:
            raise ValueError("targets have unknown/duplicate cases or a different dataset hash")
        if row["review_status"] not in ("PENDING", "CONFIRMED"):
            raise ValueError("target review_status must be PENDING or CONFIRMED")
        if row["risk_level"] not in ("", *LEVELS) or row["is_legitimate"] not in ("", "TRUE", "FALSE"):
            raise ValueError("invalid risk or legitimate-complaint target")
        for code, allowed in SUBTYPES.items():
            value = row[code.lower() + "_context_subtypes"]
            values = value.split(";") if value else []
            if len(values) != len(set(values)) or set(values) - set(allowed):
                raise ValueError("invalid or duplicate context subtype")
        result[case_id] = row
    artifact["confirmed_cases"] = sum(r["review_status"] == "CONFIRMED" for r in result.values())
    artifact["pending_cases"] = sum(r["review_status"] == "PENDING" for r in result.values())
    return result, artifact


def read_backend_predictions(path, dataset, mode):
    if not path:
        return {}, None
    raw, artifact = snapshot(path)
    def invalid_number(value):
        raise ValueError("backend export only allows finite integer JSON numbers")
    value = json.loads(raw, parse_constant=invalid_number, parse_float=invalid_number)
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
        raise ValueError("backend export requires schema_version=1 object")
    if set(value) != {"schema_version", "dataset_sha256", "mode", "risk_engine", "predictions"}:
        raise ValueError("unexpected fields in backend export")
    if value.get("dataset_sha256") != dataset.digest or value.get("mode") != mode:
        raise ValueError("backend export dataset/mode differs from this evaluation")
    engine = value.get("risk_engine")
    if not isinstance(engine, dict) or not isinstance(engine.get("version"), str) or not engine["version"].strip():
        raise ValueError("backend export requires risk_engine.version")
    if set(engine) != {"version", "source_commit"} or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}", engine["version"]):
        raise ValueError("risk_engine requires only a short version identifier and source_commit")
    commit = engine.get("source_commit")
    if not isinstance(commit, str) or len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("backend export requires the exact engine source_commit")
    predictions = value.get("predictions")
    if not isinstance(predictions, list):
        raise ValueError("backend predictions must be an array")
    known, result = {case["case_id"] for case in dataset.cases}, {}
    for prediction in predictions:
        if not isinstance(prediction, dict):
            raise ValueError("backend prediction must be an object")
        if set(prediction) != {"case_id", "risk_level", "risk_input_sha256"}:
            raise ValueError("unexpected fields in backend prediction")
        case_id, digest = prediction.get("case_id"), prediction.get("risk_input_sha256")
        if not isinstance(case_id, str) or case_id not in known or case_id in result:
            raise ValueError("unknown or duplicate backend prediction case")
        if prediction.get("risk_level") not in LEVELS:
            raise ValueError("backend risk_level must be LOW/MEDIUM/HIGH/EMERGENCY")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("backend prediction requires risk_input_sha256")
        result[case_id] = prediction
    artifact["risk_engine"] = {key: engine[key] for key in ("version", "source_commit")}
    artifact["origin"] = "caller_supplied_backend_export; engine calculation is not reimplemented"
    return result, artifact


def risk_input(response, rule_results):
    return {"tags": response["tags"], "safetyFlags": response.get("safetyFlags"), "ruleResults": rule_results}


def target_subtypes(targets, case_id, code):
    target = targets.get(case_id, {})
    return target.get(code.lower() + "_context_subtypes", "") if target.get("review_status") == "CONFIRMED" else ""


def subtype_metrics(rows, policies):
    result = {}
    for code, values in SUBTYPES.items():
        result[code] = {}
        for subtype in values:
            cohort = [r for r in rows if r["code"] == code
                      and subtype in r.get("context_subtypes", "").split(";")]
            successful = [r for r in cohort if r["request_success"]]
            result[code][subtype] = {
                "annotated_labels": len(cohort), "successful_labels": len(successful),
                "failed_labels": len(cohort) - len(successful),
                "confusion_matrix": confusion(successful),
                "binary": {p: binary_metrics(successful, p) for p in policies},
            }
    return {"kind": "gold_context_cohorts_not_subtype_prediction_accuracy",
            "overlapping_cohorts": True, "per_tag": result}


def risk_rows(targets, records, predictions, selected_ids):
    captured = {r["case_id"]: r for r in records}
    rows = []
    for case_id in selected_ids:
        target = targets.get(case_id, {})
        if target.get("review_status") != "CONFIRMED" or not target.get("risk_level"):
            continue
        record, prediction = captured.get(case_id), predictions.get(case_id)
        error = ("not_attempted" if record is None else "tagging_failed" if not record["request_success"]
                 else "missing_backend_prediction" if prediction is None
                 else "backend_input_hash_mismatch" if prediction["risk_input_sha256"] != record["risk_input_sha256"] else "")
        rows.append({"case_id": case_id, "gold_risk_level": target["risk_level"],
                     "predicted_risk_level": prediction["risk_level"] if prediction and not error else "",
                     "is_legitimate": target["is_legitimate"], "success": int(not error), "error": error})
    return rows


def risk_metrics(rows):
    successful = [r for r in rows if r["success"]]
    matrix = {g: {p: 0 for p in LEVELS} for g in LEVELS}
    for row in successful:
        matrix[row["gold_risk_level"]][row["predicted_risk_level"]] += 1
    recalls = {}
    for level in ("HIGH", "EMERGENCY"):
        support = sum(matrix[level].values())
        recalls[level] = {"correct": matrix[level][level], "support": support,
                          "recall": rate(matrix[level][level], support)}
    severe = [r for r in successful if r["gold_risk_level"] in ("HIGH", "EMERGENCY")]
    legitimate = [r for r in successful if r["is_legitimate"] == "TRUE"]
    over = [r for r in legitimate if LEVELS.index(r["predicted_risk_level"]) > LEVELS.index(r["gold_risk_level"])]
    emergency_misses = [r["case_id"] for r in successful
                        if r["gold_risk_level"] == "EMERGENCY" and r["predicted_risk_level"] != "EMERGENCY"]
    return {"status": "evaluated" if successful else "not_evaluated", "annotated_cases": len(rows),
            "successful_cases": len(successful), "failed_cases": len(rows) - len(successful),
            "failure_codes": dict(Counter(r["error"] for r in rows if r["error"])),
            "confusion_matrix": matrix, "class_recall": recalls,
            "high_or_emergency_recall": rate(sum(r["predicted_risk_level"] in ("HIGH", "EMERGENCY") for r in severe), len(severe)),
            "emergency_missed_case_ids": emergency_misses,
            "legitimate_overestimation": {"overestimated": len(over), "denominator": len(legitimate),
                                          "rate": rate(len(over), len(legitimate)), "policy": "predicted_level > confirmed_gold_level"}}
