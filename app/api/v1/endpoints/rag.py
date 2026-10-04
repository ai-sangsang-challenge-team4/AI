from fastapi import APIRouter
from pydantic import BaseModel

from app.rag.retriever import RagRetriever


router = APIRouter(prefix="/rag", tags=["RAG"])


class RagSearchRequest(BaseModel):
    query: str


class RagSearchResult(BaseModel):
    content: str
    source: str | None = None
    page: int | None = None


class RagSearchResponse(BaseModel):
    documents: list[RagSearchResult]


@router.post("/search", response_model=RagSearchResponse)
def search(request: RagSearchRequest):
    retriever = RagRetriever()

    documents = retriever.search(request.query)

    return RagSearchResponse(
        documents=documents
    )