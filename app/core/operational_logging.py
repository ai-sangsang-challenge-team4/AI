"""Allowlisted operational events, independent from evaluation report files."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from contextvars import ContextVar
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from starlette.responses import JSONResponse

from app.core.errors import AiFailure, ErrorCode

LOGGER_NAME = "teachercare.operations"
LOGGER = logging.getLogger(LOGGER_NAME)
FIELDS = ("request_id", "endpoint", "model_name", "prompt_version", "latency_ms", "success", "error_code")
ENDPOINTS = frozenset(("/", "/api/v1/ai/analyze", "/api/v1/ai/context", "/api/v1/ai/summary",
                       "/api/v1/ai/revision", "/api/v1/ai/response-draft", "/api/v1/rag/search",
                       "/openapi.json", "/docs", "/redoc"))
# Configuration and remote model output must not become arbitrary log strings.
MODELS = frozenset(("claude-sonnet-4-6", "claude-haiku-4-5", "claude-opus-4-6",
                    "gemini-3.5-flash-lite", "gemini-3.8-flash", "bge-m3", "unknown"))
QUIET_LOGGERS = ("anthropic", "google", "google_genai", "httpx", "httpcore", "urllib3",
                 "requests", "langchain", "langchain_core", "chromadb", "uvicorn.access", "uvicorn.error")


@dataclass
class RequestContext:
    request_id: str
    endpoint: str
    model_name: str = "unknown"
    prompt_version: str = "unknown"


CURRENT_REQUEST = ContextVar("teacher_care_request", default=None)


@lru_cache(maxsize=1)
def prompt_version():
    root = Path(__file__).resolve().parents[2]
    digest = hashlib.sha256()
    # Includes the inline response/revision prompts as well as app/rag/prompt.py.
    for name in ("app/rag/prompt.py", "app/services/ai_service.py"):
        digest.update((root / name).read_bytes())
    return "sha256:" + digest.hexdigest()


def record_model(model):
    context = CURRENT_REQUEST.get()
    if context is not None:
        context.model_name = model if isinstance(model, str) and model in MODELS else "unknown"


class SafeJsonFormatter(logging.Formatter):
    def format(self, record):
        # Never call getMessage(), formatException(), or serialize arbitrary extra fields.
        source = getattr(record, "safe_event", {})
        if not isinstance(source, dict):
            source = {}
        event = {
            "request_id": source.get("request_id", ""), "endpoint": source.get("endpoint", "unmatched"),
            "model_name": source.get("model_name", "unknown"),
            "prompt_version": source.get("prompt_version", "unknown"),
            "latency_ms": source.get("latency_ms", 0), "success": source.get("success", False),
            "error_code": source.get("error_code", ErrorCode.INTERNAL_ERROR.value),
        }
        for field in ("request_id", "endpoint", "model_name", "prompt_version", "error_code"):
            if not isinstance(event[field], str):
                event[field] = "unknown"
        if not isinstance(event["request_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", event["request_id"]):
            event["request_id"] = "unknown"
        if event["endpoint"] not in ENDPOINTS:
            event["endpoint"] = "unmatched"
        if event["model_name"] not in MODELS:
            event["model_name"] = "unknown"
        if not isinstance(event["prompt_version"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", event["prompt_version"]):
            event["prompt_version"] = "unknown"
        if event["error_code"] not in {code.value for code in ErrorCode}:
            event["error_code"] = ErrorCode.INTERNAL_ERROR.value
        if type(event["latency_ms"]) not in (int, float) or not 0 <= event["latency_ms"] < float("inf"):
            event["latency_ms"] = 0
        event["success"] = event["success"] is True
        return json.dumps(event, ensure_ascii=False, allow_nan=False)


def configure_operational_logging():
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    if not LOGGER.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(SafeJsonFormatter())
        LOGGER.addHandler(handler)
    # SDK debug/access/error messages can contain headers, URLs and response bodies.
    # A NullHandler also prevents logging.lastResort from printing them.
    names = set(QUIET_LOGGERS)
    names.update(name for name in logging.Logger.manager.loggerDict
                 if any(name.startswith(prefix + ".") for prefix in QUIET_LOGGERS))
    for name in names:
        logger = logging.getLogger(name)
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False


def status_code(status):
    if status < 400:
        return ErrorCode.OK
    if status == 404:
        return ErrorCode.NOT_FOUND
    if status in (400, 422):
        return ErrorCode.INVALID_REQUEST
    return ErrorCode.HTTP_ERROR


def failure_response(code, request_id, status):
    return JSONResponse({"error": {"code": code.value}, "requestId": request_id}, status_code=status,
                        headers={"X-Request-ID": request_id})


class OperationalMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        # Do not trust caller IDs, raw paths, queries, or headers as log fields.
        path = scope.get("path", "")
        context = RequestContext(uuid4().hex, path if path in ENDPOINTS else "unmatched",
                                 prompt_version=prompt_version())
        token = CURRENT_REQUEST.set(context)
        started = perf_counter()
        status, code = 500, ErrorCode.INTERNAL_ERROR
        messages = []

        async def capture(message):
            # Current endpoints return bounded JSON, so buffer until the request succeeds.
            # This also replaces framework error bodies that contain Pydantic input values.
            messages.append(message)

        try:
            try:
                await self.app(scope, receive, capture)
                initial = next((message for message in messages if message["type"] == "http.response.start"), None)
                status = initial["status"] if initial else 500
                code = status_code(status)
            except AiFailure as exc:
                status, code = exc.status, exc.code
            except Exception as exc:
                # Pydantic/response validation errors can embed the complete model output.
                if type(exc).__name__ in ("ValidationError", "ResponseValidationError"):
                    status, code = 502, ErrorCode.LLM_INVALID_SCHEMA
                else:
                    status, code = 500, ErrorCode.INTERNAL_ERROR
            if status >= 400:
                await failure_response(code, context.request_id, status)(scope, receive, send)
            else:
                for message in messages:
                    if message["type"] == "http.response.start":
                        message["headers"] = [(key, value) for key, value in message.get("headers", [])
                                              if key.lower() != b"x-request-id"] + [(b"x-request-id", context.request_id.encode())]
                    await send(message)
        finally:
            event = {"request_id": context.request_id, "endpoint": context.endpoint,
                     "model_name": context.model_name, "prompt_version": context.prompt_version,
                     "latency_ms": round((perf_counter() - started) * 1000, 3),
                     "success": status < 400, "error_code": code.value}
            LOGGER.info("request_completed", extra={"safe_event": event})
            CURRENT_REQUEST.reset(token)
