from fastapi import APIRouter
from pydantic import BaseModel

from app.schemas.ai import LlmRiskAnalysisResult
from app.schemas.revision import (
    RevisionRequest,
    RevisionResult,
)
from app.schemas.support import (
    SummaryRequest,
    SummaryResult,
    ResponseDraftRequest,
    ResponseDraftResult,
)
from app.services.ai_service import AiService


router = APIRouter(
    prefix="/ai",
    tags=["AI"],
)

ai_service = AiService()


class AiAnalyzeRequest(BaseModel):
    complaint: str


# ============================================================
# 위험 요소 분석
# ============================================================

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


# ============================================================
# 학부모 민원 표현 수정안
# ============================================================

@router.post(
    "/revision",
    response_model=RevisionResult,
    summary="학부모 민원 표현 수정안 생성",
    description=(
        "위험 분석 결과를 바탕으로 민원의 핵심 의도와 "
        "사실관계를 유지하면서 공격적이거나 부적절한 표현을 "
        "정중하고 객관적인 표현으로 수정합니다."
    ),
)
def revision(
    request: RevisionRequest,
):
    return ai_service.revise_complaint(
        request
    )


# ============================================================
# 민원 완충 요약
# ============================================================

@router.post(
    "/summary",
    response_model=SummaryResult,
    summary="교사용 민원 완충 요약 생성",
    description=(
        "학부모 민원의 핵심 정보는 유지하면서 공격적이거나 "
        "감정적인 표현을 완화한 교사용 요약을 생성합니다."
    ),
)
def summary(
    request: SummaryRequest,
):
    return ai_service.generate_summary(
        request.content
    )


# ============================================================
# 교사용 답변 초안
# ============================================================

@router.post(
    "/response-draft",
    response_model=ResponseDraftResult,
    summary="교사용 AI 답변 초안 생성",
    description=(
        "민원 대화 내용을 분석하고 관련 근거 문서를 검색하여 "
        "교사가 학부모에게 전달할 수 있는 답변 초안을 생성합니다."
    ),
)
def response_draft(
    request: ResponseDraftRequest,
):
    return ai_service.generate_response_draft(
        request.content
    )