from pathlib import Path

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter


load_dotenv()

DOCUMENT_DIR = Path("data/documents")
VECTORSTORE_DIR = Path("data/vectorstore")

EMBEDDING_MODEL = "BAAI/bge-m3"


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


def create_embeddings():
    print(f"Loading embedding model: {EMBEDDING_MODEL}")

    return HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={
            "device": "cpu",
        },
        encode_kwargs={
            "normalize_embeddings": True,
        },
    )


def create_vectorstore(chunks):
    embeddings = create_embeddings()

    VECTORSTORE_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    print("Creating Chroma vector store...")

    vectorstore = Chroma.from_documents(
        documents=chunks,
        embedding=embeddings,
        persist_directory=str(VECTORSTORE_DIR),
        collection_name="teacherhub_rag",
    )

    return vectorstore


def main():
    print("=== Chroma RAG Ingestion Start ===")

    documents = load_documents()

    print(f"Loaded documents: {len(documents)}")

    chunks = split_documents(documents)

    print(f"Created chunks: {len(chunks)}")

    create_vectorstore(chunks)

    print("=== Chroma Vector Store Created ===")


if __name__ == "__main__":
    main()