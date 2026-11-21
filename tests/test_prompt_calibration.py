"""Runtime provenance and prompt delivery; these are not live model-quality tests."""
import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.v1.endpoints.ai import get_ai_service
from app.main import create_app
from tests.offline_support import FakeLlm, make_service


def test_risk_prompt_version_comes_from_loaded_source_not_stale_environment(monkeypatch):
    from app.rag import prompt
    monkeypatch.setenv('PROMPT_VERSION', 'stale-deployment-setting')
    client = FakeLlm()
    app = create_app()
    app.dependency_overrides[get_ai_service] = lambda: make_service(client)
    complaint = '가정 학습 상담을 요청합니다.'
    with TestClient(app) as http:
        response = http.post('/api/v1/ai/analyze', json={'complaint': complaint, 'ruleResults': []})
    assert response.status_code == 200
    provenance = response.json()['metadata']['evaluationProvenance']
    assert provenance['prompt_version'] != 'stale-deployment-setting'
    assert provenance['prompt_version'] == getattr(prompt, 'RISK_PROMPT_VERSION', None)
    assert provenance['prompt_version']
    path = Path(prompt.__file__)
    assert provenance['source_hashes']['app/rag/prompt.py'] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert complaint in client.prompts[0]
    assert provenance['prompt_version'] in client.prompts[0]
