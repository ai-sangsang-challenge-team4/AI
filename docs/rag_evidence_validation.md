# RAG 답변 근거 예비 검증 (opt-in)

교사용 `POST /api/v1/ai/response-draft`에만 적용되는 **선택 기능**입니다. 기본값은 꺼짐입니다. 위험 분석 및 `/api/v1/rag/search`의 기존 동작은 변경하지 않습니다.

## 활성화

```bash
RAG_EVIDENCE_VALIDATION_ENABLED=true RAG_RETRIEVAL_MODE=vector python -m uvicorn app.main:app --port 8000
```

- `RAG_EVIDENCE_VALIDATION_ENABLED` 기본값: `false`.
- `RAG_RETRIEVAL_MODE` 기본값: `vector` (기존 유지).
- Backend 응답 `content`, `modelName`, `references` 필드 변경 없음.

## 검증 로직

1. 비어 있는 청크, 표지·쪽 번호에 불과한 청크, 출처 누락, 잘못된 0-based 페이지, 동일한 청크 중복 제거
2. 질의와 문서 내용의 토큰 또는 2-gram 겹침을 이용한 **보수적 관련성 선별**. 강한 관련성 필터는 아니므로 사람 검토가 필요합니다.
3. 기존 검색 순위 보존; RRF 융합 점수와 Vector 유사도 점수를 서로 비교하지 않음
4. 선별된 근거만 Gemini 프롬프트와 `references`에 전달
5. 근거가 없을 때 법률 요건·기한·조치를 추측하지 않도록 프롬프트에서 명시

문서명에 따른 `document_type`은 연구자료, 매뉴얼, 학교별 규정, 법령을 설명적으로 구분하는 **휴리스틱**입니다. 법적 효력, 최신성, 공신력을 판정하지 않으며, 현 단계에서는 순위 가중치나 필터링에 사용하지 않습니다.

## 알려진 한계

- 텍스트 겹침만으로 근거의 사실적 정합성 또는 답변의 개별 주장까지 검증하지 못합니다.
- 우연한 2-gram 겹침으로 관련성 없는 문서가 통과할 수 있고, 다른 표현을 사용하는 진짜 정답 문서가 탈락할 수도 있습니다.
- 검색된 문서가 `references`에 있다는 사실이 Gemini가 실제로 해당 문장을 사용했다는 뜻은 아닙니다.
- PDF 원문 발행일/유효성 및 학교별 적용 범위는 별도로 검증해야 합니다.
- 예비 평가셋 30건은 이전 검색 결과에 영향을 받았으며, 정답 source/page 일치만 측정합니다. 운영 정확도로 일반화하지 마세요.

## 회귀 확인

```bash
python -m pytest tests/test_evidence_validator.py -v
python -m pytest
```

모드를 끈 기본 환경과 켠 환경에서 교사용 답변 초안에 대해 `content`·`modelName`·`references`를 확인하세요. 올바른 근거가 필터링되지 않는지도 사람이 PDF 본문과 대조해 확인한 후 운영 적용을 결정해야 합니다.
