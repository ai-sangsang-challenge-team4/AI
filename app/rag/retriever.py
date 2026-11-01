from pathlib import Path

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings


VECTORSTORE_DIR = Path("data/vectorstore")
EMBEDDING_MODEL = "BAAI/bge-m3"


class RagRetriever:

    def __init__(
        self,
        max_results: int = 5,
        max_per_source: int = 2,
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

    def search(
        self,
        query: str,
        k: int | None = None,
    ) -> list[dict]:

        limit = k or self.max_results

        # 중복을 줄이기 위해 후보를 넉넉하게 검색
        search_k = max(limit * 3, 10)

        results = (
            self.vectorstore
            .similarity_search_with_relevance_scores(
                query,
                k=search_k,
            )
        )

        documents = []
        source_counts: dict[str, int] = {}

        for document, score in results:

            source = document.metadata.get(
                "source",
                "알 수 없음",
            )

            current_count = source_counts.get(
                source,
                0,
            )

            # 같은 문서가 지나치게 많이 들어오는 것을 방지
            if current_count >= self.max_per_source:
                continue

            source_counts[source] = current_count + 1

            documents.append(
                {
                    "content": document.page_content,
                    "source": source,
                    "page": document.metadata.get("page"),
                    "score": float(score),
                }
            )

            if len(documents) >= limit:
                break

        return documents