from pathlib import Path

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings


VECTORSTORE_DIR = Path("data/vectorstore")
EMBEDDING_MODEL = "BAAI/bge-m3"

DEFAULT_TOP_K = 3
DEFAULT_SCORE_THRESHOLD = 0.35


class RagRetriever:

    def __init__(
        self,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
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

        self.score_threshold = score_threshold

    def search(
        self,
        query: str,
        k: int = DEFAULT_TOP_K,
    ) -> list[dict]:

        results = self.vectorstore.similarity_search_with_relevance_scores(
            query,
            k=k,
        )

        documents = []

        for document, score in results:

            if score < self.score_threshold:
                continue

            documents.append(
                {
                    "content": document.page_content,
                    "source": document.metadata.get("source"),
                    "page": document.metadata.get("page"),
                    "score": float(score),
                }
            )

        return documents
