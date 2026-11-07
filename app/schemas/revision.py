from pydantic import BaseModel, Field


class RevisionTagInput(BaseModel):
    code: str
    state: str
    confidence: float | None = None
    evidence: str | None = None
    reason: str | None = None


class RevisionRequest(BaseModel):
    complaint: str
    tags: list[RevisionTagInput] = Field(
        default_factory=list
    )
    riskScore: int
    riskLevel: str


class TagRevisionSuggestion(BaseModel):
    code: str
    originalExpression: str
    suggestedExpression: str
    reason: str


class FinalRevision(BaseModel):
    reason: str
    content: str


class RevisionResult(BaseModel):
    finalRevision: FinalRevision
    tagSuggestions: list[TagRevisionSuggestion] = Field(
        default_factory=list
    )