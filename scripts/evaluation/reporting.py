"""Versioned artifacts and comparison on the same successful cases."""
from __future__ import annotations

import csv
import fcntl
import json
import shutil
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .data import EVALUATED_CODES, file_hash, json_hash
from .metrics import EVIDENCE_POLICY, build_tag_metrics, compute_metrics

REPO_ROOT = Path(__file__).resolve().parents[2]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_csv(path, rows, fieldnames=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = list(fieldnames or [])
    for row in rows:
        for key in row:
            if key not in columns:
                columns.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns or ["case_id"])
        writer.writeheader()
        writer.writerows(rows)


def git_info():
    try:
        sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, stderr=subprocess.DEVNULL).decode().strip()
        dirty = bool(subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=REPO_ROOT,
            stderr=subprocess.DEVNULL,
        ).strip())
        return {"sha": sha, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"sha": None, "dirty": None}


def build_manifest(dataset, cases, records, options, overlap, *, rule_sha256=None):
    def artifact(path, version=None):
        path = Path(path)
        digest = file_hash(path) if path.is_file() else None
        return {"version": version or ("sha256:" + digest if digest else "unknown"),
                "sha256": digest, "path": str(path)}

    models, settings, server_provenance = Counter(), {}, {}
    missing_settings = 0
    for record in records:
        response = record.get("response")
        metadata = response.get("metadata", {}) if isinstance(response, dict) else {}
        if not isinstance(metadata, dict):
            metadata = {}
        if isinstance(metadata.get("modelName"), str):
            models[metadata["modelName"]] += 1
        # Legacy temperature=0 metadata is not evidence of the actual SDK call.
        actual = metadata.get("generationSettings")
        if isinstance(actual, dict):
            settings[json_hash(actual)] = actual
        else:
            missing_settings += 1
        provenance = metadata.get("evaluationProvenance")
        if isinstance(provenance, dict):
            server_provenance[json_hash(provenance)] = provenance
    prompt = artifact(REPO_ROOT / "app/rag/prompt.py", options.prompt_version)
    prompt["source"] = "local_checkout; not proof of remote deployment"
    rag = artifact(REPO_ROOT / "app/rag/retriever.py", options.rag_version)
    rag["source"] = "local_retriever_source; corpus/index hash requires server provenance"
    rule = ({"version": options.rule_version or "sha256:" + rule_sha256,
             "sha256": rule_sha256, "path": str(options.rule_results)} if options.rule_results
            else {"version": options.rule_version or "none", "sha256": json_hash([]), "source": "empty_rule_results"})
    return {
        "schema_version": 1, "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": options.mode, "execution": "replay" if options.predictions else "http",
        "git": git_info(), "dataset_schema": dataset.schema,
        "dataset": {"version": options.dataset_version or "sha256:" + dataset.digest,
                    "sha256": dataset.digest, "files": dataset.hashes},
        "prompt": prompt, "rule": rule, "rag": rag,
        "codebook": {"version": options.codebook_version, "sha256": file_hash(options.codebook_file)
                     if options.codebook_file else None,
                     "source": "caller_declaration; codebook file not bundled"},
        "evaluator_source_hashes": {str(path.relative_to(REPO_ROOT)): file_hash(path)
                                    for path in sorted((REPO_ROOT / "scripts/evaluation").glob("*.py"))},
        "entrypoint_sha256": file_hash(REPO_ROOT / "scripts/evaluate_risk_prompt_updated.py"),
        "prediction_input": artifact(options.predictions) if options.predictions else None,
        "models": dict(models), "actual_generation_settings": list(settings.values()),
        "generation_settings_source": "response.metadata.generationSettings",
        "generation_settings_note": "Explicit SDK parameters only; omitted options use provider defaults. Replay metadata is supplied by the prediction producer.",
        "records_without_generation_settings": missing_settings,
        "server_provenance": list(server_provenance.values()),
        "case_ids": [case["case_id"] for case in cases], "requested_cases": len(cases),
        "processed_cases": len(records), "overlap_check": overlap,
        "evaluation": {"codes": EVALUATED_CODES, "excluded_codes": {"REPEAT": "history_not_supplied"},
                       "input_scope": "complaint_only; no structured history or regulation_context",
                       "positive_policies": options.policies, "gold_unknown_binary": "exclude",
                       "predicted_unknown_binary": "non_positive", "zero_division": 0,
                       "empty_denominator": None, "confusion_axes": "rows=gold, columns=predicted",
                       "evidence_policy": EVIDENCE_POLICY},
        "not_evaluated": {
            "final_risk": "Backend Risk Engine contract and gold risk levels required",
            "context_subtype": "goldenset subtype annotations and shared codebook required",
            "severity_repeatCount_safetyFlags": "predictions preserved; no gold targets supplied",
            "repeat": "structured history input contract required",
            "controlled_ab": "#25 must freeze RAG snapshots and generation settings; mode alone is insufficient",
        },
    }


def read_result_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    integer_fields = ("request_success", "evaluation_in_scope", "state_match", "evidence_evaluable",
                      "predicted_span_count", "grounded_span_count")
    for row in rows:
        for field in integer_fields:
            row[field] = int(row[field])
    return rows


def compare_run(previous_dir, manifest, rows):
    previous_dir = Path(previous_dir)
    previous = json.loads((previous_dir / "manifest.json").read_text(encoding="utf-8"))
    if not isinstance(previous, dict):
        raise ValueError("previous manifest must be an object")
    if previous.get("schema_version") != 1:
        raise ValueError("unsupported previous manifest schema")
    for field in ("dataset", "evaluation", "artifacts"):
        if not isinstance(previous.get(field), dict):
            raise ValueError(f"previous manifest {field} must be an object")
    for value in (previous["dataset"].get("sha256"), previous["artifacts"].get("results.csv")):
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("previous manifest requires valid dataset and results.csv hashes")
    if previous["dataset"]["sha256"] != manifest["dataset"]["sha256"] or previous["evaluation"] != manifest["evaluation"]:
        raise ValueError("previous run uses a different dataset or evaluation policy")
    expected_hash = previous.get("artifacts", {}).get("results.csv")
    if expected_hash != file_hash(previous_dir / "results.csv"):
        raise ValueError("previous results.csv hash does not match its manifest")
    old = read_result_rows(previous_dir / "results.csv")
    old_ok = {r["case_id"] for r in old if r["request_success"]}
    new_ok = {r["case_id"] for r in rows if r["request_success"]}
    paired = old_ok & new_ok
    before = compute_metrics([r for r in old if r["case_id"] in paired], len(paired), manifest["evaluation"]["positive_policies"])
    after = compute_metrics([r for r in rows if r["case_id"] in paired], len(paired), manifest["evaluation"]["positive_policies"])
    old_by_key = {(r["case_id"], r["code"]): r for r in old if r["case_id"] in paired and r["evaluation_in_scope"]}
    newly_wrong, corrected = [], []
    for row in rows:
        prior = old_by_key.get((row["case_id"], row["code"]))
        if prior is None:
            continue
        if prior["gold_state"] != row["gold_state"]:
            raise ValueError("gold states differ in previous results")
        change = {"case_id": row["case_id"], "code": row["code"], "gold_state": row["gold_state"],
                  "previous_state": prior["predicted_state"], "current_state": row["predicted_state"]}
        if prior["state_match"] and not row["state_match"]:
            newly_wrong.append(change)
        if not prior["state_match"] and row["state_match"]:
            corrected.append(change)
    def delta(new, old):
        return new - old if new is not None and old is not None else None
    policy_changes = {}
    for policy in manifest["evaluation"]["positive_policies"]:
        policy_changes[policy] = {
            "macro_precision_delta": delta(after["binary"][policy]["macro_precision"], before["binary"][policy]["macro_precision"]),
            "macro_recall_delta": delta(after["binary"][policy]["macro_recall"], before["binary"][policy]["macro_recall"]),
            "macro_f1_delta": delta(after["binary"][policy]["macro_f1"], before["binary"][policy]["macro_f1"]),
            "micro_precision_delta": delta(after["binary"][policy]["micro"]["precision"], before["binary"][policy]["micro"]["precision"]),
            "micro_recall_delta": delta(after["binary"][policy]["micro"]["recall"], before["binary"][policy]["micro"]["recall"]),
            "micro_f1_delta": delta(after["binary"][policy]["micro"]["f1"], before["binary"][policy]["micro"]["f1"]),
            "tag_f1_delta": {code: delta(after["per_tag"][code]["binary"][policy]["f1"],
                                         before["per_tag"][code]["binary"][policy]["f1"]) for code in EVALUATED_CODES},
        }
    return {"status": "compared", "controlled_ab": False, "previous_run": str(previous_dir),
            "paired_successful_case_ids": sorted(paired), "paired_cases": len(paired),
            "excluded_from_pairing": sorted((old_ok | new_ok) - paired),
            "newly_failed_cases": sorted(old_ok & {r["case_id"] for r in rows if not r["request_success"]}),
            "recovered_cases": sorted(new_ok & {r["case_id"] for r in old if not r["request_success"]}),
            "tag_exact_match_rate_delta": delta(after["tag_exact_match"]["rate"], before["tag_exact_match"]["rate"]),
            "all_tags_exact_match_rate_delta": delta(after["all_tags_exact_match"]["rate"], before["all_tags_exact_match"]["rate"]),
            "evidence_match_rate_delta": delta(after["evidence"]["match_rate"], before["evidence"]["match_rate"]),
            "before": before, "after": after, "changes": policy_changes,
            "newly_wrong": newly_wrong, "corrected": corrected}


def save_run(report_root, version, manifest, metrics, rows, cases, records, comparison=None):
    # Version labels are display values; never allow them to become path components.
    safe_version = "".join(c if c.isalnum() or c in "-_" else "_" for c in version)[:64] or "eval"
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "_" + safe_version + "_" + uuid4().hex[:8]
    directory = Path(report_root) / run_id
    directory.mkdir(parents=True, exist_ok=False)
    manifest["run_id"] = run_id
    failed = [case for case in cases if not case["request_success"]]
    mismatches = [r for r in rows if r["request_success"] and r["evaluation_in_scope"] and not r["state_match"]]
    files = {"results.csv": rows, "cases.csv": cases, "failures.csv": failed, "mismatches.csv": mismatches,
             "evidence_mismatches.csv": [r for r in rows if r["request_success"] and r["evaluation_in_scope"]
                                         and ((r["evidence_evaluable"] and r["evidence_match"] != "MATCH")
                                              or r["predicted_span_count"] > r["grounded_span_count"])],
             "core_mismatches.csv": [r for r in mismatches if r.get("review_required") == "NO"],
             "review_mismatches.csv": [r for r in mismatches if r.get("review_required") == "YES"],
             "tag_metrics.csv": build_tag_metrics(rows),
             "tag_metrics_core.csv": build_tag_metrics(rows, review_required="NO")}
    for name, content in files.items():
        fields = list(cases[0]) if name == "failures.csv" and cases else list(rows[0]) if "mismatches" in name and rows else None
        write_csv(directory / name, content, fields)
    write_json(directory / "metrics.json", metrics)
    core_rows = [r for r in rows if r.get("review_required") == "NO"]
    core = compute_metrics(core_rows, len(cases))
    review_rows = [r for r in rows if r.get("review_required") == "YES"
                   and r["evaluation_in_scope"] and r["request_success"]]
    succeeded = [case for case in cases if case["request_success"]]
    latencies = [case["latency_ms"] for case in succeeded if case["latency_ms"] is not None]
    summary = {"generated_at": manifest["generated_at"], "evaluation_mode": manifest["mode"],
               "cases_requested": manifest["requested_cases"], "cases_succeeded": len(cases) - len(failed),
               "cases_failed": len(failed), "cases_not_attempted": manifest["requested_cases"] - len(cases),
               "evaluated_codes": EVALUATED_CODES, "excluded_codes": ["REPEAT"],
               "model_names": manifest["models"], "manifest": "manifest.json",
               "average_latency_ms": sum(latencies) / len(latencies) if latencies else None,
               "silver": {"exact_state_accuracy": metrics["tag_exact_match"]["rate"],
                          "exact_state_matches": metrics["tag_exact_match"]["matched"],
                          "total_tag_comparisons": metrics["tag_exact_match"]["denominator"],
                          "state_mismatches": len(mismatches),
                          "perfect_evaluated_tag_cases": metrics["all_tags_exact_match"]["matched_cases"],
                          "perfect_evaluated_tag_case_rate": metrics["all_tags_exact_match"]["rate"],
                          "macro_present_f1": metrics["binary"].get("present", {}).get("macro_f1")},
               "core_review_required_no": {
                   "exact_state_accuracy": core["tag_exact_match"]["rate"],
                   "exact_state_matches": core["tag_exact_match"]["matched"],
                   "total_tag_comparisons": core["tag_exact_match"]["denominator"],
                   "state_mismatches": len(files["core_mismatches.csv"]),
                   "macro_present_f1": core["binary"]["present"]["macro_f1"],
                   "stable_cases": core["all_tags_exact_match"]["successful_complete_cases"],
                   "stable_perfect_cases": core["all_tags_exact_match"]["matched_cases"],
                   "stable_perfect_case_rate": core["all_tags_exact_match"]["rate"]},
               "human_review": {"review_cases": len({r["case_id"] for r in review_rows}),
                                "review_tag_comparisons": len(review_rows),
                                "review_mismatches": len(files["review_mismatches.csv"])},
               "note": "See metrics.json for policies, denominators and review groups; dev_stable_ai is not teacher-confirmed."}
    write_json(directory / "summary.json", summary)
    with (directory / "predictions.jsonl").open("w", encoding="utf-8") as stream:
        for record in records:
            stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
    if comparison:
        write_json(directory / "diff.json", comparison)
        write_csv(directory / "newly_wrong.csv", comparison.get("newly_wrong", []),
                  ["case_id", "code", "gold_state", "previous_state", "current_state"])
    manifest["artifacts"] = {p.name: file_hash(p) for p in directory.iterdir() if p.is_file()}
    write_json(directory / "manifest.json", manifest)
    # Keep original fixed filenames as a latest snapshot for existing consumers.
    with (Path(report_root) / ".publish.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            for name in (*files, "summary.json", "metrics.json"):
                shutil.copyfile(directory / name, Path(report_root) / name)
            write_json(Path(report_root) / "latest.json", {"run_id": run_id, "directory": str(directory.resolve())})
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    return directory
