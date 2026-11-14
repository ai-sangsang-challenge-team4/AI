"""Network/key isolation and aggregate-only CI reporting."""
from __future__ import annotations

import json
import socket
from collections import Counter
from pathlib import Path
from time import perf_counter

import pytest


def pytest_addoption(parser):
    parser.addoption("--aggregate-report", default="reports/ci/aggregate.json", help="Counts only; no inputs/outputs or failure tracebacks")


def pytest_configure(config):
    config._safe_results = {}
    config._safe_started = perf_counter()


@pytest.fixture(autouse=True)
def no_network_or_keys(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("network_forbidden_in_offline_tests")
    for method in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, method, forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    for name in ("ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY",
                 "CLOUDFLARE_API_TOKEN", "CLOUDFLARE_ACCOUNT_ID", "GOOGLE_APPLICATION_CREDENTIALS"):
        monkeypatch.delenv(name, raising=False)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call" or report.failed or (report.when == "setup" and report.skipped):
        result = ("xfailed" if report.skipped else "xpassed") if hasattr(report, "wasxfail") else report.outcome
        prior = item.config._safe_results.get(item.nodeid)
        rank = {"passed": 0, "skipped": 1, "xfailed": 2, "xpassed": 3, "failed": 4}
        if prior is None or rank[result] >= rank[prior]:
            item.config._safe_results[item.nodeid] = result


def pytest_sessionfinish(session, exitstatus):
    config = session.config
    if config.option.collectonly:
        return
    outcomes = Counter(config._safe_results.values())
    core = Counter(result for node, result in config._safe_results.items()
                   if "test_regression_core20.py::test_core_case[" in node)
    value = {"schema_version": 1, "kind": "offline_contract_validation_not_model_quality",
             "exit_code": int(exitstatus), "duration_seconds": round(perf_counter() - config._safe_started, 3),
             "tests": {key: outcomes[key] for key in ("passed", "failed", "skipped", "xfailed", "xpassed")},
             "core20": dict(core), "contains_raw_cases_or_responses": False}
    destination = Path(config.getoption("--aggregate-report"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
