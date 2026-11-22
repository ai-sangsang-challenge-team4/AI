# AI API 요청 텍스트 입력 검증

## 목적과 범위

LLM/임베딩 호출 전에 빈 내용, 공백만 있는 내용, 과도하게 긴 텍스트를 차단해 불필요한 호출 비용과 지연을 줄입니다. **HTTP 요청 전체의 바이트 크기 제한이나 분당 호출 제한(rate limiting)은 이번 변경 범위가 아닙니다.**

## 입력 제한

| API | 입력 필드 | 최대 길이 |
| --- | --- | --- |
| POST /api/v1/ai/analyze | complaint | 10,000자 |
| POST /api/v1/ai/context | content | 10,000자 |
| POST /api/v1/ai/summary | content | 10,000자 |
| POST /api/v1/ai/revision | complaint | 10,000자 |
| POST /api/v1/ai/response-draft | content | 10,000자 |
| POST /api/v1/rag/search | query | 2,000자 |

- 최소 한 개의 공백이 아닌 문자가 필요합니다. 공백만 포함된 문자열과 빈 문자열을 거절합니다.
- 유효한 입력은 **원문 그대로 전달**됩니다. `strip()`이나 잘라내기를 적용하지 않아 위험 표현의 `evidenceSpans` 인덱스가 바뀌지 않습니다.
- 최대 길이는 Python 문자열의 길이(Unicode 코드 포인트)를 기준으로 합니다. 바이트·토큰 단위 제한이 아닙니다.
- 제한 초과/공백 입력은 FastAPI/Pydantic 입력 검증으로 거절되어, 외부 서비스 호출 전에 기존 보안 미들웨어가 `422` + `INVALID_REQUEST`로 응답합니다. 오류 본문에는 입력 원문이 포함되지 않습니다.
- 응답 스키마 및 정상 요청 반환값은 변경하지 않습니다.
- 비어 있거나 너무 긴 중첩 태그, 배열 등 비텍스트 필드의 제한은 추후 Backend 계약 확인을 거쳐 별도로 다룹니다.

## 검증

```bash
python -m pytest tests/test_ai_input_validation.py -v
python -m pytest
```

테스트는 최대 경계값, 초과 요청, 공백, 외부 호출 미실행, 원문 보존, 정상 RAG 검색, 응답 구조 유지를 오프라인으로 확인합니다.

## 추후 검토

- 정상 민원의 길이 분포를 수집하되 개인정보와 원문은 저장하지 않고 길이만 집계하여 상한을 재평가합니다.
- 과도한 JSON 전체 크기 제한은 프록시/ASGI 레이어에서 적용하는 별도 작업이 필요합니다.
- IP/사용자별 실제 호출 빈도 제한은 인증/프록시/Backend 연동 계약을 확인한 뒤 별도 작업으로 설계해야 합니다.
