"""Public failures carry only an allowlisted code, never upstream messages."""
from enum import Enum


class ErrorCode(str, Enum):
    OK = "OK"
    INVALID_REQUEST = "INVALID_REQUEST"
    NOT_FOUND = "NOT_FOUND"
    HTTP_ERROR = "HTTP_ERROR"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_UNAVAILABLE = "LLM_UNAVAILABLE"
    LLM_INVALID_JSON = "LLM_INVALID_JSON"
    LLM_INVALID_SCHEMA = "LLM_INVALID_SCHEMA"
    LLM_INVALID_EVIDENCE = "LLM_INVALID_EVIDENCE"
    RAG_UNAVAILABLE = "RAG_UNAVAILABLE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


STATUS = {
    ErrorCode.LLM_TIMEOUT: 504,
    ErrorCode.LLM_UNAVAILABLE: 502,
    ErrorCode.LLM_INVALID_JSON: 502,
    ErrorCode.LLM_INVALID_SCHEMA: 502,
    ErrorCode.LLM_INVALID_EVIDENCE: 502,
    ErrorCode.RAG_UNAVAILABLE: 503,
    ErrorCode.INVALID_REQUEST: 422,
    ErrorCode.NOT_FOUND: 404,
}


class AiFailure(RuntimeError):
    def __init__(self, code: ErrorCode):
        self.code = ErrorCode(code)
        self.status = STATUS.get(self.code, 500)
        super().__init__(self.code.value)
