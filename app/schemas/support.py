from pydantic import BaseModel


class SummaryRequest(BaseModel):
    content: str


class SummaryResult(BaseModel):
    summary: str
    modelName: str


class ResponseDraftRequest(BaseModel):
    content: str


class RagReference(BaseModel):
    source: str
    page: int | None = None
    content: str


class ResponseDraftResult(BaseModel):
    content: str
    modelName: str
    references: list[RagReference] = []