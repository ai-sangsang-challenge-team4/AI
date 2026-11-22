# Hybrid RAG / Reranker / 정답 기반 평가

## 동작 및 안전한 점진적 도입

- **기본 모드**: 기존 `vector` 검색 그대로 유지. `RAG_RETRIEVAL_MODE=hybrid`로 활성화.
- Hybrid: Chroma BGE-M3 벡터 후보 + 같은 Chroma 컬렉션 전체 청크 BM25 후보를 **RRF(k=60)**로 결합. 원본 Chroma 컬렉션은 읽기 전용으로 접근한다.
- **선택적 Reranker**: `RAG_RETRIEVAL_MODE=hybrid_rerank`와 `RAG_RERANKER_MODEL`을 설정하고 `pip install sentence-transformers` 별도 실행. 예시 모델 `BAAI/bge-reranker-v2-m3`은 로컬 메모리/CPU, 모델 다운로드, 라이선스 확인 후 사용. Reranker 호출 실패 시 hybrid 검색 결과 유지.
- Hybrid 모드의 `score`는 **RRF 점수**로, Vector 모드 Chroma 유사도와 단위가 다르다. 서로 다른 모드의 점수를 직접 비교하거나 같은 임계값을 적용하지 않는다.
- 기존 `/api/v1/rag/search`와 AI 응답 초안 API의 `source/page/content` 계약은 유지한다.
- BM25는 인메모리 컬렉션 스냅샷을 최초 요청에 읽는다. 현재 기본 한도 10,000청크를 초과하면 오류를 반환한다. 인덱스 업데이트는 프로세스 재시작 후 반영된다. 운영에서는 성능/메모리 확인 필수.
- 운영 기본 검색 방식은 바꾸지 않았다. 검색 품질이 개선된다는 결론은 아직 없다.

## 정답 기반 평가

기존 `benchmark/run_rag_benchmark.py`의 평균 유사도는 정답 검색 정확도가 아니다. 다음 JSONL은 **사람이 직접 판단한 PDF 파일명과 0-based 페이지**를 정답으로 사용한다.

예시 구조(예시 파일명과 페이지는 **실제 정답이 아님**):

```json
{"query_id":"DEV-RAG-001","query":"학교폭력 자체해결 요건","relevant":[{"source":"검토한_문서.pdf","page":12}]}
```

평가용 정답은 실제 저장된 출처와 페이지를 확인한 후 `data/private/rag_judgments.jsonl`에 저장한다. 이 경로는 gitignore 대상이다. 원문 민원 개인정보를 공개 저장소에 커밋하지 않는다.

```bash
source .venv/bin/activate
python scripts/evaluate_rag_relevance.py --judgments data/private/rag_judgments.jsonl --mode vector --k 3
python scripts/evaluate_rag_relevance.py --judgments data/private/rag_judgments.jsonl --mode hybrid --k 3
pip install sentence-transformers
python scripts/evaluate_rag_relevance.py --judgments data/private/rag_judgments.jsonl --mode hybrid_rerank --reranker-model BAAI/bge-reranker-v2-m3 --k 3
```

동일 정답셋·k·벡터 DB 기준 비교. `reports/rag_relevance/` 아래에 모드별 `*_cases.csv`, `*_summary.json`을 저장한다.
주요 지표: Recall@K (정답 회수), MRR@K (첫 정답 위치), nDCG@K (정답 순위). **추론 지연시간·메모리·오류율은 별도 측정 필요**. 골든셋을 개별 사례 튜닝에 사용하지 않는다.
