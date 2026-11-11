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
#
# Rule 탐지 결과 입력과
# LLM 위험 요소 분석 결과 모두 동일한 구조를 사용한다.
# ============================================================

class RiskTagResult(BaseModel):
    code: RiskTagCode
    state: RiskTagState
    confidence: float | None = None

    # LLM 문맥 기반 심각도 (0~3)
    # BOUNDARY / UNKNOWN은 null
    severity: int | None = Field(
        default=None,
        ge=0,
        le=3,
    )

    # 현재 민원에서 확인된 위험 표현 횟수
    repeatCount: int | None = Field(
        default=None,
        ge=0,
    )
    evidenceSpans: list[EvidenceSpan] = Field(
        default_factory=list
    )
    reason: str | None = None


# ============================================================
# Backend -> AI 위험 요소 분석 요청
#
# complaint:
#   개인정보 마스킹이 적용된 민원 내용
#
# ruleResults:
#   Backend Rule 기반 1차 탐지 결과
#
# Claude는 Rule 결과를 참고하되 그대로 복사하지 않고,
# 전체 문맥을 바탕으로 Rule 미탐지 / 오탐 가능성을
# 2차로 보완 분석한다.
#
# Rule 구현이 완료되지 않았거나
# AI 단독 테스트를 수행하는 경우에도 사용할 수 있도록
# ruleResults의 기본값은 빈 배열로 둔다.
# ============================================================

class AiAnalyzeRequest(BaseModel):
    complaint: str
    ruleResults: list[RiskTagResult] = Field(
        default_factory=list
    )


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

class SafetyFlags(BaseModel):
    credibleThreat: bool | None = None
    studentSafetyConcern: bool | None = None
    privacyExposure: bool | None = None


class LlmRiskAnalysisResult(BaseModel):
    tags: list[RiskTagResult] = Field(
        default_factory=list
    )
    metadata: LlmAnalysisMetadata
    safetyFlags: SafetyFlags | None = None


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