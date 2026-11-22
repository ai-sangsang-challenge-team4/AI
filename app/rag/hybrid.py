"""Dependency-free BM25 and reciprocal rank fusion for Korean RAG."""
from __future__ import annotations
import math
import re
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256

_WORD = re.compile(r"[가-힣]+|[a-zA-Z]+|\d+")

def tokenize(value: str) -> list[str]:
    result = []
    for match in _WORD.finditer(value.lower()):
        word = match.group()
        result.append(word)
        if len(word) >= 3:
            result.extend(word[i:i + 2] for i in range(len(word) - 1))
    return result

def document_key(content: str, source: str | None, page: int | None) -> str:
    return sha256(f"{source or ''}\x00{page}\x00{content.strip()}".encode()).hexdigest()

@dataclass(frozen=True)
class IndexedChunk:
    content: str
    source: str | None
    page: int | None

    @property
    def key(self) -> str:
        return document_key(self.content, self.source, self.page)

class BM25Index:
    def __init__(self, documents: list[IndexedChunk], k1: float = 1.5, b: float = 0.75):
        self.documents, self.k1, self.b = documents, k1, b
        self.counts = [Counter(tokenize(doc.content)) for doc in documents]
        self.lengths = [sum(counts.values()) for counts in self.counts]
        self.average_length = sum(self.lengths) / len(self.lengths) if self.lengths else 0
        self.df = Counter(term for counts in self.counts for term in counts)

    def search(self, query: str, limit: int = 20) -> list[tuple[IndexedChunk, float]]:
        if not self.documents or limit <= 0:
            return []
        words = set(tokenize(query))
        if not words:
            return []
        scores = []
        size = len(self.documents)
        for index, (counts, length) in enumerate(zip(self.counts, self.lengths)):
            score = 0.0
            for word in words:
                tf = counts.get(word, 0)
                if tf:
                    df = self.df[word]
                    idf = math.log(1 + (size - df + .5) / (df + .5))
                    denominator = tf + self.k1 * (1 - self.b + self.b * length / max(self.average_length, 1))
                    score += idf * tf * (self.k1 + 1) / denominator
            if score > 0:
                scores.append((index, score))
        scores.sort(key=lambda item: (-item[1], self.documents[item[0]].key))
        return [(self.documents[i], score) for i, score in scores[:limit]]

def reciprocal_rank_fusion(rankings: list[list[str]], constant: int = 60) -> list[tuple[str, float]]:
    if constant <= 0:
        raise ValueError("RRF constant must be positive")
    fused: Counter[str] = Counter()
    for ranking in rankings:
        for rank, key in enumerate(dict.fromkeys(ranking), 1):
            fused[key] += 1 / (constant + rank)
    return sorted(fused.items(), key=lambda pair: (-pair[1], pair[0]))
