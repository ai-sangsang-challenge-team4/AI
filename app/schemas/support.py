from pydantic import BaseModel, Field

from app.schemas.input_limits import ComplaintText


class SummaryRequest(BaseModel):
    content: ComplaintText


class SummaryResult(BaseModel):
    summary: str
    modelName: str


class ResponseDraftRequest(BaseModel):
    content: ComplaintText


class RagReference(BaseModel):
    source: str
    page: int | None = None
    content: str


class ResponseDraftResult(BaseModel):
    content: str
    modelName: str
    references: list[RagReference] = Field(default_factory=list)