"""Shared input bounds for AI and RAG entry points.

Validate without modifying original complaint text: evidence span offsets refer
to the original characters. These limits constrain text fields, not raw HTTP
request bodies or nested JSON arrays.
"""
from typing import Annotated

from pydantic import AfterValidator, Field

MAX_COMPLAINT_CHARS = 10_000
MAX_SEARCH_QUERY_CHARS = 2_000


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("text must contain non-whitespace characters")
    return value


ComplaintText = Annotated[
    str, Field(min_length=1, max_length=MAX_COMPLAINT_CHARS), AfterValidator(_not_blank)
]

SearchQueryText = Annotated[
    str, Field(min_length=1, max_length=MAX_SEARCH_QUERY_CHARS), AfterValidator(_not_blank)
]
