from pathlib import Path

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings


VECTORSTORE_DIR = Path("data/vectorstore")
EMBEDDING_MODEL = "BAAI/bge-m3"


class RagRetriever:

    def __init__(self):
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