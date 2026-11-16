from __future__ import annotations

import io
import json
import logging
import re

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints.ai import get_ai_service
from app.core.operational_logging import FIELDS, LOGGER, SafeJsonFormatter
from app.main import create_app
from tests.offline_support import FakeLlm, FakeRetriever, make_service, risk_output

CANARIES = ("RAW_COMPLAINT_CANARY", "PROMPT_CANARY", "EVIDENCE_CANARY", "HISTORY_CANARY",
            "MODEL_RESPONSE_CANARY", "sk-API_KEY_CANARY", "EXCEPTION_CANARY", "HEADER_CANARY")


@pytest.fixture
def operation_logs(monkeypatch):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(SafeJsonFormatter())
    monkeypatch.setattr(LOGGER, "handlers", [handler])
    return stream


def assert_no_sensitive_data(text):
    if any(canary in text for canary in CANARIES):
        pytest.fail("sensitive_data_exposure_detected", pytrace=False)


def read_events(stream):
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    for event in events:
        assert set(event) == set(FIELDS)
        assert re.fullmatch(r"[0-9a-f]{32}", event["request_id"])
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", event["prompt_version"])
        assert event["latency_ms"] >= 0
    return events


@pytest.mark.parametrize("mode,code,status", [
    ("success", "OK", 200), ("timeout", "LLM_TIMEOUT", 504),
    ("json", "LLM_INVALID_JSON", 502), ("schema", "LLM_INVALID_SCHEMA", 502),
    ("evidence", "LLM_INVALID_EVIDENCE", 502), ("provider", "LLM_UNAVAILABLE", 502),
])
def test_success_and_failure_log_allowlist(mode, code, status, operation_logs, capsys, caplog):
    secret = " ".join(CANARIES)
    value = risk_output({"THREAT": "PRESENT"}, {"THREAT": ["EVIDENCE_CANARY"]})
    value["tags"][0]["reason"] = "MODEL_RESPONSE_CANARY"
    if mode == "timeout":
        raw = TimeoutError(secret)
    elif mode == "provider":
        raw = RuntimeError(secret)
    elif mode == "json":
        raw = "{" + secret
    else:
        if mode == "schema":
            value["tags"][0]["code"] = secret
        if mode == "evidence":
            value["tags"][2]["evidenceSpans"] = [{"text": "원문 바깥 MODEL_RESPONSE_CANARY"}]
        raw = json.dumps(value)
    client = FakeLlm(raw, sdk_log=secret)
    service = make_service(client, FakeRetriever([{"content": "PROMPT_CANARY", "source": "offline"}]))
    app = create_app()
    app.dependency_overrides[get_ai_service] = lambda: service
    with TestClient(app) as http:
        result = http.post("/api/v1/ai/analyze?token=sk-API_KEY_CANARY", headers={"X-Request-ID": "HEADER_CANARY"},
                           json={"complaint": secret, "ruleResults": [{"code": "LEGAL", "state": "UNKNOWN", "reason": "HISTORY_CANARY"}]})
    assert result.status_code == status
    events = read_events(operation_logs)
    assert len(events) == 1
    event = events[0]
    assert event["endpoint"] == "/api/v1/ai/analyze"
    assert event["model_name"] == "claude-sonnet-4-6"
    assert event["error_code"] == code
    assert event["success"] is (mode == "success")
    assert event["request_id"] == result.headers["X-Request-ID"]
    captured = capsys.readouterr()
    output = operation_logs.getvalue() + captured.out + captured.err + caplog.text
    if status >= 400:
        output += result.text
        assert set(result.json()) == {"error", "requestId"}
        assert result.json()["requestId"] == event["request_id"]
    assert_no_sensitive_data(output)


@pytest.mark.parametrize("endpoint,payload", [
    ("/api/v1/ai/analyze", {"complaint": "RAW_COMPLAINT_CANARY", "ruleResults": [{"code": "MODEL_RESPONSE_CANARY", "state": "BAD"}]}),
    ("/api/v1/ai/summary", {"content": {"RAW_COMPLAINT_CANARY": "sk-API_KEY_CANARY"}}),
    ("/api/v1/ai/context", {"content": []}),
])
def test_request_validation_never_echoes_pydantic_input(endpoint, payload, operation_logs, capsys):
    client = FakeLlm()
    app = create_app(); app.dependency_overrides[get_ai_service] = lambda: make_service(client)
    with TestClient(app) as http:
        result = http.post(endpoint, json=payload)
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "INVALID_REQUEST"
    assert not client.prompts
    assert read_events(operation_logs)[0]["success"] is False
    captured = capsys.readouterr()
    assert_no_sensitive_data(result.text + operation_logs.getvalue() + captured.out + captured.err)


def test_unhandled_dependency_failure_and_unknown_path_are_sanitized(operation_logs, capsys):
    app = create_app()
    def unavailable():
        raise RuntimeError(" ".join(CANARIES))
    app.dependency_overrides[get_ai_service] = unavailable
    with TestClient(app) as http:
        result = http.post("/api/v1/ai/summary", json={"content": "RAW_COMPLAINT_CANARY"})
        missing = http.get("/unknown/RAW_COMPLAINT_CANARY?api_key=sk-API_KEY_CANARY")
    assert result.status_code == 500
    assert result.json()["error"]["code"] == "INTERNAL_ERROR"
    assert missing.status_code == 404
    assert read_events(operation_logs)[1]["endpoint"] == "unmatched"
    captured = capsys.readouterr()
    assert_no_sensitive_data(result.text + missing.text + operation_logs.getvalue() + captured.out + captured.err)


def test_response_validation_and_rag_failure_are_sanitized(operation_logs, monkeypatch, capsys):
    service = make_service()
    monkeypatch.setattr(service, "generate_summary", lambda content: {"summary": {"MODEL_RESPONSE_CANARY": "sk-API_KEY_CANARY"}})
    app = create_app(); app.dependency_overrides[get_ai_service] = lambda: service
    with TestClient(app) as http:
        result = http.post("/api/v1/ai/summary", json={"content": "RAW_COMPLAINT_CANARY"})
    assert result.status_code == 502
    assert result.json()["error"]["code"] == "LLM_INVALID_SCHEMA"
    def broken(*args, **kwargs):
        raise RuntimeError(" ".join(CANARIES))
    monkeypatch.setattr(service.retriever, "search", broken)
    with TestClient(app) as http:
        result = http.post("/api/v1/ai/analyze", json={"complaint": "RAW_COMPLAINT_CANARY"})
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "RAG_UNAVAILABLE"
    captured = capsys.readouterr()
    assert_no_sensitive_data(result.text + operation_logs.getvalue() + captured.out + captured.err)


def test_rag_output_validation_uses_search_failure_boundary(operation_logs, monkeypatch, capsys):
    import sys
    import types
    module = types.ModuleType("app.rag.retriever")

    class BadRetriever:
        def search(self, query):
            return [{"content": {"MODEL_RESPONSE_CANARY": "sk-API_KEY_CANARY"}}]

    module.RagRetriever = BadRetriever
    monkeypatch.setitem(sys.modules, "app.rag.retriever", module)
    with TestClient(create_app()) as http:
        result = http.post("/api/v1/rag/search", json={"query": "RAW_COMPLAINT_CANARY"})
    assert result.status_code == 503
    assert result.json()["error"]["code"] == "RAG_UNAVAILABLE"
    assert read_events(operation_logs)[0]["error_code"] == "RAG_UNAVAILABLE"
    captured = capsys.readouterr()
    assert_no_sensitive_data(result.text + operation_logs.getvalue() + captured.out + captured.err)


@pytest.mark.parametrize("endpoint,payload,raw", [
    ("/api/v1/ai/context", {"content": "RAW_COMPLAINT_CANARY"}, "{MODEL_RESPONSE_CANARY"),
    ("/api/v1/ai/revision", {"complaint": "RAW_COMPLAINT_CANARY", "tags": [], "riskScore": 0, "riskLevel": "Low"}, "{MODEL_RESPONSE_CANARY"),
    ("/api/v1/ai/summary", {"content": "RAW_COMPLAINT_CANARY"}, TimeoutError("sk-API_KEY_CANARY")),
])
def test_other_ai_endpoints_share_safe_error_boundary(endpoint, payload, raw, operation_logs, capsys):
    app = create_app(); app.dependency_overrides[get_ai_service] = lambda: make_service(FakeLlm(raw))
    with TestClient(app) as http:
        result = http.post(endpoint, json=payload)
    assert result.status_code in (502, 504)
    captured = capsys.readouterr()
    assert_no_sensitive_data(result.text + operation_logs.getvalue() + captured.out + captured.err)


def test_parallel_requests_keep_separate_request_ids(operation_logs):
    from concurrent.futures import ThreadPoolExecutor
    app = create_app(); app.dependency_overrides[get_ai_service] = lambda: make_service()
    def request_one(index):
        with TestClient(app) as http:
            return http.post("/api/v1/ai/analyze", json={"complaint": f"요청 {index}"}).headers["X-Request-ID"]
    with ThreadPoolExecutor(max_workers=4) as executor:
        ids = list(executor.map(request_one, range(8)))
    assert len(set(ids)) == 8
    assert {event["request_id"] for event in read_events(operation_logs)} == set(ids)


def test_formatter_ignores_messages_tracebacks_and_untrusted_extra_fields():
    record = logging.LogRecord("teachercare.operations", logging.ERROR, __file__, 1,
                               " ".join(CANARIES), ("sk-API_KEY_CANARY",), None)
    record.exc_text = "EXCEPTION_CANARY"
    record.safe_event = {"request_id": ["RAW_COMPLAINT_CANARY"], "endpoint": {"secret": "PROMPT_CANARY"},
                         "model_name": ["sk-API_KEY_CANARY"], "prompt_version": "PROMPT_CANARY",
                         "error_code": {"detail": "EXCEPTION_CANARY"}, "latency_ms": float("nan"),
                         "success": "MODEL_RESPONSE_CANARY", "history": "HISTORY_CANARY"}
    text = SafeJsonFormatter().format(record)
    assert set(json.loads(text)) == set(FIELDS)
    assert_no_sensitive_data(text)


@pytest.mark.parametrize("kind", ["summary", "context", "revision", "response-draft"])
def test_generation_endpoints_still_work_with_offline_dependencies(kind, operation_logs):
    context = {"communicationIntent": "INFORMATION_INQUIRY", "primaryTopic": "SCHOOL_POLICY_PROCEDURE",
               "secondaryTopics": [], "confidence": 0.9, "evidenceSpans": [], "reason": "fixture"}
    if kind == "context":
        client = FakeLlm(json.dumps(context)); payload = {"content": "절차 안내 요청"}
    elif kind == "revision":
        client = FakeLlm(json.dumps({"finalRevision": {"reason": "fixture", "content": "절차 안내를 부탁드립니다"}, "tagSuggestions": []}))
        payload = {"complaint": "절차 안내 요청", "tags": [], "riskScore": 0, "riskLevel": "Low"}
    elif kind == "response-draft":
        client = FakeLlm(json.dumps(context), "절차를 확인하여 안내드리겠습니다")
        payload = {"content": "절차 안내 요청"}
    else:
        client = FakeLlm("절차 안내를 요청합니다"); payload = {"content": "절차 안내 요청"}
    app = create_app(); app.dependency_overrides[get_ai_service] = lambda: make_service(client)
    with TestClient(app) as http:
        result = http.post("/api/v1/ai/" + kind, json=payload)
    assert result.status_code == 200
    assert read_events(operation_logs)[0]["success"] is True
