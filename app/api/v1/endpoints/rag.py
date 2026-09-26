from fastapi import APIRouter
from pydantic import BaseModel

from app.rag.retriever import RagRetriever


router = APIRouter(prefix="/rag", tags=["RAG"])

retriever = RagRetriever()


class RagSearchRequest(BaseModel):
    query: str


class RagSearchResponse(BaseModel):
    documents: list[str]


@router.post("/search", response_model=RagSearchResponse)
def search(request: RagSearchRequest):
    documents = retriever.search(request.query)

    return RagSearchResponse(
        documents=documents
    )