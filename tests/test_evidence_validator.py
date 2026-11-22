"""Deterministic offline coverage for optional answer-draft evidence validation."""
from app.rag.evidence_validator import document_type, validate_evidence


def test_keeps_relevant_school_violence_manual():
    rows = [
        {"content": "학교폭력 사건 발견 시 학교장에게 즉시 신고합니다.", "source": "안내매뉴얼.pdf", "page": 4},
        {"content": "교과서 대여와 장학금 관련 안내입니다.", "source": "공지.pdf", "page": 1},
    ]
    result = validate_evidence("학교폭력 신고 절차를 알려주세요", rows)
    assert len(result.documents) == 1
    assert result.documents[0]["source"] == "안내매뉴얼.pdf"
    assert result.rejected == 1
    assert not result.insufficient


def test_rejects_bad_metadata_and_duplicates():
    doc = {"content": "학부모 폭언 발생 시 상담을 종료합니다.", "source": "학교민원처리매뉴얼.pdf", "page": 3}
    result = validate_evidence("학부모 폭언 대응", [
        doc, dict(doc), {"content": "자료", "source": "", "page": 2},
        {"content": "학부모 폭언 대응", "source": "매뉴얼.pdf", "page": -1},
    ])
    assert result.documents == [doc]
    assert result.rejected == 3


def test_unknown_or_unrelated_documents_are_insufficient():
    rows = [{"content": "급식 식단과 체육대회 날짜 공지", "source": "공지.pdf", "page": 1}]
    result = validate_evidence("개인정보 유출 신고", rows)
    assert result.documents == []
    assert result.insufficient


def test_no_numeric_similarity_threshold_between_modes():
    rows = [{"content": "학교폭력 신고 절차와 담당자 안내", "source": "매뉴얼.pdf",
             "page": 2, "score": 0.001}]
    result = validate_evidence("학교폭력 신고 절차", rows)
    assert len(result.documents) == 1
    assert result.documents[0]["score"] == 0.001


def test_school_specific_rule_is_classified_separately():
    assert document_type("2026학년도_정발고_학생생활규정.pdf") == "school_policy"
    assert document_type("학교민원+처리+매뉴얼.pdf") == "guidance"
    assert document_type("(2018)_학부모_민원_연구.pdf") == "research"


def test_preserves_order_and_caps_results():
    rows = [
        {"content": f"학교폭력 신고 접수 처리절차 {i}", "source": f"문서{i}.pdf", "page": i}
        for i in range(5)
    ]
    result = validate_evidence("학교폭력 신고 처리절차", rows, limit=2)
    assert [row["page"] for row in result.documents] == [0, 1]


def test_short_generic_question_does_not_remove_good_document():
    rows = [{"content": "학교 내 위기 학생 지도 및 상담 담당자", "source": "지침.pdf", "page": None}]
    result = validate_evidence("방법", rows)
    assert len(result.documents) == 1


def test_response_draft_validation_opt_in(monkeypatch):
    """Exercise response-draft pipeline with stubbed model and retriever."""
    from app.services.ai_service import AiService

    class FakeRetriever:
        def search(self, query, k):
            return [{"content": "전교생 운동회 일정 및 급식표", "source": "공지.pdf", "page": 3}]

    class FakeModel:
        model = "fake-model"
        def generate(self, prompt):
            self.prompt = prompt
            return "확인 후 안내하겠습니다."

    service = AiService.__new__(AiService)
    service.retriever = FakeRetriever()
    service.response_draft_llm_client = FakeModel()
    class Context:
        def model_dump(self):
            return {"type": "test"}
    service.analyze_context = lambda content: Context()

    monkeypatch.setenv("RAG_EVIDENCE_VALIDATION_ENABLED", "true")
    result = service.generate_response_draft("학생 개인정보 유출 신고 절차")
    assert result.references == []
    assert "검색 근거가 부족합니다" in service.response_draft_llm_client.prompt
    assert result.content == "확인 후 안내하겠습니다."

    monkeypatch.delenv("RAG_EVIDENCE_VALIDATION_ENABLED")
    result_default = service.generate_response_draft("학생 개인정보 유출 신고 절차")
    assert len(result_default.references) == 1
    assert "검색 근거가 부족합니다" not in service.response_draft_llm_client.prompt
