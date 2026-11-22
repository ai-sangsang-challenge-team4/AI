# AI API 안정성 강화 (LLM 호출 실패 대응)

## 범위
Claude / Gemini / RAG 호출 실패를 안전한 오류 코드로 매핑합니다. Backend/Frontend 요청·응답 계약과 운영 설정은 변경하지 않습니다.

| 구성요소 | 제한시간 | 재시도 | 실패 대응 |
| --- | --- | --- | --- |
| Claude | 기존 30초 | 기존 SDK `max_retries=0` | `LLM_TIMEOUT` / `LLM_UNAVAILABLE` |
| Gemini | HTTP 요청 30초 | `HttpRetryOptions(attempts=1)` (재시도 없음) | `LLM_TIMEOUT` / `LLM_UNAVAILABLE` |
| Cloudflare BGE-M3 | 기존 60초 | 별도 자동 재시도 없음 | `RAG_UNAVAILABLE` |
| 답변 초안 RAG | 위 검색 의존성 사용 | 안전하지 않은 무근거 우회 없음 | `RAG_UNAVAILABLE` |

Google Gen AI SDK의 `HttpOptions.timeout` 단위는 **밀리초**입니다. `30_000`은 30초를 뜻하며, 이는 SDK **HTTP 요청별 타임아웃**입니다. 문맥 분석(Claude)·검색(Cloudflare)·답변 생성(Gemini)이 연속 실행되는 API의 전체 제한시간이 30초로 보장되는 것은 아닙니다.

## 보안 및 호환성
- 예외의 원문·`__cause__`를 응답이나 운영 로그에 노출하지 않습니다.
- 시간 초과 → `LLM_TIMEOUT` (504), 나머지 외부 LLM 오류 → `LLM_UNAVAILABLE` (502)
- 텍스트가 없거나 공백만 반환되면 `LLM_INVALID_SCHEMA` (502)로 실패 처리
- RAG 호출 장애 → `RAG_UNAVAILABLE` (503). 법률 근거가 없는 상태로 정상 성공 응답을 만들어 반환하지 않습니다.
- `RAG_RETRIEVAL_MODE=vector`, `RAG_EVIDENCE_VALIDATION_ENABLED=false` 등 기존 기본값 유지
- 비용과 지연을 늘릴 수 있는 일반적인 자동 재시도는 도입하지 않습니다.

## 오프라인 회귀 테스트

```bash
python -m pytest tests/test_ai_resilience.py -v
python -m pytest
```

테스트는 Fake LLM/검색기와 교체한 `genai.Client`만 사용하며 실제 외부 API를 호출하지 않습니다.

## 제한 및 추후 작업

- Gemini 설정은 SDK의 HTTP 요청 단위 제한시간으로, 여러 하위 호출을 포함한 전체 요청 시간 상한을 의미하지 않습니다.
- `response-draft`는 문맥 분석·검색·생성이 순차 실행되어 각 타임아웃의 합에 가까워질 수 있습니다. 앱 전체 데드라인 및 취소 전파는 별도 설계가 필요합니다.
- 공급자별 예외를 모두 분류했다고 단언할 수 없습니다. SDK 업데이트 시 타임아웃 클래스와 재시도 동작을 다시 확인해야 합니다.
- 실제 장애·지연을 평가하려면 테스트 환경에서 공급자 오류 및 네트워크 지연을 주입하여 검증해야 합니다. 운영 배포 전 API 스모크 테스트가 필요합니다.
