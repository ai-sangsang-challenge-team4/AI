"""Offline resilience tests: no provider calls, API keys, or exception data in responses."""
from types import ModuleType, SimpleNamespace
import importlib.util
from pathlib import Path
import sys

import pytest

from app.core.errors import AiFailure, ErrorCode
from app.services.ai_service import AiService


class StubLlm:
    model = "gemini-3.5-flash-lite"

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = 0

    def generate(self, prompt):
        self.calls += 1
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


@pytest.mark.parametrize("error", [
    TimeoutError("secret prompt token"),
    type("APITimeoutError", (Exception,), {})("secret key"),
    type("ReadTimeout", (Exception,), {})("secret request"),
    type("ConnectTimeout", (Exception,), {})("secret url"),
    type("PoolTimeout", (Exception,), {})("secret path"),
    type("WriteTimeout", (Exception,), {})("secret user input"),
])
def test_timeout_exceptions_are_safe(error):
    client = StubLlm(error)
    with pytest.raises(AiFailure) as caught:
        AiService._generate(client, "a private complaint")
    assert caught.value.code == ErrorCode.LLM_TIMEOUT
    assert caught.value.status == 504
    assert str(caught.value) == "LLM_TIMEOUT"
    assert client.calls == 1
    assert caught.value.__cause__ is None


def test_other_sdk_failure_returns_safe_unavailable_code():
    client = StubLlm(RuntimeError("private provider message and api key"))
    with pytest.raises(AiFailure) as caught:
        AiService._generate(client, "private complaint")
    assert caught.value.code == ErrorCode.LLM_UNAVAILABLE
    assert caught.value.status == 502
    assert str(caught.value) == "LLM_UNAVAILABLE"
    assert client.calls == 1


@pytest.mark.parametrize("value", [None, "", "   ", 42])
def test_invalid_llm_response_is_not_reported_as_success(value):
    with pytest.raises(AiFailure) as caught:
        AiService._generate(StubLlm(value), "prompt")
    assert caught.value.code == ErrorCode.LLM_INVALID_SCHEMA


def test_success_preserves_model_output():
    assert AiService._generate(StubLlm("정상 답변"), "prompt") == "정상 답변"


def test_gemini_timeout_and_retry_are_explicit(monkeypatch):
    """Inspect config with a fake SDK; CI intentionally omits google-genai."""
    created = []

    class HttpOptions:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class HttpRetryOptions:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    def fake_client(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(models=SimpleNamespace(
            generate_content=lambda **_: SimpleNamespace(text="정상 답변")
        ))

    fake_google = ModuleType("google")
    fake_genai = ModuleType("google.genai")
    fake_types = ModuleType("google.genai.types")
    fake_genai.Client = fake_client
    fake_types.HttpOptions = HttpOptions
    fake_types.HttpRetryOptions = HttpRetryOptions
    fake_genai.types = fake_types
    fake_google.genai = fake_genai
    monkeypatch.setitem(sys.modules, "google", fake_google)
    monkeypatch.setitem(sys.modules, "google.genai", fake_genai)
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)

    # Load under an isolated test name so the fake SDK is not cached in the
    # regular app.llm.gemini_client module across other tests.
    module_path = Path(__file__).resolve().parents[1] / "app/llm/gemini_client.py"
    spec = importlib.util.spec_from_file_location("_offline_gemini_client", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    monkeypatch.setenv("GEMINI_API_KEY", "test-only-placeholder")
    client = module.GeminiLlmClient(model="gemini-3.5-flash-lite")
    assert created[0]["http_options"].timeout == 30000
    assert created[0]["http_options"].retry_options.attempts == 1
    assert client.generate("테스트") == "정상 답변"


def test_rag_failure_does_not_fall_back_to_unverified_answer():
    class BrokenRetriever:
        def search(self, text, **kwargs):
            raise RuntimeError("internal confidential endpoint")
    with pytest.raises(AiFailure) as caught:
        AiService._search(BrokenRetriever(), "personal details", k=3)
    assert caught.value.code == ErrorCode.RAG_UNAVAILABLE
    assert caught.value.status == 503
    assert str(caught.value) == "RAG_UNAVAILABLE"
