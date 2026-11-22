"""Strict, content-preserving repair of LLM risk evidence offsets.

Only offsets are repaired. Evidence text is never reworded, whitespace-normalized
or inferred from a Rule candidate or RAG document.
"""
from app.core.errors import AiFailure, ErrorCode


def ground_evidence_spans(complaint: str, tags: list[dict]) -> None:
    """In-place offset validation on normalized LLM tags.

    The LLM may supply wrong character offsets even when its quoted evidence
    is an exact substring. Repair only unambiguous locations; if a span occurs
    more than once without a valid supplied location, retain exact text with
    null offsets. A non-existent quote or malformed offset remains a failure.
    """
    for tag in tags:
        for span in tag["evidenceSpans"]:
            text = span["text"]
            if not isinstance(text, str) or not text or text not in complaint:
                raise AiFailure(ErrorCode.LLM_INVALID_EVIDENCE)

            start, end = span.get("start"), span.get("end")
            if start is None and end is None:
                # Explicitly unlocated quote: preserve original contract.
                continue
            if type(start) is not int or type(end) is not int:
                raise AiFailure(ErrorCode.LLM_INVALID_EVIDENCE)
            if 0 <= start < end <= len(complaint) and complaint[start:end] == text:
                continue

            first = complaint.find(text)
            second = complaint.find(text, first + 1)
            if second >= 0:
                # Never arbitrarily attach a repeated expression to one instance.
                span["start"] = None
                span["end"] = None
            else:
                span["start"] = first
                span["end"] = first + len(text)
