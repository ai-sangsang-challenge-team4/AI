from fastapi import APIRouter
from pydantic import BaseModel

from app.rag.retriever import RagRetriever


router = APIRouter(
    prefix="/rag",
    tags=["RAG"],
)


class RagSearchRequest(BaseModel):
    query: str


class RagSearchResult(BaseModel):
    content: str
    source: str | None = None
    page: int | None = None


class RagSearchResponse(BaseModel):
    documents: list[RagSearchResult]


@router.post(
    "/search",
    response_model=RagSearchResponse,
    summary="민원 관련 근거 문서 검색",
    description=(
        "민원 내용을 기준으로 벡터 검색을 수행하여 "
        "교육활동 보호 및 학교 민원 관련 참고 문서를 반환합니다."
    ),
)
def search(
    request: RagSearchRequest,
):
    retriever = RagRetriever()

    documents = retriever.search(
        request.query
    )

    return RagSearchResponse(
        documents=documents
    )