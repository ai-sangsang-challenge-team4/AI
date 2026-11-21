"""Safety Flag 긴급 판정 기준이 위험 태그 판정과 분리되어 있는지 검증한다."""

from app.rag.prompt import build_prompt


def test_safety_flags_require_immediate_protection_not_merely_risk_terms():
    prompt = build_prompt(
        complaint="친구 간 갈등이 있었고 학생이 무섭다고 했습니다.",
        documents=[],
        rule_results=[],
    )

    assert "Backend는 세 Flag 중 하나라도 true이면 EMERGENCY로 강제 승격한다." in prompt
    assert "즉각적인 보호·개입" in prompt
    assert "THREAT=PRESENT여도 credibleThreat=true를 자동 적용하지 않는다." in prompt
    assert "PRIVACY 또는 EXPOSURE=PRESENT여도 privacyExposure=true를 자동 적용하지 않는다." in prompt
    assert "학생 피해·학교폭력 언급만으로 studentSafetyConcern=true를 자동 적용하지 않는다." in prompt


def test_safety_flags_define_true_false_null_for_every_signal():
    prompt = build_prompt(
        complaint="개인정보가 공개됐다고 들었으나 상황은 확인되지 않았습니다.",
        documents=[],
        rule_results=[],
    )

    for name in ("credibleThreat", "studentSafetyConcern", "privacyExposure"):
        part = prompt.split(f"[{name} —", 1)[1].split("\\n[", 1)[0]
        assert "true:" in part
        assert "false:" in part
        assert "null:" in part
    assert "false는 '위험이 전혀 없다'가 아니라" in prompt
    assert "null은 긴급 위험의 존재·시점·상태를 판단할 필수 정보가 부족한 경우다." in prompt
