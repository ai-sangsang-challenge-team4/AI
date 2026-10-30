from pydantic import BaseModel


class EvidenceSpan(BaseModel):
    text: str
    start: int | None = None
    end: int | None = None


class RiskTagResult(BaseModel):
    code: str
    state: str
    confidence: float | None = None
    evidenceSpans: list[EvidenceSpan] = []
    reason: str | None = None


class LlmAnalysisMetadata(BaseModel):
    modelName: str
    temperature: float


class AiAnalysisResult(BaseModel):
    tags: list[RiskTagResult]
    metadata: LlmAnalysisMetadata