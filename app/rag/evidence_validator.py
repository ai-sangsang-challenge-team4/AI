"""Conservative, opt-in filtering of RAG evidence for teacher response drafts.

The retriever's dense scores and hybrid RRF scores are on incompatible scales.
This module intentionally does not compare these numeric scores.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
import re
import unicodedata

# Keep this module importable in the offline test suite without LangChain/Chroma.
def _low_quality_chunk(content: str) -> bool:
    text = " ".join(content.split())
    return not text or text.isdecimal() or text in {
        "학교민원 처리 매뉴얼",
        "학교민원 처리 매뉴얼 학교민원 처리 매뉴얼",
        "학교민원 처리 기본 원칙 및 절차",
    }


_TOKEN = re.compile(r"[가-힣a-zA-Z0-9]{2,}")
_STOPWORDS = frozenset({
    "학교", "학생", "교사", "학부모", "관련", "경우", "어떻게", "어떤",
    "대한", "위한", "있나요", "합니다", "해주세요", "방법", "조치",
    "절차", "알려주세요", "알려", "있는", "교원", "학교에서",
})


@dataclass(frozen=True)
class EvidenceReview:
    documents: list[dict]
    rejected: int
    insufficient: bool


def document_type(source: str | None) -> str:
    """Descriptive heuristic only; not a determination of legal authority."""
    name = unicodedata.normalize("NFC", str(source or "")).lower()
    if "연구" in name or "논문" in name:
        return "research"
    if "매뉴얼" in name or "해설서" in name or "가이드" in name:
        return "guidance"
    if "학교규칙" in name or "학생생활규정" in name:
        return "school_policy"
    if "법률" in name or "시행령" in name or "고시" in name:
        return "regulation"
    return "unclassified"


def _tokens(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFC", text).lower()
    return {term for term in _TOKEN.findall(normalized) if term not in _STOPWORDS}


def _bigrams(text: str) -> set[str]:
    # For Korean inflections, adjacent-character overlap provides a fallback
    # when whitespace tokens do not match exactly.
    normalized = unicodedata.normalize("NFC", text).lower()
    tokens = [term for term in _TOKEN.findall(normalized) if term not in _STOPWORDS]
    return {token[i:i + 2] for token in tokens for i in range(len(token) - 1)}


def _relevant(query: str, content: str) -> bool:
    query_terms = _tokens(query)
    if not query_terms:
        # Short/generic questions should not trigger arbitrary evidence deletion.
        return True
    doc_terms = _tokens(content)
    if query_terms & doc_terms:
        return True
    query_grams = _bigrams(query)
    if len(query_grams) < 3:
        return True
    overlap = len(query_grams & _bigrams(content)) / len(query_grams)
    return overlap >= 0.20


def validate_evidence(query: str, documents: list[dict], *, limit: int = 3) -> EvidenceReview:
    """Return verified-for-retrieval candidates; no claim-level factual validation.

    This is a conservative lexical heuristic, not proof that a document supports
    every assertion in the eventual model answer. Maintains original rank order.
    """
    kept: list[dict] = []
    seen: set[tuple[str, int | None, str]] = set()
    rejected = 0
    for row in documents:
        content = str(row.get("content") or "").strip()
        source = str(row.get("source") or "").strip()
        page = row.get("page")
        if not content or _low_quality_chunk(content) or not source or source == "알 수 없음":
            rejected += 1
            continue
        if isinstance(page, bool) or (page is not None and (not isinstance(page, int) or page < 0)):
            rejected += 1
            continue
        normalized_source = unicodedata.normalize("NFC", PurePath(source).name)
        normalized_content = " ".join(unicodedata.normalize("NFC", content).split())
        identity = (normalized_source, page, normalized_content)
        if identity in seen:
            rejected += 1
            continue
        seen.add(identity)
        if not _relevant(query, content):
            rejected += 1
            continue
        kept.append(dict(row))
        if len(kept) >= limit:
            break
    return EvidenceReview(documents=kept, rejected=rejected, insufficient=not bool(kept))
