from typing import Literal

from pydantic import BaseModel, Field


# ============================================================
# Backend RiskTagCode와 동일한 코드
# ============================================================

RiskTagCode = Literal[
    "PROFANITY",
    "INSULT",
    "THREAT",
    "LEGAL",
    "EXPOSURE",
    "REPEAT",
    "UNFAIR_REQUEST",
    "PRIVACY",
]


# ============================================================
# Backend RiskTagState와 동일한 상태
# ============================================================

RiskTagState = Literal[
    "PRESENT",
    "ABSENT",
    "BOUNDARY",
    "UNKNOWN",
]


# ============================================================
# Backend EvidenceSpan 대응
# ============================================================

class EvidenceSpan(BaseModel):
    text: str
    start: int | None = None
    end: int | None = None


# ============================================================
# Backend RiskTagDetectionResult 대응
# ============================================================

class RiskTagResult(BaseModel):
    code: RiskTagCode
    state: RiskTagState
    confidence: float | None = None
    evidenceSpans: list[EvidenceSpan] = Field(
        default_factory=list
    )
    reason: str | None = None


# ============================================================
# Backend LlmAnalysisMetadata 대응
# ============================================================

class LlmAnalysisMetadata(BaseModel):
    modelName: str
    temperature: float


# ============================================================
# Backend LlmRiskAnalysisResult 대응
#
# 실제 /api/v1/ai/analyze 응답은 반드시 이 구조만 사용한다.
# ============================================================

class LlmRiskAnalysisResult(BaseModel):
    tags: list[RiskTagResult] = Field(
        default_factory=list
    )
    metadata: LlmAnalysisMetadata


# ============================================================
# 이하 AI 내부 문맥 분석용 모델
#
# Backend 응답으로 직접 반환하지 않는다.
# ============================================================

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
    evidenceSpans: list[EvidenceSpan] = Field(
        default_factory=list
    )
    reason: str

    historyRequired: bool = False
    boundaryCase: bool = False
    obfuscationType: Literal[
        "NONE",
        "MASKING",
        "CHOSUNG",
        "NUMBER_SUBSTITUTION",
        "SPACING",
        "OTHER",
    ] = "NONE"


# ============================================================
# AI 내부 분석 결과
#
# 문맥 분석 / 완충 요약 등을 내부적으로 보관하기 위한 모델.
# Backend API 응답에는 사용하지 않는다.
# ============================================================

class InternalAnalysisResult(BaseModel):
    context: ContextAnalysisResult
    tags: list[RiskTagResult] = Field(
        default_factory=list
    )
    softenedSummary: str | None = None
    metadata: LlmAnalysisMetadata
