#!/usr/bin/env python3
"""One command for core20, guardrails, safe logs and optional inference regression (#33)."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.evaluate_risk_prompt_updated import build_parser as evaluation_parser
from scripts.evaluation.contracts import build_payload, read_predictions
from scripts.evaluation.regression import assess_records, load_core_suite
from scripts.evaluation.reporting import REPO_ROOT, git_info, write_csv, write_json
from scripts.evaluation.runner import evaluate, prepare_dataset
from scripts.validate_operational_logs import check_logs

SUITE = REPO_ROOT / "tests/fixtures/regression_core20.json"
OFFLINE_TESTS = ("tests/test_regression_core20.py", "tests/test_guardrails.py", "tests/test_operational_logging.py")
OUTCOMES = ("passed", "failed", "skipped", "xfailed", "xpassed")


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--predictions", type=Path, help="Saved dev inference JSON/JSONL; no model calls")
    source.add_argument("--base-url", help="Explicit live AI origin; makes 20 paid model/RAG requests")
    parser.add_argument("--mode", choices=("llm", "rule_llm"), default="llm")
    parser.add_argument("--rule-results", type=Path)
    parser.add_argument("--report-dir", type=Path, default=Path("reports/regression"))
    parser.add_argument("--run-version", default="core20-v1")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--log-file", type=Path, help="Validate existing JSONL without echoing its contents")
    parser.add_argument("--require-complete-guardrails", action="store_true", help="Fail while any guardrail is skipped or xfailed")
    return parser


def evaluation_options(args, suite):
    command = ["--dataset", "dev", "--data-dir", str(REPO_ROOT / "data/dev"),
               "--mode", args.mode, "--run-version", args.run_version,
               "--timeout", str(args.timeout), "--sleep", str(args.sleep)]
    for case in suite["cases"]:
        command.extend(["--case-id", case["case_id"]])
    if args.predictions:
        command.extend(["--predictions", str(args.predictions.resolve())])
    if args.base_url is not None:
        url = urlsplit(args.base_url)
        if (url.scheme not in ("https", "http") or not url.hostname or url.username or url.password
                or url.path not in ("", "/") or url.query or url.fragment
                or (url.scheme == "http" and url.hostname not in ("localhost", "127.0.0.1"))):
            raise ValueError("AI URL must be HTTPS; HTTP only for localhost")
        command.extend(["--base-url", args.base_url, "--stop-on-error"])
    if args.rule_results:
        command.extend(["--rule-results", str(args.rule_results.resolve())])
    options = evaluation_parser().parse_args(command)
    options.policies = ["present", "present_boundary"]
    # Validate all inputs before subprocesses or paid requests.
    dataset, cases, _ = prepare_dataset(options)
    rules = json.loads(args.rule_results.read_text()) if args.rule_results else {}
    if not isinstance(rules, dict) or (args.mode == "llm" and args.rule_results):
        raise ValueError("Invalid Rule input")
    for case in cases:
        build_payload(case, args.mode, rules.get(case["case_id"]))
    if args.predictions:
        records = read_predictions(args.predictions)
        if set(records) - {case["case_id"] for case in dataset.cases}:
            raise ValueError("Predictions must use development IDs")
    return options


def counts(value):
    if not isinstance(value, dict):
        value = {}
    return {key: value[key] if type(value.get(key)) is int and value[key] >= 0 else 0 for key in OUTCOMES}


def run_offline(directory):
    destination = directory / "offline_aggregate.json"
    env = dict(os.environ)
    for key in ("PYTEST_ADDOPTS", "PYTEST_PLUGINS", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
                "OPENAI_API_KEY", "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "GOOGLE_APPLICATION_CREDENTIALS",
                "TEACHERHUB_EMAIL", "TEACHERHUB_PASSWORD"):
        env.pop(key, None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env["PY_COLORS"] = "0"
    try:
        result = subprocess.run([sys.executable, "-m", "pytest", *OFFLINE_TESTS,
                                 "-o", "addopts=--tb=no --show-capture=no", "-q",
                                 "--aggregate-report", str(destination)],
                                cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120)
        aggregate = json.loads(destination.read_text()) if destination.exists() else {}
        groups = aggregate.get("groups", {})
        core = counts(aggregate.get("core20"))
        guards = counts(groups.get("guardrails"))
        logs = counts(groups.get("operational_logs"))
        status = (result.returncode == 0 and core["passed"] == 20
                  and guards["passed"] > 0 and logs["passed"] > 0
                  and not any(counts(aggregate.get("tests"))[key] for key in ("failed", "xpassed")))
        failed = set()
        for line in result.stdout.splitlines():
            if re.fullmatch(r"CORE20_FAILED:(?: DEV[0-9]{3})+", line):
                failed.update(line.split()[1:])
        return {"status": "passed" if status else "failed", "pytest_exit_code": result.returncode,
                "core20": core, "guardrails": guards, "operational_logs": logs,
                "failed_case_ids": sorted(failed), "raw_pytest_output_retained": False}
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return {"status": "failed", "error_code": "offline_runner_failed", "core20": counts({}),
                "guardrails": counts({}), "operational_logs": counts({}), "failed_case_ids": []}


def main(argv=None):
    args = build_parser().parse_args(argv)
    directory = None
    try:
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", args.run_version)
                or not math.isfinite(args.timeout) or args.timeout <= 0
                or not math.isfinite(args.sleep) or args.sleep < 0):
            raise ValueError("Invalid run settings")
        if args.base_url is not None and (not args.base_url.strip() or args.base_url != args.base_url.strip()):
            raise ValueError("An explicit live origin must not be empty")
        wants_inference = args.predictions is not None or args.base_url is not None
        if not wants_inference and (args.rule_results or args.mode != "llm"):
            raise ValueError("Rule mode requires inference input")
        suite_bytes = SUITE.read_bytes()
        suite, dataset = load_core_suite(SUITE, REPO_ROOT / "data/dev")
        if json.loads(suite_bytes) != suite:
            raise ValueError("Core suite changed while loading")
        options = evaluation_options(args, suite) if wants_inference else None
        snapshots = {name: path.read_bytes() for name, path in
                     (("predictions", args.predictions), ("rules", args.rule_results)) if path is not None}
        log_result = check_logs(args.log_file) if args.log_file else {"status": "not_run"}
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + args.run_version + "_" + uuid4().hex[:8]
        directory = args.report_dir.resolve() / run_id
        directory.mkdir(parents=True, exist_ok=False)
        snapshot_paths = {}
        for name, content in snapshots.items():
            suffix = ".jsonl" if name == "predictions" and args.predictions.suffix == ".jsonl" else ".json"
            path = directory / (name + "_input" + suffix)
            with path.open("xb") as stream:
                os.chmod(path, 0o600)
                stream.write(content)
            snapshot_paths[name] = path.name
            setattr(options, "predictions" if name == "predictions" else "rule_results", str(path))
        offline = run_offline(directory)
        pending = sum(offline["guardrails"][key] for key in ("skipped", "xfailed", "xpassed"))
        quality = {"status": "not_run", "reason": "no_inference_input"}
        if options and (offline["status"] != "passed" or log_result["status"] == "failed"
                        or (args.require_complete_guardrails and pending)):
            quality = {"status": "not_run", "reason": "offline_log_or_guardrail_gate_failed"}
        elif options:
            options.report_dir = str(directory / "tagging")
            # The evaluator saves each completed HTTP response before starting the next case.
            if args.base_url is not None:
                options.checkpoint_file = str(directory / "inference_checkpoint.jsonl")
            _, report, evaluation_status = evaluate(options)
            quality = assess_records(suite, read_predictions(report / "predictions.jsonl"))
            quality.update(execution="http" if args.base_url is not None else "saved_predictions",
                           tagging_report=str(report.relative_to(directory)), evaluator_exit_code=evaluation_status)
            if evaluation_status:
                quality["status"] = "failed"
        success = (offline["status"] == "passed" and log_result["status"] != "failed"
                   and quality["status"] in ("passed", "not_run")
                   and (not options or quality["status"] == "passed")
                   and not (args.require_complete_guardrails and pending))
        summary = {"schema_version": 1, "kind": "core20_contracts_and_optional_inference_regression",
                   "exit_code": int(not success), "offline": offline, "model_regression": quality,
                   "log_validation": log_result, "guardrails_complete": pending == 0 and offline["status"] == "passed",
                   "pending_guardrails": pending, "human_expectation_review_complete": False,
                   "deployment_readiness_claimed": False}
        write_json(directory / "summary.json", summary)
        write_csv(directory / "failures.csv", quality.get("failures", []),
                  ["case_id", "code", "expected", "actual", "error_code"])
        manifest = {"run_id": run_id, "git": git_info(), "suite_sha256": hashlib.sha256(suite_bytes).hexdigest(),
                    "development_dataset_sha256": dataset.digest,
                    "predictions_sha256": hashlib.sha256(snapshots["predictions"]).hexdigest() if "predictions" in snapshots else None,
                    "rules_sha256": hashlib.sha256(snapshots["rules"]).hexdigest() if "rules" in snapshots else None,
                    "input_snapshots": snapshot_paths,
                    "log_file_sha256": log_result.get("checked_sha256"),
                    "log_hash_scope": "checked bytes only; subsequent appends are not covered",
                    "expectations": "AI_PROPOSED_partial_conditions_pending_human_review",
                    "raw_inputs_in_summary": False}
        write_json(directory / "manifest.json", manifest)
        print(f"Offline: {offline['status']} | core20={offline['core20']['passed']}/20 | pending guardrails={pending}")
        print(f"Inference regression: {quality['status']} | log validation: {log_result['status']}")
        for case_id in offline["failed_case_ids"]:
            print(f"{case_id}: offline_contract_failed")
        for row in quality.get("failures", []):
            detail = f"{row['code']} expected={row['expected']} actual={row['actual']}" if row["code"] else row["error_code"]
            print(f"{row['case_id']}: {detail}")
        print(f"Reports: {directory}")
        return summary["exit_code"]
    except (ValueError, OSError, KeyError, TypeError):
        # Paths, parser errors and exception strings can contain source data or secrets.
        if directory:
            try:
                write_json(directory / "runner_error.json", {"error_code": "REGRESSION_RUNNER_ERROR", "exit_code": 2})
            except OSError:
                pass
        print("REGRESSION_RUNNER_ERROR: check settings and saved reports; no exception text retained", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
