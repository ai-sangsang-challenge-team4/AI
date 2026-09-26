from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from dotenv import load_dotenv

load_dotenv()

DOCUMENT_DIR = Path("data/documents")
VECTORSTORE_DIR = Path("data/vectorstore")


def load_documents():
    documents = []

    for pdf_path in DOCUMENT_DIR.glob("*.pdf"):
        print(f"Loading: {pdf_path.name}")

        loader = PyPDFLoader(str(pdf_path))
        pdf_documents = loader.load()

        for document in pdf_documents:
            document.metadata["source"] = pdf_path.name

        documents.extend(pdf_documents)

    return documents


def split_documents(documents):
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=150,
    )

    return splitter.split_documents(documents)


def create_vectorstore(chunks):
    embeddings = OpenAIEmbeddings(
        model="text-embedding-3-small"
    )

    vectorstore = FAISS.from_documents(
        chunks,
        embeddings,
    )

    VECTORSTORE_DIR.mkdir(parents=True, exist_ok=True)

    vectorstore.save_local(str(VECTORSTORE_DIR))

    return vectorstore


def main():
    print("=== RAG Ingestion Start ===")

    documents = load_documents()
    print(f"Loaded documents: {len(documents)}")

    chunks = split_documents(documents)
    print(f"Created chunks: {len(chunks)}")

    create_vectorstore(chunks)

    print("=== FAISS Vector Store Created ===")


if __name__ == "__main__":
    main()