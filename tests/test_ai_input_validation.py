"""Input-boundary regression tests. No network, provider keys or complaint leaks."""
from __future__ import annotations

import sys
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints.ai import get_ai_service
from app.main import create_app
from app.schemas.input_limits import MAX_COMPLAINT_CHARS, MAX_SEARCH_QUERY_CHARS
from tests.offline_support import FakeLlm, FakeRetriever, make_service


AI_CASES = [
    ("/api/v1/ai/analyze", "complaint", {"ruleResults": []}),
    ("/api/v1/ai/context", "content", {}),
    ("/api/v1/ai/summary", "content", {}),
    ("/api/v1/ai/revision", "complaint", {"tags": [], "riskScore": 0, "riskLevel": "Low"}),
    ("/api/v1/ai/response-draft", "content", {}),
]


@pytest.mark.parametrize("endpoint,field,extra", AI_CASES)
@pytest.mark.parametrize("text", ["", "   \n\t  ", "가" * (MAX_COMPLAINT_CHARS + 1)])
def test_invalid_ai_text_rejected_before_llm(endpoint, field, extra, text):
    fake = FakeLlm()
    retriever = FakeRetriever()
    app = create_app()
    app.dependency_overrides[get_ai_service] = lambda: make_service(fake, retriever)
    with TestClient(app) as http:
        response = http.post(endpoint, json={field: text, **extra})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert set(response.json()) == {"error", "requestId"}
    assert not fake.prompts
    assert not retriever.calls
    assert text[:30] not in response.text if text else True


@pytest.mark.parametrize("endpoint,field,extra", AI_CASES)
def test_at_max_length_schema_accepts_request(endpoint, field, extra):
    """Use request schema to prove boundary without expensive LLM generation."""
    from app.schemas.ai import AiAnalyzeRequest, ContextAnalysisRequest
    from app.schemas.revision import RevisionRequest
    from app.schemas.support import SummaryRequest, ResponseDraftRequest
    models = {
        "/api/v1/ai/analyze": AiAnalyzeRequest,
        "/api/v1/ai/context": ContextAnalysisRequest,
        "/api/v1/ai/summary": SummaryRequest,
        "/api/v1/ai/revision": RevisionRequest,
        "/api/v1/ai/response-draft": ResponseDraftRequest,
    }
    text = "  " + "가" * (MAX_COMPLAINT_CHARS - 2)
    parsed = models[endpoint].model_validate({field: text, **extra})
    assert getattr(parsed, field) == text  # no trimming: evidence offsets are preserved


@pytest.mark.parametrize("query", ["", "  \t\n ", "질" * (MAX_SEARCH_QUERY_CHARS + 1)])
def test_invalid_rag_search_does_not_construct_retriever(monkeypatch, query):
    sdk = ModuleType("app.rag.retriever")
    class MustNotRun:
        def __init__(self):
            raise AssertionError("invalid search must not construct retriever")
    sdk.RagRetriever = MustNotRun
    monkeypatch.setitem(sys.modules, "app.rag.retriever", sdk)
    with TestClient(create_app()) as http:
        response = http.post("/api/v1/rag/search", json={"query": query})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert set(response.json()) == {"error", "requestId"}


def test_rag_search_accepts_upper_bound_and_keeps_text(monkeypatch):
    seen = []
    sdk = ModuleType("app.rag.retriever")
    class Retriever:
        def search(self, query):
            seen.append(query)
            return []
    sdk.RagRetriever = Retriever
    monkeypatch.setitem(sys.modules, "app.rag.retriever", sdk)
    query = " " + "가" * (MAX_SEARCH_QUERY_CHARS - 1)
    with TestClient(create_app()) as http:
        response = http.post("/api/v1/rag/search", json={"query": query})
    assert response.status_code == 200
    assert response.json() == {"documents": []}
    assert seen == [query]


def test_ai_response_schemas_not_constrained_by_request_limits():
    from app.schemas.support import RagReference, ResponseDraftResult
    text = "가" * (MAX_COMPLAINT_CHARS + 1)
    output = ResponseDraftResult(content=text, modelName="fake",
                                 references=[RagReference(source="fixture", content=text)])
    assert output.content == text
    assert output.references[0].content == text
