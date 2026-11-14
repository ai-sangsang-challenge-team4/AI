from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints.ai import get_ai_service
from app.core.errors import AiFailure, ErrorCode
from app.main import create_app
from tests.offline_support import FakeLlm, make_service, risk_output


def call_analyze(client, complaint="입력 원문", **kwargs):
    app = create_app()
    app.dependency_overrides[get_ai_service] = lambda: make_service(client)
    with TestClient(app) as http:
        return http.post("/api/v1/ai/analyze", json={"complaint": complaint, "ruleResults": []}, **kwargs)


@pytest.mark.parametrize("kind,expected", [
    ("fake_tag", "LLM_INVALID_SCHEMA"), ("duplicate_tag", "LLM_INVALID_SCHEMA"),
    ("missing_tag", "LLM_INVALID_SCHEMA"), ("invalid_state", "LLM_INVALID_SCHEMA"),
    ("missing_severity", "LLM_INVALID_SCHEMA"), ("bad_flags", "LLM_INVALID_SCHEMA"),
    ("outside_evidence", "LLM_INVALID_EVIDENCE"), ("broken_json", "LLM_INVALID_JSON"),
    ("non_object", "LLM_INVALID_SCHEMA"),
])
def test_bad_output_is_retried_once_then_fails_closed(kind, expected):
    value = risk_output()
    if kind == "fake_tag":
        value["tags"][0]["code"] = "FAKE_TAG_CANARY"
    elif kind == "duplicate_tag":
        value["tags"].append(dict(value["tags"][0]))
    elif kind == "missing_tag":
        value["tags"].pop()
    elif kind == "invalid_state":
        value["tags"][0]["state"] = "INVALID_CANARY"
    elif kind == "missing_severity":
        del value["tags"][0]["severity"]
    elif kind == "bad_flags":
        value["safetyFlags"]["credibleThreat"] = "UNTRUSTED_CANARY"
    elif kind == "outside_evidence":
        value = risk_output({"THREAT": "PRESENT"}, {"THREAT": ["원문에 없는 근거_CANARY"]})
    raw = "{BROKEN_CANARY" if kind == "broken_json" else "[]" if kind == "non_object" else json.dumps(value)
    client = FakeLlm(raw)
    result = call_analyze(client)
    assert result.status_code == 502
    assert result.json()["error"]["code"] == expected
    assert "tags" not in result.json()
    assert len(client.prompts) == 2


@pytest.mark.parametrize("first", ["{broken", json.dumps({"tags": []})])
def test_one_output_retry_can_recover(first):
    client = FakeLlm(first, json.dumps(risk_output()))
    assert call_analyze(client).status_code == 200
    assert len(client.prompts) == 2


def test_timeout_is_not_retried_or_fabricated_as_normal():
    client = FakeLlm(TimeoutError("SECRET_TIMEOUT_CANARY"))
    result = call_analyze(client)
    assert result.status_code == 504
    assert result.json()["error"]["code"] == "LLM_TIMEOUT"
    assert len(client.prompts) == 1


def test_provider_error_after_invalid_output_stops_at_budget():
    client = FakeLlm("{broken", RuntimeError("SECRET_PROVIDER_CANARY"))
    result = call_analyze(client)
    assert result.status_code == 502
    assert result.json()["error"]["code"] == "LLM_UNAVAILABLE"
    assert len(client.prompts) == 2


@pytest.mark.parametrize("malformed", [123, None, [123], [{}], [{"text": None}], [""], " "])
def test_malformed_evidence_is_not_silently_erased(malformed):
    value = risk_output({"THREAT": "PRESENT"})
    next(tag for tag in value["tags"] if tag["code"] == "THREAT")["evidenceSpans"] = malformed
    client = FakeLlm(json.dumps(value))
    result = call_analyze(client)
    assert result.status_code == 502
    assert result.json()["error"]["code"] == "LLM_INVALID_SCHEMA"
    assert len(client.prompts) == 2


@pytest.mark.parametrize("spans", [[], "입력 원문", ["입력 원문"], [{"text": "입력 원문"}]])
def test_supported_evidence_formats_keep_compatibility(spans):
    value = risk_output({"THREAT": "PRESENT"})
    next(tag for tag in value["tags"] if tag["code"] == "THREAT")["evidenceSpans"] = spans
    client = FakeLlm(json.dumps(value))
    result = call_analyze(client)
    assert result.status_code == 200
    assert len(client.prompts) == 1
    actual = next(tag for tag in result.json()["tags"] if tag["code"] == "THREAT")["evidenceSpans"]
    assert actual == [] if spans == [] else actual[0]["text"] == "입력 원문"


def test_safe_exception_has_no_free_text_details():
    exc = AiFailure(ErrorCode.LLM_INVALID_JSON)
    assert str(exc) == "LLM_INVALID_JSON"


def test_provider_timeout_type_uses_timeout_response():
    APITimeoutError = type("APITimeoutError", (Exception,), {})
    client = FakeLlm(APITimeoutError("SECRET_PROVIDER_TIMEOUT_CANARY"))
    result = call_analyze(client)
    assert result.status_code == 504
    assert result.json()["error"]["code"] == "LLM_TIMEOUT"
    assert len(client.prompts) == 1


def test_claude_sdk_timeout_and_nested_retry_budget(monkeypatch):
    import importlib.util
    import sys
    import types
    from pathlib import Path
    from unittest.mock import Mock
    sdk = types.ModuleType("anthropic")
    sdk.Anthropic = Mock()
    monkeypatch.setitem(sys.modules, "anthropic", sdk)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "offline-placeholder")
    spec = importlib.util.spec_from_file_location("offline_sdk_budget", Path(__file__).parents[1] / "app/llm/claude_client.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ClaudeLlmClient(temperature=0.0)
    sdk.Anthropic.assert_called_once_with(api_key="offline-placeholder", timeout=30.0, max_retries=0)


@pytest.mark.pending_guardrail
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="#28 owner: evidence repair PRESENT -> BOUNDARY is not implemented; current behavior is fail-closed")
def test_pending_evidence_downgrade_contract():
    value = risk_output({"THREAT": "PRESENT"}, {"THREAT": ["원문에 없는 표현"]})
    result = call_analyze(FakeLlm(json.dumps(value)))
    assert result.status_code == 200
    assert next(tag for tag in result.json()["tags"] if tag["code"] == "THREAT")["state"] == "BOUNDARY"


@pytest.mark.pending_guardrail
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="#28 owner: REPEAT without structured history must not remain PRESENT; enforcement is pending")
def test_pending_repeat_without_history_contract():
    value = risk_output({"REPEAT": "PRESENT"}, {"REPEAT": ["다시 문의"]})
    result = call_analyze(FakeLlm(json.dumps(value)), complaint="다시 문의 드립니다")
    assert result.status_code == 200
    assert next(tag for tag in result.json()["tags"] if tag["code"] == "REPEAT")["state"] != "PRESENT"


@pytest.mark.pending_guardrail
@pytest.mark.xfail(strict=True, raises=AssertionError, reason="#28 owner: summary invented number/date/name guard is not implemented")
def test_pending_summary_invented_date_contract():
    app = create_app()
    app.dependency_overrides[get_ai_service] = lambda: make_service(FakeLlm("2099년 12월 31일 확정"))
    with TestClient(app) as http:
        result = http.post("/api/v1/ai/summary", json={"content": "일정을 확인해 주세요"})
    assert result.status_code == 502
