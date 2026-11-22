# AI

## 오프라인 검증

Python 3.11 이상에서 테스트 의존성을 설치한 뒤 실행한다.

```bash
python -m pip install -r requirements-test.txt
python -m pytest
python scripts/run_regression.py
python scripts/evaluate_risk_prompt_updated.py --dataset goldenset --validate-only
```

테스트와 데이터 검증은 모델 비밀키 없이 실행한다. LLM·RAG는 모의 의존성을 사용하며 실제 모델 품질은 별도 평가가 필요하다.

- [#26 태깅 평가 명령·데이터·결과 계약](docs/evaluation_contract.md)
- [#33 핵심 20건·운영 로그·#28 미완료 계약](docs/regression_and_logging.md)
- [#26 위험도·세부 유형 정답 양식, 백엔드 결과 평가, 그래프](docs/supplemental_evaluation.md)
- [#26 공개 Backend API로 골든셋 실제 평가·중단 재개·결과 저장](docs/backend_evaluation.md)
