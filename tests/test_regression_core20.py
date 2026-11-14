from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.v1.endpoints.ai import get_ai_service
from app.main import create_app
from scripts.evaluation.contracts import build_payload
from scripts.evaluation.regression import assert_conditions, load_core_suite
from tests.offline_support import FakeLlm, make_service, risk_output

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = FIXTURES.parents[1]
SUITE, DATASET = load_core_suite(FIXTURES / "regression_core20.json", ROOT / "data/dev")
MOCK_OUTPUTS = json.loads((FIXTURES / "regression_mock_outputs.json").read_text(encoding="utf-8"))["cases"]
CASES = {case["case_id"]: case for case in DATASET.cases}


@pytest.mark.parametrize("case_spec", SUITE["cases"], ids=lambda spec: spec["case_id"])
def test_core_case(case_spec):
    case_id = case_spec["case_id"]
    captured = MOCK_OUTPUTS[case_id]
    client = FakeLlm(json.dumps(risk_output(captured["states"], captured["evidence"]), ensure_ascii=False))
    service = make_service(client)
    app = create_app()
    app.dependency_overrides[get_ai_service] = lambda: service
    with TestClient(app) as http:
        result = http.post("/api/v1/ai/analyze", json=build_payload(CASES[case_id]))
    if result.status_code != 200:
        pytest.fail(f"{case_id}: HTTP {result.status_code}; offline_contract_failed", pytrace=False)
    assert_conditions(case_spec, result.json())
    assert len(client.prompts) == 1, f"{case_id}: unexpected_retry"
    assert len(service.retriever.calls) == 1, f"{case_id}: RAG_not_reused"


def test_each_condition_detects_a_tag_state_regression():
    # Mutation test: an incorrect state must be caught even when the mock stays valid JSON.
    for case_spec in SUITE["cases"]:
        captured = MOCK_OUTPUTS[case_spec["case_id"]]
        for condition in case_spec["conditions"]:
            changed = risk_output(captured["states"], captured["evidence"])
            tag = next(tag for tag in changed["tags"] if tag["code"] == condition["code"])
            tag["state"] = next(state for state in ("ABSENT", "PRESENT", "BOUNDARY", "UNKNOWN")
                                if state not in condition["allowed_states"])
            with pytest.raises(AssertionError, match=case_spec["case_id"]):
                assert_conditions(case_spec, changed)


def test_expectations_are_partial_and_not_teacher_gold():
    assert len(SUITE["cases"]) == 20
    assert len(MOCK_OUTPUTS) == 20
    for spec in SUITE["cases"]:
        assert 0 < len(spec["conditions"]) < 8
        assert spec["selection_reason"]
        for condition in spec["conditions"]:
            assert condition["human_review_status"] == "pending"
            assert condition["source_label_origin"] == "AI_PROPOSED"


def test_core_suite_rejects_golden_ids_and_dataset_drift(tmp_path):
    changed = copy.deepcopy(SUITE)
    changed["cases"][0]["case_id"] = "G001"
    path = tmp_path / "bad_suite.json"
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="development"):
        load_core_suite(path, ROOT / "data/dev")
    changed = copy.deepcopy(SUITE)
    changed["source_sha256"] = {}
    path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="development data changed"):
        load_core_suite(path, ROOT / "data/dev")
