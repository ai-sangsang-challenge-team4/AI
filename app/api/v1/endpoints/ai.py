from fastapi import APIRouter
from pydantic import BaseModel

from app.schemas.ai import LlmRiskAnalysisResult
from app.schemas.revision import (
    RevisionRequest,
    RevisionResult,
)
from app.services.ai_service import AiService


router = APIRouter(
    prefix="/ai",
    tags=["AI"],
)

ai_service = AiService()


class AiAnalyzeRequest(BaseModel):
    complaint: str


@router.post(
    "/analyze",
    response_model=LlmRiskAnalysisResult,
    summary="학부모 민원 위험 요소 분석",
    description=(
        "학부모 민원 내용을 분석하여 위험 태그, 근거 문구, "
        "신뢰도 및 분석 메타데이터를 반환합니다."
    ),
)
def analyze(
    request: AiAnalyzeRequest,
):
    return ai_service.analyze(
        request.complaint
    )


@router.post(
    "/revision",
    response_model=RevisionResult,
    summary="학부모 민원 표현 수정안 생성",
    description=(
        "민원 위험 분석 결과를 바탕으로 원문의 핵심 의도와 사실관계를 유지하면서 "
        "공격적이거나 부적절한 표현을 완화한 수정안을 생성합니다."
    ),
)
def revision(
    request: RevisionRequest,
):
    return ai_service.revise_complaint(
        request
    )