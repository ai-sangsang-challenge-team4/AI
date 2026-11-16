import hashlib
from pathlib import Path

from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from app.rag.cloudflare_embeddings import CloudflareBgeM3Embeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter


load_dotenv(dotenv_path=".env")

DOCUMENT_DIR = Path("data/documents")
VECTORSTORE_DIR = Path("data/vectorstore_test")

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


def clean_chunks(chunks):
    """동일 출처의 중복 내용과 쪽 번호만 있는 chunk 제거."""
    cleaned = []
    seen = set()

    for chunk in chunks:
        text = " ".join(chunk.page_content.split())

        if not text or text.isdecimal():
            continue

        source = str(chunk.metadata.get("source", "unknown"))
        key = (source, text)

        if key in seen:
            continue

        seen.add(key)
        cleaned.append(chunk)

    return cleaned


def create_embeddings():
    print("Using Cloudflare BGE-M3 embeddings")
    return CloudflareBgeM3Embeddings()


def create_vectorstore(chunks):
    """테스트 DB에 결정적 ID로 적재하고 중단 시 재개한다."""
    import chromadb

    # 운영 DB에 실수로 적재하지 않도록 차단
    production = Path("data/vectorstore").resolve()
    target = VECTORSTORE_DIR.resolve()

    if target == production:
        raise RuntimeError("Production vector store ingestion blocked")

    VECTORSTORE_DIR.mkdir(parents=True, exist_ok=True)

    client = chromadb.PersistentClient(path=str(VECTORSTORE_DIR))
    collection_name = "teacherhub_rag"

    existing_names = [c.name for c in client.list_collections()]
    if collection_name in existing_names:
        collection = client.get_collection(collection_name)
        existing_ids = set(collection.get(include=[])["ids"])

        # 이전에 다른 ID 방식으로 만든 DB와 혼합 방지
        if existing_ids and not all(
            item.startswith("tc-v2-") for item in existing_ids
        ):
            raise RuntimeError(
                "Existing collection uses another ID scheme. "
                "Ingestion blocked."
            )
    else:
        existing_ids = set()

    embeddings = create_embeddings()
    vectorstore = Chroma(
        collection_name=collection_name,
        persist_directory=str(VECTORSTORE_DIR),
        embedding_function=embeddings,
    )

    batch_size = 16
    pending = []

    for chunk in chunks:
        source = str(chunk.metadata.get("source", "unknown"))
        page = str(chunk.metadata.get("page", ""))
        text = " ".join(chunk.page_content.split())

        key = "\\n".join([source, page, text])
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        doc_id = f"tc-v2-{digest}"

        if doc_id in existing_ids:
            continue

        existing_ids.add(doc_id)
        pending.append((doc_id, chunk))

    print(f"Already stored: {collection.count() if collection_name in existing_names else 0}")
    print(f"Remaining chunks: {len(pending)}")

    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]

        vectorstore.add_documents(
            documents=[chunk for _, chunk in batch],
            ids=[doc_id for doc_id, _ in batch],
        )

        print(
            f"Embedded {min(start + batch_size, len(pending))}"
            f"/{len(pending)} remaining chunks",
            flush=True,
        )

    return vectorstore


def main():
    print("=== Chroma RAG Ingestion Start ===")

    documents = load_documents()

    print(f"Loaded documents: {len(documents)}")

    chunks = split_documents(documents)

    print(f"Created chunks: {len(chunks)}")

    chunks = clean_chunks(chunks)

    print(f"Cleaned chunks: {len(chunks)}")

    create_vectorstore(chunks)

    print("=== Chroma Vector Store Created ===")


if __name__ == "__main__":
    main()