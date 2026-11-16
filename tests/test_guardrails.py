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


def test_application_loads_dotenv_before_lazy_service_creation(monkeypatch, tmp_path):
    import os
    import app.main as main_module
    from dotenv import load_dotenv
    path = tmp_path / ".env"
    path.write_text("TEST_CONFIG_SENTINEL=loaded\n")
    monkeypatch.delenv("TEST_CONFIG_SENTINEL", raising=False)
    monkeypatch.setattr(main_module, "load_dotenv", lambda: load_dotenv(path))
    app = main_module.create_app()
    def service():
        assert os.environ["TEST_CONFIG_SENTINEL"] == "loaded"
        return make_service()
    app.dependency_overrides[get_ai_service] = service
    with TestClient(app) as http:
        result = http.post("/api/v1/ai/analyze", json={"complaint": "테스트", "ruleResults": []})
    assert result.status_code == 200


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


@pytest.mark.parametrize("first", [None, 123, "{broken", json.dumps({"tags": []})])
def test_one_output_retry_can_recover(first):
    client = FakeLlm(first, json.dumps(risk_output()))
    assert call_analyze(client).status_code == 200
    assert len(client.prompts) == 2


@pytest.mark.parametrize("temperature", [0.7, None])
def test_metadata_records_effective_generation_temperature(temperature):
    client = FakeLlm()
    client.generation_settings = {"max_tokens": 4096}
    if temperature is not None:
        client.generation_settings["temperature"] = temperature
    result = call_analyze(client)
    assert result.status_code == 200
    assert result.json()["metadata"]["temperature"] == temperature
    assert result.json()["metadata"]["generationSettings"] == client.generation_settings


@pytest.mark.parametrize("offsets", [(0, 5), (1, 4)])
def test_evidence_text_and_offsets_remain_consistent(offsets):
    text = " abc " if offsets == (0, 5) else "abc"
    value = risk_output({"THREAT": "PRESENT"})
    tag = next(tag for tag in value["tags"] if tag["code"] == "THREAT")
    tag["evidenceSpans"] = [{"text": text, "start": offsets[0], "end": offsets[1]}]
    result = call_analyze(FakeLlm(json.dumps(value)), complaint=" abc ")
    assert result.status_code == 200
    actual = next(tag for tag in result.json()["tags"] if tag["code"] == "THREAT")["evidenceSpans"][0]
    assert " abc "[actual["start"]:actual["end"]] == actual["text"]


@pytest.mark.parametrize("start,end", [(0, 3), (-1, 4), (1, 99), (1, None), (None, 4), (True, 4), ("1", 4)])
def test_invalid_evidence_offsets_use_output_retry(start, end):
    value = risk_output({"THREAT": "PRESENT"})
    next(tag for tag in value["tags"] if tag["code"] == "THREAT")["evidenceSpans"] = [
        {"text": "abc", "start": start, "end": end}]
    client = FakeLlm(json.dumps(value), json.dumps(risk_output()))
    result = call_analyze(client, complaint=" abc ")
    assert result.status_code == 200
    assert len(client.prompts) == 2


def test_overflowing_json_number_is_retried_before_response_rendering():
    value = risk_output()
    value["tags"][0]["confidence"] = "OVERFLOW_TOKEN"
    raw = json.dumps(value).replace('"OVERFLOW_TOKEN"', '1e400')
    client = FakeLlm(raw, json.dumps(risk_output()))
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
