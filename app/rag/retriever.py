
from pathlib import Path

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings


VECTORSTORE_DIR = Path("data/vectorstore")
EMBEDDING_MODEL = "BAAI/bge-m3"

DEFAULT_SCORE_THRESHOLD = 0.35
DEFAULT_MAX_RESULTS = 3
DEFAULT_SEARCH_K = 10
DEFAULT_MAX_PER_SOURCE = 2


class RagRetriever:

    def __init__(
        self,
        max_results: int = DEFAULT_MAX_RESULTS,
        max_per_source: int = DEFAULT_MAX_PER_SOURCE,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
        search_k: int = DEFAULT_SEARCH_K,
    ):
        embeddings = HuggingFaceEmbeddings(
            model_name=EMBEDDING_MODEL,
            model_kwargs={
                "device": "cpu",
            },
            encode_kwargs={
                "normalize_embeddings": True,
            },
        )

        self.vectorstore = Chroma(
            collection_name="teacherhub_rag",
            persist_directory=str(VECTORSTORE_DIR),
            embedding_function=embeddings,
        )

        self.max_results = max_results
        self.max_per_source = max_per_source
        self.score_threshold = score_threshold
        self.search_k = search_k

    def search(
        self,
        query: str,
        k: int | None = None,
    ) -> list[dict]:

        limit = k or self.max_results

        search_k = max(
            self.search_k,
            limit * 3,
        )

        results = (
            self.vectorstore
            .similarity_search_with_relevance_scores(
                query,
                k=search_k,
            )
        )

        documents = []
        source_counts: dict[str, int] = {}
        seen_chunks: set[str] = set()

        for document, score in results:

            score = float(score)

            # 명백히 관련성이 낮은 검색 결과 제거
            if score < self.score_threshold:
                continue

            content = document.page_content.strip()

            if not content:
                continue

            # 동일 chunk 중복 제거
            chunk_key = content

            if chunk_key in seen_chunks:
                continue

            seen_chunks.add(chunk_key)

            source = document.metadata.get(
                "source",
                "알 수 없음",
            )

            current_count = source_counts.get(
                source,
                0,
            )

            # 하나의 문서가 검색 결과를 독점하지 않도록 제한
            if current_count >= self.max_per_source:
                continue

            source_counts[source] = current_count + 1

            documents.append(
                {
                    "content": content,
                    "source": source,
                    "page": document.metadata.get("page"),
                    "score": score,
                }
            )

            if len(documents) >= limit:
                break

        return documents
