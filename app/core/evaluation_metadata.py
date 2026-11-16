"""Safe execution provenance: hashes/configuration only, never complaint text."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


def evaluation_provenance(documents, retriever):
    root = Path(__file__).resolve().parents[2]
    hashes = {}
    for name in ("app/rag/prompt.py", "app/rag/retriever.py", "app/llm/claude_client.py"):
        path = root / name
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
    return {
        "runtime_git_sha": os.getenv("GIT_SHA"),
        "source_hashes": hashes,
        "prompt_version": os.getenv("PROMPT_VERSION"),
        "rule_version": os.getenv("RULE_VERSION"),
        "rag_version": os.getenv("RAG_VERSION"),
        "rag_index_sha256": os.getenv("RAG_INDEX_SHA256"),
        "rag_documents_sha256": hashlib.sha256(json.dumps(
            documents, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest(),
        "rag_config": {key: getattr(retriever, key, None)
                       for key in ("max_results", "max_per_source", "score_threshold", "search_k")},
    }
