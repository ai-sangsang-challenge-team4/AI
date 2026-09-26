from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings


VECTORSTORE_DIR = Path("data/vectorstore")


class RagRetriever:

    def __init__(self):
        embeddings = OpenAIEmbeddings(
            model="text-embedding-3-small"
        )

        self.vectorstore = FAISS.load_local(
            str(VECTORSTORE_DIR),
            embeddings,
            allow_dangerous_deserialization=True,
        )

    def search(self, query: str, k: int = 3) -> list[str]:
        documents = self.vectorstore.similarity_search(
            query,
            k=k,
        )

        return [
            document.page_content
            for document in documents
        ]