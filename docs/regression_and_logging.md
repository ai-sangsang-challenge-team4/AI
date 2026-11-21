# #33 오프라인 회귀 테스트와 운영 로그

## 실행 및 확인 범위

애플리케이션 팩터리는 SDK·검색기 생성 전에 `.env`를 명시적으로 읽는다. Gemini 모듈 import의 부수 효과에 의존하지 않는다. 오프라인 테스트는 실제 `.env` 재로딩도 차단하며, 초기화 순서는 임시 파일의 합성 설정값으로 검증한다.

Python 3.11 이상에서 테스트 의존성만 설치하고 저장소 루트에서 실행한다.

```bash
python -m pip install -r requirements-test.txt
python -m pytest
python scripts/run_regression.py
```

테스트 실행 자체에는 비밀키·네트워크가 필요 없다. 이미 의존성이 설치된 환경에서는 설치 단계도 생략한다.
CI와 새 실행기 검증은 Python 3.11을 사용한다. 가벼운 테스트 의존성 버전은 `requirements-test.txt`에 고정한다.

`pytest.ini`는 `tests/`만 기본 수집하고 `benchmark/`, `reports/`를 재귀 수집에서 제외한다. `benchmark/test_models.py` 같은 외부 연결 스크립트를 기본 pytest에서 실행하지 않는다. 실제 provider SDK·Chroma·임베딩 패키지는 테스트 의존성에 없다.

`tests/conftest.py`가 각 테스트에서 API Key 환경변수를 제거하고 socket 연결을 실패시킨다. FastAPI TestClient는 실제 HTTP 소켓 대신 ASGI 앱을 직접 호출한다. 모델·검색기만 대체하고 실제 라우팅·서비스·프롬프트 조립·출력 검증·오류 응답·로그 코드를 실행한다. 20건 모두 개발 CSV에서 읽으며 골든셋을 회귀 정답으로 사용하지 않는다. #26의 별도 데이터 검증 테스트는 기존처럼 골든셋 구조를 확인한다.

**이 결과는 오프라인 계약 검증이다. 실제 모델 품질·프롬프트 개선 효과·검색 품질의 검증이 아니다.** 고정 모의 응답이 올바르게 처리되고 부분 상태 조건이 집행되는지 확인한다. 실제 모델이 같은 태그를 판정한다는 주장은 하지 않는다. 프롬프트 문장만 바뀌면 모의 응답이 자동으로 달라지지도 않는다. 실제 품질은 별도로 승인한 LLM/RAG 실행 후 #26 평가기로 측정해야 한다.

## 한 명령으로 실행하고 실제 응답의 퇴행 확인

`python scripts/run_regression.py`는 핵심 20건, 가드레일, 운영 로그 테스트를 실행하고
`reports/regression/<UTC>_<버전>_<고유-ID>/`에 `summary.json`, `manifest.json`,
`offline_aggregate.json`, `failures.csv`를 저장한다. 실행마다 새 폴더를 만들며 이전 결과를 덮어쓰지 않는다.
실패 시 사례 ID와 제한된 실패 이유를 출력한다. 자식 pytest의 원본 출력·traceback은 보관하거나
재출력하지 않는다. 집계 파일에는 사례 ID·원문·모델 출력이 없다.

기본 실행은 네트워크·키·모델 비용 없이 동작한다. `summary.json.model_regression.status`는
`not_run`이다. #28의 예상 실패 3개는 `pending_guardrails`에 별도로 표시하며 통과로 합산하지 않는다.
미완료 가드레일이 있으면 명령 자체도 실패해야 하는 검토 단계에서는 다음 옵션을 사용한다.

```bash
python scripts/run_regression.py --require-complete-guardrails
```

실제 판정 퇴행은 **개발셋** 응답으로 검사한다. 아래 둘 중 하나를 같은 실행 명령에 지정한다.

```bash
# #26 개발셋 평가기가 저장한 응답 재사용: 추가 모델 호출 없음
python scripts/run_regression.py \
  --predictions reports/<개발셋-실행>/predictions.jsonl --run-version saved-dev-v1

# AI 서버 직접 실행: 20건의 유료 LLM/RAG 요청이 발생함
python scripts/run_regression.py \
  --base-url http://127.0.0.1:8000 --run-version prompt-v2
```

`--base-url`은 Backend 로그인/민원 API가 아닌 AI `/api/v1/ai/analyze` 서버의 origin이다.
localhost는 이 명령을 실행하는 컴퓨터를 뜻한다. 서버 내부에서 실행하거나 SSH 포워딩한 경우에만
해당 localhost를 사용한다. 원격 서버에는 HTTPS가 필요하다. URL에 인증 정보·query를 넣지 않는다.
이번 구현 검증에서는 유료 모델이나 공개 Backend에 추가 요청을 보내지 않았다.

`--mode rule_llm --rule-results <개발사례별-Rule-결과.json>`으로 실제 Rule 문맥을 함께 전달할 수 있다.
Rule 결과는 별도로 캡처한 값이어야 하며, 개발 라벨에서 만들지 않는다. 요청에는 원문과
허용된 Rule 필드만 넣고 기대 정답·선정 이유·원본 라벨은 전달하지 않는다. REPEAT와 최종 위험도
Emergency 판정은 이 20건의 정답 조건에 포함하지 않는다. `urgent_response` 사례의 THREAT
조건은 최종 Emergency 위험도 정답을 의미하지 않는다.

저장 응답은 `case_id`, `mode`, `input_sha256`, `complaint_sha256`,
`source_provenance_verified`, `request_success`, `response`를 갖는 #26 형식을 사용한다.
현재 개발셋 입력과 해시가 맞고 provenance가 확인된 응답만 조건을 검사한다. 이는 기록의 일치
검사이며 모델 실행의 진위를 인증하는 기능은 아니다. 이 정보가 없는 임의 JSON, 누락된 사례,
요청 실패, 중복 ID, 골든셋 ID, 다른 입력의 응답을 정상 결과로 보정하지 않는다. 개발셋 100건
전체 파일을 주면 선정된 20건만 검사한다. 사람 검토 대기인 33개 부분 기대 조건을 사용한다는
사실은 실제 응답 검사 결과에도 기록한다.

실제 응답 모드에서는 `model_regression`에 조건 통과/실패, 실패 사례 목록을 저장하고,
`failures.csv`에는 사례·태그·기대 상태·실제 상태·제한된 오류 코드를 쓴다. 태깅 지표·예측·버전은
하위 `tagging/`의 기존 #26 보고서에 보존한다. live 요청의 완료 응답도 사례마다 체크포인트에
동기 저장한다. 오프라인 테스트·로그 검사나 엄격 가드레일 조건이 실패하면 모델 요청을 시작하지 않는다.
live 요청의 HTTP·출력 계약 검증이 실패하면 후속 요청도 중단한다. 완료 기록과 실패·미시도
coverage는 보존하며 누락 사례를 통과로 처리하지 않는다. 유효한 응답의 기대 상태 불일치는
20건 수집 후 모두 보고한다.

저장 예측·Rule 입력은 오프라인 테스트 전에 실행 폴더에 권한 600의 스냅샷으로 복사하고,
그 바이트를 평가·해시 기록에 함께 사용한다. 테스트 중 원본 파일이 바뀌어도 서로 다른 버전이
섞이지 않는다. 스냅샷·상세 태깅 보고서는 원문을 포함할 수 있으므로 기존처럼 Git 추적과
CI 기본 업로드에서 제외한다.

종료 코드는 0=요청한 검사 통과, 1=검사 실패, 2=입력/실행 오류다. 기본 모드의 0은 실제 모델
품질 평가나 #28 전체 완료를 뜻하지 않는다. `guardrails_complete`와
`human_expectation_review_complete`를 별도로 확인한다.

## 핵심 20건과 기대 조건

`tests/fixtures/regression_core20.json`에 선정 이유·범주·부분 상태 조건·근거·원본 라벨 검토 표시를 기록했다. 총 **20건 / 33개 조건**이며 모든 조건의 `human_review_status`는 `pending`이다.

| 사례 | 주요 목적 | 반드시 유지할 부분 조건 |
| --- | --- | --- |
| DEV002 | 강한 회신 요청의 협박 과탐 방지 | THREAT ABSENT |
| DEV003 | 구체적 신체 위해 / 긴급 대응 후보 | THREAT PRESENT |
| DEV005 | 정당한 오류 확인과 기한 압박의 경계 | UNFAIR_REQUEST BOUNDARY, THREAT ABSENT |
| DEV007 | 교육청 상담 절차 문의 | LEGAL PRESENT, THREAT ABSENT |
| DEV008 | 특수문자 우회 위해 표현 | THREAT PRESENT |
| DEV009 | 우회 표기 공개 압박 | EXPOSURE·THREAT PRESENT |
| DEV010 | 학생 보호·대안 문의 | THREAT·UNFAIR_REQUEST ABSENT |
| DEV011 | 학교 공간 위해 예고 / 긴급 대응 후보 | THREAT PRESENT |
| DEV017 | 기한부 공개 압박 | EXPOSURE·THREAT PRESENT |
| DEV018 | 자모 분리 비속어와 개인 공격 | PROFANITY·INSULT PRESENT, THREAT ABSENT |
| DEV019 | 정중한 어투 속 압박 경계 | THREAT BOUNDARY, LEGAL PRESENT |
| DEV033 | 공식 고충 절차와 후속 문의 | LEGAL PRESENT, THREAT ABSENT |
| DEV037 | 초성 표현과 구체적인 침입 예고 | THREAT PRESENT |
| DEV040 | 숫자 치환 욕설 / 대상 없는 감정 | PROFANITY PRESENT, INSULT ABSENT |
| DEV059 | 학생 안전 신호와 발신자 위협 구분 | THREAT ABSENT |
| DEV064 | 학생 상담 요청의 과탐 방지 | THREAT ABSENT |
| DEV066 | 마스킹 원어 임의 복원 방지 | PROFANITY BOUNDARY, THREAT ABSENT |
| DEV069 | 띄어쓰기 우회 절차 언급 / 압박 경계 | LEGAL PRESENT, THREAT BOUNDARY |
| DEV080 | 제3자 위험 제보의 협박 과탐 방지 | THREAT ABSENT |
| DEV098 | 띄어쓰기 욕설과 개인 공격 구분 | PROFANITY PRESENT, INSULT ABSENT |

`basis`는 개발 라벨의 AI 제안 근거이며 교사 확정 판정이 아니다. `source_review_required=false`도 교사 검토 완료를 뜻하지 않는다. 각 조건에는 `source_label_origin=AI_PROPOSED`, 원본 상태·검토 표시, 사람 검토 대기 상태를 함께 남겼다. 학생 안전 사례를 포함했어도 Emergency 위험도나 safetyFlags 정답은 생성하지 않았다. 이력 없는 비교의 REPEAT는 #26처럼 제외한다.

`regression_mock_outputs.json`은 사람이 검토할 조건과 별도로 고정한 **합성 모의 출력**이다. 8종 전체 JSON 일치 비교는 하지 않는다. 테스트 지원 코드가 유효한 응답 외형을 만들고 `scripts/evaluation/regression.py`가 #26의 엄격한 태그 계약과 부분 조건만 검사한다. 모의 severity·repeatCount·null safetyFlags는 구조 실행용이며 정답·품질 지표가 아니다.

조건이 깨지면 `DEV003: THREAT expected=PRESENT actual=ABSENT`처럼 사례 ID와 상태 불일치 이유를 출력한다. 33개 조건 각각에 잘못된 상태를 주입해 탐지 여부도 검사한다. 개발 CSV 해시가 달라지면 자동으로 기대 조건을 재생성하지 않고 검토를 요구한다. 프롬프트에 잘못된 판정이 생겼다는 이유로 기대 조건을 맞춰 바꾸는 자동 재기준화는 없다.

## 이번에 구현한 최소 가드레일 / #28 담당자 확인

이번 변경으로 실제 동작하는 부분:

- 허용 태그·상태, 중복·누락 8종, severity/count 조합, safetyFlags 구조 검사
- 잘못된 근거 컨테이너·숫자/null 근거·빈 문구를 빈 배열로 지우지 않고 스키마 실패로 처리
- 깨진 JSON·스키마 불일치·원문 밖 근거에 대해 위험 태깅 출력 한 번 재시도
- 두 번 모두 실패하면 502와 제한된 오류 코드 반환. 정상 태그를 임의 생성하지 않음
- 근거가 마스킹된 입력 원문에 없으면 응답 전체를 거부하는 최소 차단
- timeout은 504, provider 오류는 502. 자유 형식 예외·응답 전문을 로그/실패 응답에 포함하지 않음
- Claude SDK의 30초 timeout과 `max_retries=0`으로 애플리케이션 재시도와 SDK 재시도의 중첩 방지

비어 있지 않은 근거 문자열·문자열 배열은 기존 호환성을 위해 EvidenceSpan 객체 배열로 변환한다. 객체의 `text`도 비어 있지 않은 문자열이어야 한다. `[]`는 기존 계약대로 허용하므로 이 검사가 PRESENT의 필수 근거 개수 정책을 추가하는 것은 아니다.

위험 태깅은 잘못된 출력에 대해 최대 2회 생성하고 동일한 검색 결과와 프롬프트를 재사용한다. timeout·provider 오류는 애플리케이션에서 재시도하지 않는다. 문맥 분석·요약·수정·초안은 같은 안전 오류 경계를 사용하지만 출력 수정이나 추가 생성 검증을 구현한 것은 아니다. Gemini SDK 내부 정책은 이번에 변경하지 않았다.

아래 3개는 **구현 완료가 아니다**. `pending_guardrail`과 `xfail(strict=True, raises=AssertionError)`로 남겼다. 예상 실패는 통과 수와 분리하며, 구현되어 예상과 달리 통과하면 strict XPASS로 CI가 실패해 테스트 전환을 요구한다.

| 미완료 계약 | 현재 동작 | #28 담당자 확인 사항 |
| --- | --- | --- |
| 근거가 원문에 없는 PRESENT를 BOUNDARY로 하향 | 재시도 후 502 거부 | 하향 시 severity·repeatCount=null 및 안전 신호 처리 합의 |
| 구조화 이력 없는 REPEAT PRESENT 강제 방지 | 아직 모델 PRESENT를 강제 보정하지 않음 | UNKNOWN 전환과 규칙/이력 신호의 충분성 정의 |
| 요약에 새 숫자·날짜·이름이 생기는 경우 차단 | 문자열 출력 그대로 반환 | 검출 방식·오탐 허용·실패/경고 계약 정의 |

가짜 태그는 현재 전체 출력을 거부한다. #28의 “잘못된 태그 폐기”를 조용한 누락 태그 정상 처리로 해석하지 않았다. 폐기·재시도 뒤에도 #26의 8종 계약을 만족해야 한다. RAG에 없는 법령 인용 경고, 수정안 의도 보존, 생성된 이름/숫자/날짜 전반 검증도 담당자 작업이며 이번에 완료했다고 표시하지 않는다. 위 3개 xfail은 그중 명시적인 계약 예제이며 #28 전체 테스트 목록을 대체하지 않는다.

현재 상태에서 PR CI 녹색은 **이 3개 미완료 계약까지 완료되었다는 의미가 아니다.** 사람 검토 및 #28 이슈 추적을 유지해야 한다.

## 운영 로그와 실패 응답

`app/core/operational_logging.py`가 각 요청에 대해 다음 7개 필드만 JSON 한 줄로 stderr에 기록한다.

```json
{
  "request_id": "32자리 서버 생성 ID",
  "endpoint": "/api/v1/ai/analyze",
  "model_name": "claude-sonnet-4-6",
  "prompt_version": "sha256:프롬프트 소스 64자리 해시",
  "latency_ms": 12.3,
  "success": false,
  "error_code": "LLM_INVALID_JSON"
}
```

- 요청 ID는 서버가 새로 생성하며 헤더의 임의 ID를 로그에 복사하지 않는다. 응답 `X-Request-ID`와 오류 응답 `requestId`가 같은 값이다.
- 엔드포인트는 알려진 경로만 기록하며 임의 경로·query string은 기록하지 않는다. 미등록 경로는 `unmatched`다.
- 모델명은 제한된 식별자 목록만 허용하고 그 외 값은 `unknown`이다. 새 모델 도입 시 목록을 검토해야 한다. SDK 요청 전 실패해 모델을 사용하지 않은 경우도 `unknown`이다.
- 프롬프트 버전은 템플릿 및 서비스 내 인라인 프롬프트 소스의 해시다. 사용자 프롬프트나 임의 환경변수 값을 로그로 출력하지 않는다.
- 마지막 모델 호출의 식별자를 기록한다. 초안 생성처럼 여러 모델을 거치는 경우 전체 호출 목록이나 토큰별 추적 로그가 아니다.
- 원문·프롬프트·근거·이력·모델 응답·API Key·자유 형식 예외 문장은 기록하지 않는다. JSON 파싱 실패 시 응답을 print하던 코드를 제거했다.
- SDK/HTTP 클라이언트 및 Uvicorn access/error 로그를 억제한다. 기존에 handler가 있는 하위 SDK logger도 정리한다. 운영 로그 handler는 메시지·traceback·임의 extra를 직렬화하지 않는다. 새 로깅 핸들러나 SDK를 추가할 때 같은 허용 목록을 유지해야 한다.

JSON 엔드포인트의 응답을 미들웨어에서 버퍼링하므로, Pydantic request/response 오류와 예상 밖 예외도 원본 오류 본문을 내보내지 않는다. 이 버퍼링은 현재의 유한 JSON 응답을 전제로 하며 향후 SSE/대용량 스트리밍을 추가할 때 별도 경계 설계가 필요하다.

실패 응답은 다음 형식만 사용한다.

```json
{"error": {"code": "LLM_INVALID_SCHEMA"}, "requestId": "서버 생성 ID"}
```

주요 상태: 잘못된 요청 422, 모델 JSON/스키마/근거/provider 실패 502, LLM timeout 504, 검색 실패 503, 예상 밖 내부 오류 500. `/api/v1/rag/search`는 검색 결과의 응답 구조 검증까지 검색 실패 경계 안에서 처리하므로, 잘못된 결과 형식도 `RAG_UNAVAILABLE`과 503으로 반환한다. 클라이언트는 예전 Pydantic `detail`·자유 형식 에러 문장 대신 이 코드와 ID를 사용하도록 확인해야 한다.

테스트는 성공·timeout·JSON·스키마·근거·검색·provider·request/response 검증 실패에 비밀 표식을 주입해 운영 로그·stdout·stderr·실패 본문에서 미노출을 검사한다. 실패 응답에 원문을 포함하는 FastAPI 기본 422도 교체한다. 병렬 요청 8건의 ID 분리와 JSON formatter의 임의 메시지·traceback 무시도 검증한다. 성공 응답의 업무상 요약/근거는 기존 API 계약대로 반환하며, 운영 로그에 복사하지 않는다.

### 저장 로그의 허용 목록 검사

성공·timeout·provider 실패 형식의 **합성 샘플**은
`tests/fixtures/operational_log_samples.jsonl`에 있다. 샘플 ID·0으로 채운 해시는 실제 운영 값이 아니다.
운영 환경에서 수집한 stderr JSONL도 같은 검증기로 검사할 수 있다.

```bash
python scripts/validate_operational_logs.py --input tests/fixtures/operational_log_samples.jsonl
python scripts/validate_operational_logs.py --input /path/to/operations.jsonl
# 회귀 실행과 함께 확인
python scripts/run_regression.py --log-file /path/to/operations.jsonl
```

정확히 7개 필드, 허용된 엔드포인트·모델·오류 코드, ID·프롬프트 해시 형식, 유한한 비음수 응답 시간,
성공/오류 코드의 일관성을 검사한다. 원문 필드 추가, URL query, 자유 형식 오류, 중복 JSON 키,
깨진 JSON, 64 KiB를 넘는 줄을 거부한다. 빈 파일도 검사 통과로 표시하지 않는다. 결과에는
집계와 오류 줄 번호·허용된 사유만 담으며 원본 줄은 출력·복사하지 않는다. 오류 목록은 최대 100개다.
이는 로그 스키마 검사이며 모든 종류의 개인정보를 탐지하는 별도 DLP 도구는 아니다.
로그 해시는 검증기가 EOF까지 실제 읽은 바이트만 대상으로 계산한다. `checked_bytes`와
`checked_sha256`를 결과에 기록하며, 이후 운영 로그에 추가된 줄은 이번 검증 범위에 포함하지 않는다.

## CI와 평가 산출물 분리

`.github/workflows/offline-regression.yml`은 PR 및 수동 실행용이다. 테스트 의존성과 선택적 그래프 의존성을 설치하고 `python -m pytest --aggregate-report reports/ci/aggregate.json`을 실행한다. 합성 데이터의 PNG 생성까지 검증한다. 코드 읽기 권한만 사용하며 모델 비밀키를 전달하지 않는다. 유료 모델·RAG 호출 단계가 없다.

추가 CI 단계는 `python scripts/run_regression.py --log-file tests/fixtures/operational_log_samples.jsonl`로
실제 단일 명령의 연결과 합성 로그 샘플을 검증한다. 실제 응답 회귀나 운영 서버 로그 검증을
CI에서 완료했다고 표시하지 않는다.

기본 보관 artifact는 `reports/ci/aggregate.json` **한 파일**이며 통과/실패/skip/xfail 수, 핵심 20건 집계, 종료 코드와 실행 시간만 포함한다. 입력·응답·로그·case ID·예외 전문은 포함하지 않는다. #26의 `results.csv`, `predictions.jsonl`, 원문이 있는 보고서나 pytest traceback/JUnit 전체를 artifact로 업로드하지 않는다. 집계 파일에 xfail 수가 남으므로 미완료 사항을 성공 수로 합치지 않는다. 원격 workflow의 실행 여부와 결과는 해당 PR의 Checks에서 확인한다.

기존 #26 평가 보고서는 `reports/<평가실행>/`, CI 집계는 `reports/ci/`, 운영 이벤트는 stderr의 전용 logger로 분리한다. 실제 모델 성능 측정은 별도 승인 하에 #26 명령으로 실행하고, 그 결과를 CI의 오프라인 통과 수와 혼합하지 않는다.

## 사람이 검토할 항목

1. AI_PROPOSED 개발 라벨 기반 20건 / 33개 기대 조건, 특히 경계·공개 압박·학생 안전 제보의 해석
2. 위 3개 strict xfail과 나머지 #28 생성 가드레일 계약
3. 502/503/504 오류 코드 형식에 대한 백엔드 소비자 호환성
4. Claude 30초 timeout과 출력 1회 재시도 예산의 운영 적합성, 새 모델명 허용 목록
5. 실제 모델·검색 품질 평가와 원격 GitHub Actions 실행 결과는 별도 확인
