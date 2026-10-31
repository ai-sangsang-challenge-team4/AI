from typing import Literal

from pydantic import BaseModel, Field


class EvidenceSpan(BaseModel):
    text: str
    start: int | None = None
    end: int | None = None


class ContextAnalysisResult(BaseModel):
    communicationIntent: Literal[
        "INFORMATION_INQUIRY",
        "COUNSELING_REQUEST",
        "ACTION_REQUEST",
        "OBJECTION_COMPLAINT",
        "STATUS_FOLLOWUP",
        "FACT_REPORT",
    ]

    primaryTopic: Literal[
        "ATTENDANCE_SCHEDULE",
        "LEARNING_ASSIGNMENT",
        "ASSESSMENT_GRADE",
        "STUDENT_GUIDANCE",
        "PEER_RELATIONSHIP",
        "TEACHER_INTERACTION",
        "SCHOOL_POLICY_PROCEDURE",
    ]

    secondaryTopics: list[
        Literal[
            "ATTENDANCE_SCHEDULE",
            "LEARNING_ASSIGNMENT",
            "ASSESSMENT_GRADE",
            "STUDENT_GUIDANCE",
            "PEER_RELATIONSHIP",
            "TEACHER_INTERACTION",
            "SCHOOL_POLICY_PROCEDURE",
        ]
    ] = Field(default_factory=list)

    confidence: float
    evidenceSpans: list[EvidenceSpan] = Field(default_factory=list)
    reason: str

    historyRequired: bool = False
    boundaryCase: bool = False
    obfuscationType: str = "NONE"


class RiskTagResult(BaseModel):
    code: str
    state: str
    confidence: float | None = None
    evidenceSpans: list[EvidenceSpan] = Field(default_factory=list)
    reason: str | None = None


class LlmAnalysisMetadata(BaseModel):
    modelName: str
    temperature: float


class AiAnalysisResult(BaseModel):
    context: ContextAnalysisResult
    tags: list[RiskTagResult] = Field(default_factory=list)
    softenedSummary: str | None = None
    metadata: LlmAnalysisMetadata