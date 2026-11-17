# #26 태깅 평가 파이프라인 / #25 공통 계약

기존 진입점은 `scripts/evaluate_risk_prompt_updated.py`다. `scripts/evaluation/`에 데이터 어댑터·계약·지표·실행·저장을 분리했다. Python 표준 라이브러리만으로 검증·저장 예측 평가·테스트가 가능하며, 평가기 import는 FastAPI·검색기·모델 SDK를 로딩하지 않는다.

이 문서의 HTTP 예시는 AI 서버 직접 호출 기준이다. EC2 접속 없이 공개 Backend의
초안·분석 API로 실행하려면 [공개 Backend 평가 가이드](backend_evaluation.md)를 따른다.
해당 가이드에 실제 200건 태깅 결과와 독립 LLM-only·최종 위험도 평가의 제한을 기록했다.

## 실행

저장소 루트에서 실행한다. 다음 명령은 외부 호출을 하지 않는다.

```bash
python3 -m unittest discover -s tests -p 'test_tagging_evaluation.py' -v
python3 -m unittest discover -s tests -p 'test_evaluation_transport.py' -v
python3 scripts/evaluate_risk_prompt_updated.py --validate-only
python3 scripts/evaluate_risk_prompt_updated.py --dataset goldenset --validate-only
python3 scripts/validate_dev_dataset.py
python3 scripts/validate_dev_dataset.py --dataset goldenset

python3 scripts/evaluate_risk_prompt_updated.py \
  --case-id DEV003 \
  --predictions tests/fixtures/tagging_predictions_dev003.json \
  --report-dir reports/offline_demo --run-version demo-before
```

fixture는 코드 동작 확인용 모의 예측이다. 모델 성능·실제 생성 설정·가드레일 통과를 나타내지 않는다. 실제 모델 응답은 생성하지 않았다. 새 골든 정답이나 안전 신호 정답도 생성하지 않았다.

실행 결과의 `결과 저장:`에 출력된 **실행 하위 디렉터리**를 이전 실행으로 지정한다.

```bash
python3 scripts/evaluate_risk_prompt_updated.py \
  --case-id DEV003 \
  --predictions tests/fixtures/tagging_predictions_dev003.json \
  --report-dir reports/offline_demo --run-version demo-after \
  --previous reports/offline_demo/<이전-실행-ID>
```

`--predictions`가 있으면 HTTP 경로를 실행하지 않는다. 입력 파일이 없거나 일부 사례의 예측이 빠져도 HTTP로 보충하지 않는다. 일부 예측 누락은 해당 사례 실패로 저장한다. `--validate-only`는 평가·보고서 작성 없이 두 데이터셋 전체를 검증한다.

기존 옵션 `--data-dir`, `--report-dir`, `--base-url`, `--limit`, 반복 가능한 `--case-id`, `--sleep`, `--timeout`, `--stop-on-error`를 유지한다. 기존처럼 `--predictions`와 `--validate-only` 없이 실행하면 실제 AI 서버를 호출하므로 이 개발 작업에서는 실행하지 않았다.

실제 서버 연동 시 사용할 명령 형식:

```bash
python3 scripts/evaluate_risk_prompt_updated.py --dataset goldenset \
  --base-url http://localhost:8000 --run-version candidate-v1 \
  --prompt-version <프롬프트-버전> --rule-version none \
  --dataset-version <데이터-버전> --rag-version <인덱스-버전>
```

종료 코드: 0은 요청·계약·저장 성공(오답 0건이라는 뜻은 아님), 1은 사례 실패 또는 이전 실행 비교 실패, 2는 실행 설정·데이터 검증 오류다. `--stop-on-error`에서도 처리된 사례의 결과를 저장하고 요청 수·미시도 수를 분리한다.

## 데이터 계약과 블라인드 경계

기존 경로와 파일명은 그대로 사용한다.

| 프로필 | 사례 파일 | 라벨 파일 |
| --- | --- | --- |
| dev | `data/dev/teachercare_dev_cases_100.csv` | `data/dev/teachercare_dev_risk_labels_100.csv` |
| goldenset | `data/goldenset/TeacherCare_goldenset_200cases.csv` | `data/goldenset/TeacherCare_goldenset_200risktages.csv` |

dev의 `risk_factor/status/evidence_span`과 goldenset의 `riskTagCode/state/evidence`를 공통 라벨로 변환한다. 태그 매핑은 `evaluation/data.py` 한 곳에서 관리한다. 사례 ID·라벨 조합 중복, 빈 ID·문장, 8종 누락·추가, 고아 라벨, 잘못된 상태, CSV 열 개수·중복 헤더를 거부한다. 골든 라벨의 정답은 현재 `state`이며 사례 CSV의 8개 상태 컬럼과 일치해야 한다. 과거 판정을 정답에 혼합하지 않는다.

부분 선택 전에 두 데이터셋 전체를 검증하고 서로의 ID 및 **NFKC + 모든 Unicode 공백 제거** 문장 중복을 검사한다. 중복은 실행 전 오류다. 정규화는 중복 검사에만 사용하고 모델 입력을 바꾸지 않는다. 반대 데이터셋을 찾지 못해도 검사를 생략하지 않는다. 사용자 데이터에는 `--overlap-data-dir`로 반대 프로필을 지정할 수 있다. 의미상 유사성·기존 학습/프롬프트 노출까지 검사하는 것은 아니다.

모델 요청은 `contracts.build_payload()`가 아래 두 키만 조립한다.

```json
{"complaint": "사례의 message_text", "ruleResults": []}
```

골든 정답, reason, evidence, 과거 판정, AI_proposed, 검토 상태, 사례의 태그 컬럼을 요청에 복사하지 않는다. `history_context`, `regulation_context`도 현재 API 계약에는 전달하지 않는다. 평가 입력 범위는 `complaint_only`다. 이력·규정으로 판정된 정답의 성능은 이 입력 제한과 함께 해석해야 한다.

## #25 협업 인터페이스

`--mode llm`은 `ruleResults=[]`다. `--mode rule_llm --rule-results captured_rules.json`은 백엔드에서 **별도로 확보한** 다음 파일을 받는다.

```json
{
  "DEV003": [{"code": "THREAT", "state": "BOUNDARY", "evidenceSpans": []}]
}
```

모든 선택 사례의 키가 필요하다. 검출 결과가 없으면 명시적으로 빈 배열을 저장한다. 규칙은 희소 배열을 허용하지만 중복 코드·허용되지 않은 코드/상태는 거부한다. `BOUNDARY/UNKNOWN`을 변환하지 않는다. CSV 정답이나 개발용 Rule 후보를 입력 규칙으로 자동 전환하지 않으며 백엔드 규칙을 재구현하지 않는다.

공통 실행 결과 형식은 JSON 배열 또는 JSONL의 다음 레코드다.

```json
{
  "case_id": "DEV003",
  "mode": "llm",
  "attempt": 1,
  "input_sha256": "complaint+ruleResults 정규 JSON의 SHA-256",
  "complaint_sha256": "complaint JSON 문자열의 SHA-256",
  "rag_snapshot_id": "선택적 스냅샷 식별자",
  "request_success": 1,
  "error_code": "",
  "latency_ms": 1234.0,
  "response": {"tags": [], "metadata": {}}
}
```

위 예시의 `tags`는 구조 설명용 자리표시자다. 실제 성공 응답에는 8종 태그가 정확히 한 번씩 있어야 한다. 원본 API 응답을 보존하므로 severity·repeatCount·safetyFlags도 있으면 저장한다. 해당 항목의 정답이나 성능 지표는 생성하지 않는다.

외부 생산자는 최소 `case_id/response`를 제공할 수 있다. mode·입력 해시가 있으면 일치 여부를 검사하며, 없는 기존 예측은 `source_provenance_verified=false`다. 직접 캡처한 요청은 `input_hash_origin=captured_request`, 재평가를 위해 현재 입력에서 만든 해시는 `reconstructed_for_replay`로 구분한다. 미확인 예측에 해시를 추가해 다시 저장해도 `source_provenance_verified=false`가 유지된다. 해시가 있다는 것은 입력 파일과 일치한다는 의미이며 외부 생산자가 정답을 보지 않았다는 보증은 아니다.

평가기가 저장한 JSONL은 재평가 입력으로 사용할 수 있다. 저장된 실패(`request_success=0`)는 응답이 파싱 가능해도 실패로 유지하며, 허용된 `error_code`와 원본 JSON 응답을 보존한다. 임의 예외 문장이 든 오류 코드는 `request:recorded_request_failure`로 대체한다. JSON으로 저장할 수 없는 실패 응답은 `response=null`과 `recorded_response_sanitized=true`로 표시하고, 잘못된 시간·스냅샷 값도 정리한다. 이 처리는 실패를 정상 예측이나 ABSENT로 보정하지 않는다.

`latency_ms`는 현재 **RAG 포함 전체 요청 시간**이다. 저장 예측 재평가에서는 원래 기록된 시간을 사용하며 재평가 처리 시간을 모델 응답 시간으로 기록하지 않는다. LLM 전용 시간·토큰·비용으로 해석하지 않는다. 평가기 자체 재시도는 없고 `attempt=1`이다. SDK·서버 내부 재시도는 이 값으로 계산할 수 없다.

모드 옵션만으로 통제된 A/B가 완성되지는 않는다. 현 API는 검색 결과를 입력으로 받지 않고 매번 검색한다. 채연님 구현에서 동일 문서·순서·검색 설정·생성 설정을 고정할 내부 연결 지점과 스냅샷 계약이 필요하다. 현재 `rag_snapshot_id`와 서버의 검색 문서 해시는 이를 식별할 준비이며, 검색 결과 주입·캐시 기능은 구현하지 않았다. 일반 실행 비교는 `controlled_ab=false`로 표시한다.

## 지표 정의

- 모든 응답은 8종 태그·허용 상태를 검증한다. 누락·중복을 ABSENT로 보정하지 않고 해당 사례 전체를 계약 실패로 저장한다.
- 이력 없는 llm/rule_llm 공통 비교는 **REPEAT 제외 7종**이다. REPEAT의 예측은 결과에 보존하며 `history_not_supplied`를 기록한다.
- 기본은 두 정책 모두 계산한다. `--positive-policy present`는 PRESENT만, `present_boundary`는 PRESENT와 BOUNDARY를 양성으로 본다. `both`가 기본값이다.
- 정답 UNKNOWN은 이진 P/R/F1에서만 제외한다. 예측 UNKNOWN은 확정 정답에 대해 비양성으로 계산한다. 정책별 `evaluated_labels`, `excluded_gold_unknown`, 양성 지원 수, TP/FP/FN/TN을 기록한다.
- 평가 가능한 이진 표본이 있는 태그는 0분모 P/R/F1을 0으로 처리한다. 표본 자체가 0이면 null이다. Macro는 평가 가능한 태그의 반올림 전 지표 평균, Micro는 TP/FP/FN 합계로 계산한다. Macro의 태그 분모도 기록한다.
- 4상태 행렬은 행=정답, 열=예측이며 UNKNOWN·BOUNDARY를 유지한다. 태그별 및 전체 행렬을 저장한다.
- `tag_exact_match`는 상태가 일치한 라벨/성공한 7종 라벨이다. `all_tags_exact_match`는 7종 모두 일치한 사례/성공한 완전 사례다. 전체 요청 사례를 분모로 한 비율도 별도 기록한다.
- 요청·계약 실패는 행렬과 품질 지표에서 제외하지만 실패 사례·실패 라벨·미시도 수를 따로 저장한다. 따라서 품질 지표만 보지 말고 coverage를 함께 확인해야 한다.
- 골든 교사 검토분·미확정분을 구분한다. 개발셋 `review_required=NO`는 `dev_stable_ai`이며 교사 확정분으로 취급하지 않는다. 부분 검토 그룹에서 사례 전체 일치율은 평가 대상 7종이 모두 그 그룹에 있는 완전 사례만 분모에 넣는다.

근거 일치율은 정답 PRESENT/BOUNDARY이며 정답 근거가 실제 전달 원문에 존재하는 라벨만 분모로 삼는다. 기존 공백 제거 후 양방향 부분문자열 기준을 사용하되 **원문에 실제 존재하는 예측 근거만** 일치로 인정한다. 비어 있거나 이력·규정 설명인 정답 근거는 제외 사유와 수를 기록한다. 별도로 예측 span 각각의 원문 내 존재 수/전체 span 수와 원문에 없는 span 수를 기록한다. 이 검사는 평가 지표이며 #28처럼 모델 상태를 하향하거나 응답을 수정하지 않는다.

## 산출물과 provenance

`--report-dir/<UTC날짜시각>_<run-version>_<고유ID>/`에 매번 새로 저장한다.

- `results.csv`, `cases.csv`, `mismatches.csv`, `failures.csv`, `evidence_mismatches.csv`
- `metrics.json`: 지표, 분모, 제외 이유, coverage, 검토 그룹
- `manifest.json`: 버전, 해시, 실행 범위, 미평가 항목, 각 산출물 해시
- `predictions.jsonl`: 사례별 원본 응답과 입력 해시, 실패 정보
- 기존 `summary.json`, `tag_metrics.csv`, `tag_metrics_core.csv`, `core_mismatches.csv`, `review_mismatches.csv`
- `--previous` 사용 시 `diff.json`, `newly_wrong.csv`

기존 고정 파일명은 report-dir 바로 아래에도 최신 스냅샷으로 유지한다. `latest.json`은 불변 실행 디렉터리를 가리킨다. 이전 결과 비교에는 고정 스냅샷 대신 실행 하위 디렉터리를 사용한다. 기존 `summary.json`의 `silver` 키는 호환성용 이름이며 골든셋 전체를 교사 확정 정답으로 선언하는 필드가 아니다.

비교는 데이터 파일 해시와 평가 정책이 같아야 하며, 기존 results.csv의 manifest 해시를 검증한다. 양쪽 모두 성공한 동일 사례에서 지표를 다시 계산해 변화·새 오답·교정 사례를 산출한다. 새 요청 실패·회복은 별도로 기록한다. 비교 불가능해도 현재 실행의 결과를 보존하고 종료 코드 1 및 비교 실패 사유를 저장한다.

manifest는 다음을 구분한다.

- 평가기 Git SHA + dirty 여부 + 평가 모듈·진입점 파일 해시
- 데이터 파일별/통합 해시와 데이터 버전, 규칙 입력 파일 해시 또는 빈 규칙 해시
- 로컬 프롬프트·검색기 파일 해시 및 호출자가 선언한 버전
- 서버 응답의 모델명·실제 명시된 SDK 생성 설정·실행 provenance
- 코드북 선언 버전과 선택적 `--codebook-file` 해시

기존 서버의 `metadata.temperature=0`은 실제 호출 설정 증거로 사용하지 않는다. 이번 변경은 위험 태깅 클라이언트에만 temperature=0을 명시하고 `generationSettings`에 실제 SDK 인자를 반환한다. 문맥 분석·수정 클라이언트는 기존처럼 temperature를 생략한다. **위험 태깅은 이전의 provider 기본값에서 명시적 0으로 바뀌므로**, 기존 결과와 통제 비교하려면 이 차이를 반영해야 한다. 생략한 생성 옵션은 provider 기본값이며 추정하지 않는다.

`metadata.evaluationProvenance`에는 실행 서버의 소스 파일 해시, 실제 검색 문서 해시, 검색 설정이 포함된다. 원문이나 검색 문서 자체는 이 메타데이터에 넣지 않는다. 프롬프트 버전은 실제 로드된 `RISK_PROMPT_VERSION` 상수에서 기록하며 `PROMPT_VERSION` 환경변수로 대체하지 않는다. 배포 환경에서 `GIT_SHA`, `RULE_VERSION`, `RAG_VERSION`, `RAG_INDEX_SHA256`을 제공하면 함께 기록한다. 로컬 파일 해시를 원격 배포·RAG 인덱스 해시로 가장하지 않는다. 구버전 서버·오프라인 예측에 없는 실제 설정/배포 정보는 null·빈 목록·미확인 건수로 남긴다. 모델 SDK의 추가 네트워크 호출은 이 메타데이터 생성에 없다.

## 리뷰 보완 사항

생성 옵션에서 temperature를 생략한 클라이언트의 `metadata.temperature`는 추정값 대신 null을 기록한다. 명시한 경우에는 실제 `generationSettings.temperature`와 같은 값을 반환한다. 백엔드의 `Double temperature` 계약도 null을 허용한다.

이전 manifest의 최상위·중첩 구조와 해시를 검증하고, 비교가 불가능해도 현재 결과를 저장한다. 규칙 파일은 최초 읽은 바이트로 파싱과 해시를 함께 계산한다. 공유 최신 스냅샷 게시에는 프로세스 간 파일 잠금을 사용한다. 이 잠금은 macOS/Linux용이며, 여러 파일을 읽는 소비자는 잠금에 참여하거나 `latest.json`이 가리키는 불변 실행 폴더를 사용한다.

## 남은 계약 / 이번 범위 밖

- 최종 위험도: 실제 Backend Risk Engine 출력과 확정 정답의 평가·저장·비교를 지원한다. 추가 입력과 엔진 버전·입력 해시 계약은 [위험도·세부 유형 가이드](supplemental_evaluation.md)를 따른다. 원본 골든셋에 위험도 정답이 없어 사람 검토가 필요하며, urgentHumanReview·THREAT 태그를 정답으로 변환하지 않는다.
- context_subtype: 별도 CONFIRMED 정답에 기반한 유형별 태그 상태 지표를 지원한다. 유형 어휘는 사람 검토 시 합의해야 한다. 원본에 없는 subtype을 추정하지 않으며, 미확정 집단 지표는 null로 남긴다.
- REPEAT: 구조화된 이력 전달 계약과 동일 정보 조건의 정답 평가가 필요하다.
- severity·repeatCount·safetyFlags: 예측을 보존하되 추가 정답 없이는 평가하지 않는다.
- #25: 백엔드 규칙 확보 및 동결된 RAG 스냅샷 재사용, 반복 실행·비용 분석은 채연님 실험 구현에 연결한다.
- #33의 오프라인 20건 부분 조건 테스트와 운영 로그는 [회귀·로그 문서](regression_and_logging.md)에 설명한다. 실제 모델 20건의 품질 검증은 수행하지 않았다. #28의 BOUNDARY 하향·REPEAT 강제 보정·생성 검증 등은 해당 문서의 미완료 계약을 따른다.
- `--charts`로 태그별 F1·태그 혼동행렬과 정답/백엔드 결과가 있는 위험도·세부 유형 PNG를 저장한다. 렌더러 오류에도 평가 결과를 보존한다.

테스트는 모의 전송·저장 예측을 사용한다. FastAPI 라우팅·서비스·실패 응답은 #33의 오프라인 TestClient로 검증한다. 실제 provider SDK 통신, 배포 서버 E2E, 유료 호출의 품질·성능 검증은 별도 실행이 필요하다. 원격 CI 결과는 PR의 Checks에서 확인한다.
