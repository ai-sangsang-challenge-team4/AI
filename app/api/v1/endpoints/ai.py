from fastapi import APIRouter
from pydantic import BaseModel

from app.schemas.ai import AiAnalysisResult
from app.services.ai_service import AiService


router = APIRouter(prefix="/ai", tags=["AI"])

ai_service = AiService()


class AiAnalyzeRequest(BaseModel):
    complaint: str


@router.post("/analyze", response_model=AiAnalysisResult)
def analyze(request: AiAnalyzeRequest):
    return ai_service.analyze(request.complaint)