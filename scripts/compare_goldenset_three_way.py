#!/usr/bin/env python3
"""Compare three completed Golden Set evaluation runs without calling models.

Only immutable evaluator output directories are accepted. Never compute a score
for an absent run or treat Backend's rule-conditioned LLM as LLM-only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
from collections import Counter
from pathlib import Path

from scripts.evaluation.data import EVALUATED_CODES
from scripts.evaluation.metrics import compute_metrics
from scripts.evaluation.reporting import read_result_rows

RUN_NAMES = ("rule", "llm", "service")
POLICIES = ("present", "present_boundary")


def _read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_run(path, *, name):
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError(f"{name}: unsupported manifest schema")
    dataset = manifest.get("dataset") or {}
    digest = dataset.get("sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"{name}: missing dataset hash")
    if manifest.get("dataset_schema") != "goldenset":
        raise ValueError(f"{name}: must use the golden set")
    if not isinstance(manifest.get("artifacts"), dict):
        raise ValueError(f"{name}: missing artifact hashes")
    for filename in ("results.csv", "cases.csv"):
        expected = manifest["artifacts"].get(filename)
        if not expected or expected != _hash(path / filename):
            raise ValueError(f"{name}: {filename} hash mismatch")
    mode = manifest.get("mode")
    if name == "llm" and (mode != "llm" or manifest.get("rule", {}).get("source") != "empty_rule_results"):
        raise ValueError("LLM Only must be a true empty-rule-results llm run")
    if name == "service" and mode != "rule_llm" and not manifest.get("backend_capture"):
        raise ValueError("service must be rule_llm or actual Backend capture")
    if name == "rule" and (not manifest.get("backend_capture") or
                           manifest["backend_capture"].get("prediction_view") != "rule"):
        raise ValueError("Rule Only must come from actual Backend rule capture")
    rows = read_result_rows(path / "results.csv")
    cases = _read_csv(path / "cases.csv")
    requested = int(manifest.get("requested_cases", 0))
    if requested != 200:
        raise ValueError(f"{name}: expected 200 requested cases, found {requested}")
    ids = [c["case_id"] for c in cases]
    if len(ids) != 200 or len(set(ids)) != 200:
        raise ValueError(f"{name}: cases.csv must contain 200 unique case IDs")
    keys = [(r["case_id"], r["code"]) for r in rows]
    if len(keys) != len(set(keys)) or set(r["case_id"] for r in rows) != set(ids):
        raise ValueError(f"{name}: duplicate rows or missing case IDs")
    for case_id in ids:
        scoped = {r["code"] for r in rows if r["case_id"] == case_id and r["evaluation_in_scope"]}
        if scoped != set(EVALUATED_CODES):
            raise ValueError(f"{name}: incomplete evaluated tags")
    return {"name": name, "path": str(path), "manifest": manifest, "rows": rows,
            "cases": cases, "digest": digest,
            "successful": {c["case_id"] for c in cases if c["request_success"] == "1"}}


def _paired_metrics(run, paired):
    rows = [r for r in run["rows"] if r["case_id"] in paired and r["request_success"]]
    return compute_metrics(rows, len(paired), POLICIES)


def _f1(run, paired, policy):
    return _paired_metrics(run, paired)["binary"][policy]["macro_f1"]


def _bootstrap_difference(left, right, paired, policy, rounds=1000, seed=2026):
    """Paired case-level bootstrap, preserving within-case tag correlation."""
    rng = random.Random(seed)
    ids = sorted(paired)
    lmap = {i: [r for r in left["rows"] if r["case_id"] == i and r["request_success"]] for i in ids}
    rmap = {i: [r for r in right["rows"] if r["case_id"] == i and r["request_success"]] for i in ids}
    deltas = []
    for _ in range(rounds):
        sampled = [rng.choice(ids) for _ in ids]
        lrows, rrows = [], []
        for idx, case_id in enumerate(sampled):
            # The metric function groups rows by case_id, so each resample receives
            # a fresh synthetic case_id while preserving all seven tag labels.
            lrows.extend({**row, "case_id": str(idx)} for row in lmap[case_id])
            rrows.extend({**row, "case_id": str(idx)} for row in rmap[case_id])
        a = compute_metrics(lrows, len(sampled), (policy,))["binary"][policy]["macro_f1"]
        b = compute_metrics(rrows, len(sampled), (policy,))["binary"][policy]["macro_f1"]
        if a is not None and b is not None:
            deltas.append(b - a)
    deltas.sort()
    if not deltas:
        return None
    return [deltas[int(0.025 * (len(deltas) - 1))],
            deltas[int(0.975 * (len(deltas) - 1))]]


def compare(runs, *, bootstrap_rounds=1000):
    if len({r["digest"] for r in runs.values()}) != 1:
        raise ValueError("the three runs do not use the same Golden Set")
    all_ids = [set(c["case_id"] for c in r["cases"]) for r in runs.values()]
    if len({tuple(sorted(ids)) for ids in all_ids}) != 1:
        raise ValueError("case IDs differ between three runs")
    paired = set.intersection(*(r["successful"] for r in runs.values()))
    if not paired:
        raise ValueError("no cases succeeded in all three runs")
    gold = {}
    for name, run in runs.items():
        current = {(r["case_id"], r["code"]): r["gold_state"] for r in run["rows"]
                   if r["case_id"] in paired and r["evaluation_in_scope"]}
        if gold and gold != current:
            raise ValueError(f"{name}: golden tag labels differ")
        gold = current
    by_run = {}
    for name, run in runs.items():
        m = _paired_metrics(run, paired)
        latencies = []
        for case in run["cases"]:
            if case["case_id"] in paired and case.get("latency_ms"):
                try:
                    latency = float(case["latency_ms"])
                except ValueError:
                    continue
                if math.isfinite(latency) and latency >= 0:
                    latencies.append(latency)
        by_run[name] = {
            "requested_cases": 200, "successful_cases": len(run["successful"]),
            "common_paired_cases": len(paired),
            "macro": {p: {k: m["binary"][p][k] for k in
                          ("macro_precision", "macro_recall", "macro_f1")} for p in POLICIES},
            "micro": {p: {k: m["binary"][p]["micro"][k] for k in
                          ("precision", "recall", "f1")} for p in POLICIES},
            "per_tag_f1": {p: {code: m["per_tag"][code]["binary"][p]["f1"]
                              for code in EVALUATED_CODES} for p in POLICIES},
            "latency_ms": {"count": len(latencies),
                           "mean": statistics.mean(latencies) if latencies else None,
                           "median": statistics.median(latencies) if latencies else None},
            "manifest_mode": run["manifest"]["mode"],
        }
    comparisons = {}
    for left, right in (("rule", "llm"), ("llm", "service"), ("rule", "service")):
        comparisons[f"{left}_vs_{right}"] = {
            p: {
                "macro_f1_difference": by_run[right]["macro"][p]["macro_f1"] -
                                       by_run[left]["macro"][p]["macro_f1"],
                "paired_case_bootstrap_95pct_ci": (
                    _bootstrap_difference(runs[left], runs[right], paired, p, bootstrap_rounds)
                    if bootstrap_rounds else None),
            } for p in POLICIES
        }
    return {
        "status": "descriptive_not_controlled_ab",
        "dataset_sha256": next(iter(runs.values()))["digest"],
        "common_paired_cases": len(paired),
        "complete_200_case_comparison": len(paired) == 200,
        "tag_scope": list(EVALUATED_CODES),
        "excluded": ["REPEAT"],
        "runs": by_run,
        "comparisons": comparisons,
        "limitations": [
            "Model, prompt, RAG, masking, SDK and scoring-engine settings must be checked independently before causal claims.",
            "Rule-only/Backend final captures can use different input preprocessing than direct AI calls.",
            "Latency may include different processing stages; do not label it an apples-to-apples speed comparison.",
            "Risk-level comparison requires independently captured Backend Risk Engine output and confirmed risk targets.",
            "No LLM API calls are performed by this script.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline Rule/LLM/Service Golden Set comparison")
    parser.add_argument("--rule-run", required=True)
    parser.add_argument("--llm-run", required=True)
    parser.add_argument("--service-run", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--bootstrap-rounds", type=int, default=1000)
    args = parser.parse_args(argv)
    if not 0 <= args.bootstrap_rounds <= 10000:
        parser.error("--bootstrap-rounds must be between 0 and 10000")
    if Path(args.output).exists():
        parser.error("output already exists; choose a new filename")
    runs = {name: load_run(getattr(args, name + "_run"), name=name) for name in RUN_NAMES}
    report = compare(runs, bootstrap_rounds=args.bootstrap_rounds)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({"comparison_status": report["status"],
                      "common_paired_cases": report["common_paired_cases"],
                      "output": str(path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
