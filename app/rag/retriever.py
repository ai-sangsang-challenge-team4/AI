from pathlib import Path

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma


VECTORSTORE_DIR = Path("data/vectorstore")

COLLECTION_NAME = "school_complaint_rag"


class RagRetriever:

    def __init__(self):
        if not VECTORSTORE_DIR.exists():
            raise FileNotFoundError(
                f"Chroma vectorstore가 없습니다: {VECTORSTORE_DIR}\n"
                "먼저 python3 -m app.rag.ingest 를 실행하세요."
            )

        embeddings = GoogleGenerativeAIEmbeddings(
            model="gemini-embedding-001",
        )

        self.vectorstore = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=embeddings,
            persist_directory=str(VECTORSTORE_DIR),
        )

    def search(
        self,
        query: str,
        k: int = 3,
    ) -> list[dict]:

        documents = self.vectorstore.similarity_search(
            query,
            k=k,
        )

        return [
            {
                "content": document.page_content,
                "source": document.metadata.get("source"),
                "page": document.metadata.get("page"),
            }
            for document in documents
        ]