from pydantic import BaseModel


class RiskTagResult(BaseModel):
    code: str
    evidence: str


class AiAnalysisResult(BaseModel):
    risk_tags: list[RiskTagResult]
    summary: str
    draft: str