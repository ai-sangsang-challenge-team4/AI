# #26 위험도·세부 유형 평가와 그래프

기존 골든셋 CSV 두 파일은 수정하지 않는다. 현재 정답은 8종 태그의 상태이며, 최종 위험도와 context_subtype 정답은 별도 사람 검토 양식으로 받는다. AI나 점수표로 정답을 만들지 않는다.

## 1. 정답 양식 준비

```bash
python scripts/evaluate_risk_prompt_updated.py --dataset goldenset \
  --write-target-template data/private/goldenset_evaluation_targets.csv
```

HTTP 호출 없이 전체 200건의 양식을 만든다. 기존 파일은 덮어쓰지 않는다. `data/private/`는 Git 추적에서 제외된다.

| 열 | 의미 |
| --- | --- |
| case_id | 기존 사례 ID |
| dataset_sha256 | 두 원본 CSV의 통합 해시. 데이터 변경 시 재검토 필요 |
| review_status | `PENDING` 또는 사람이 검토한 `CONFIRMED` |
| risk_level | 사람이 확정한 `LOW/MEDIUM/HIGH/EMERGENCY`, 미확정은 빈칸 |
| is_legitimate | 정당한 민원 여부 `TRUE/FALSE`, 미확정은 빈칸 |
| privacy_context_subtypes | 아래 PRIVACY 유형, 복수이면 `;`로 구분 |
| threat_context_subtypes | 아래 THREAT 유형, 복수이면 `;`로 구분 |

양식의 모든 정답은 빈칸, 검토 상태는 PENDING이다. PENDING 행에 임시 값이 있어도 지표에는 사용하지 않는다. CONFIRMED에서도 빈 정답은 미확정으로 남긴다.

현재 평가용 유형 어휘는 다음과 같다. 사람 검토 시 이 정의를 먼저 합의해야 하며, 기존 코드북에 이미 확정된 유형이 있다고 가정하지 않는다.

- PRIVACY: `PII_INCLUDED`(개인정보 포함 문맥), `MISUSE_OR_THIRD_PARTY_REQUEST`(악용·제3자 정보 요구), `OTHER`(그 밖의 검토된 문맥)
- THREAT: `COERCIVE_PRESSURE`(강요·압박), `PHYSICAL_HARM`(신체 위해), `OTHER`

이 지표는 **정답 유형별로 나눈 태그 상태 P/R/F1**이다. 모델이 subtype 자체를 예측하는 정확도가 아니다. 복수 유형 사례는 여러 집단에 포함되므로 집단별 분모를 합산하지 않는다. 요청 실패와 미시도도 집단별 coverage에 남긴다. 전체 태깅 평가는 기존처럼 REPEAT 제외 7종이다.

## 2. 태깅 실행과 백엔드 입력 전달

```bash
python -m pip install -r requirements-evaluation.txt
python scripts/evaluate_risk_prompt_updated.py --dataset goldenset \
  --base-url http://localhost:8000 --run-version g200-before --charts
```

이 명령은 실제 AI 서버를 호출한다. Backend 저장소 문서의 localhost는 **EC2 내부** 주소다. Mac에서 같은 주소를 사용하면 Mac의 서버를 찾는다. EC2에서 실행하거나 SSH 포워딩이 필요하다. 공개 백엔드 주소 `https://teacherhub.duckdns.org`를 AI 주소로 대체하지 않는다.

실행 폴더의 `backend_inputs.jsonl`은 성공 사례의 `case_id`, `mode`, `dataset_sha256`, `risk_input`, `risk_input_sha256`을 제공한다. `risk_input`은 실제 AI 응답의 tags·safetyFlags와 요청의 ruleResults만 포함한다. 위험도·유형 정답은 서버 요청이나 이 입력에 포함하지 않는다.

Backend Risk Engine 담당자는 이 입력을 **실제 백엔드의 검증·결합·점수·안전 신호 정책**으로 계산하고 다음 구조로 내보낸다. Python에서 점수표나 임계값을 복제하지 않는다.

```json
{
  "schema_version": 1,
  "dataset_sha256": "해당 실행 manifest의 dataset.sha256",
  "mode": "llm",
  "risk_engine": {
    "version": "실제 백엔드 정책 버전",
    "source_commit": "백엔드 소스의 40자리 Git SHA"
  },
  "predictions": [
    {"case_id": "G001", "risk_level": "LOW", "risk_input_sha256": "전달받은 해당 입력의 64자리 SHA-256"}
  ]
}
```

예시는 구조 설명이며 정답이나 실제 실행 결과가 아니다. 입력 해시는 전달한 입력의 정규 JSON(UTF-8, 키 정렬, 공백 없는 구분자, ensure_ascii=false)의 SHA-256이다. `backend_inputs.jsonl`에 이미 계산된 값을 유지한다. 데이터 해시·모드·사례 ID·입력 해시가 다르면 지표에 섞지 않는다. 엔진 버전은 외부 생산자의 선언이며 평가기가 백엔드 실행 자체를 인증하는 것은 아니다.

## 3. 저장 예측으로 최종 평가

백엔드 출력은 예시에 나온 필드만 허용한다. 엔진 version은 영문·숫자로 시작하는 128자 이내 식별자이며 나머지는 영문·숫자와 `._:+-`만 허용한다. 임의 디버그 메타데이터·인증 정보·추가 필드는 받지 않고, NaN·Infinity·지수 오버플로 등은 모델 요청 전에 거부한다.

```bash
python scripts/evaluate_risk_prompt_updated.py --dataset goldenset \
  --predictions reports/<태깅-실행>/predictions.jsonl \
  --targets data/private/goldenset_evaluation_targets.csv \
  --risk-predictions data/private/backend_risk_predictions.json \
  --run-version g200-risk-v1 --charts
```

재평가는 모델을 호출하지 않는다. `--targets`만 사용하면 확정된 세부 유형 지표를 계산한다. 위험도 정답이 있는데 백엔드 결과가 없으면 해당 사례를 `missing_backend_prediction`으로 기록하고 종료 코드 1을 반환한다. 정답·예측·모델 요청 실패를 ABSENT나 LOW로 보정하지 않는다.

추가 산출물:

- `risk_results.csv`: 확정 위험도 사례의 정답·예측·성공/실패
- `risk_mismatches.csv`, `emergency_misses.csv`
- `metrics.json.final_risk`: 4×4 혼동행렬, HIGH/EMERGENCY 각각의 재현율, 두 단계 통합 재현율, Emergency 미탐 ID, 정당한 민원 과대평가율
- `metrics.json.context_subtypes`: 유형별 태그 상태 지표와 분모
- `backend_inputs.jsonl`: 정답 없는 실제 백엔드 계산 입력
- `manifest.json`: 정답 파일·백엔드 출력 파일의 최초 읽기 해시와 엔진 선언 버전

정당한 민원의 과대평가는 `is_legitimate=TRUE`이고 **예측 단계가 확정 정답 단계보다 높은** 사례/비교 가능한 해당 민원 수다. 정답이 없거나 분모가 0이면 지표는 null이다. 실패는 품질 지표에서 제외하지만 실패 수와 원인을 별도 집계한다.

`--previous reports/<이전-최종평가-실행>`으로 비교한다. 원본 데이터·정답 양식 해시·평가 정책이 같아야 한다. 양쪽 모두 성공한 사례에서 위험도·유형 지표 변화와 새 오답을 비교하고, 새 실패/회복은 분리한다. 이전 위험도 결과 파일도 manifest 해시를 검증한다.

## 4. 그래프와 검증 범위

중단이 기록 쓰기 도중 발생해 마지막 JSONL이 잘렸다면 먼저 다음 복구 도구를 사용한다. 마지막의 줄바꿈 없는 불완전 기록만 제외하고 제외 여부를 보고한다. 중간 기록의 손상·중복 ID·비유한 숫자는 오류로 처리하며 원본과 기존 출력 파일을 덮어쓰지 않는다. 일반 `--predictions` 파서는 계속 엄격하게 동작한다.

```bash
python scripts/recover_evaluation_checkpoint.py \
  --input data/private/live_checkpoint.jsonl \
  --output data/private/recovered_predictions.jsonl
```

장시간 실제 실행에는 `--checkpoint-file data/private/live_checkpoint.jsonl`을 함께 지정할 수 있다. 완료된 사례마다 JSONL을 flush·fsync하며 기존 파일은 덮어쓰지 않는다. 이후 요청이나 프로세스가 중단되어도 완료 기록을 보존한다. 이 옵션은 실제 HTTP 실행에서만 지원한다. 복구할 때는 체크포인트의 사례 ID를 `--case-id`로 지정하거나 완료된 앞부분 건수를 `--limit`로 지정해 `--predictions` 입력으로 재평가한다. 이 복구는 추가 모델 호출을 하지 않으며, 미완료 200건을 완료로 표시하지 않는다.

`--charts`는 다음 PNG를 실행 폴더에 저장하고 manifest에 해시를 기록한다.

- `tag_f1.png`: 두 BOUNDARY 정책의 태그별 F1
- `tag_state_confusion.png`: 태그 4상태 혼동행렬
- `risk_confusion.png`: 비교 가능한 확정 위험도 사례가 있을 때만 생성
- `context_subtype_f1.png`: 확정 유형 정답이 있을 때만 생성

그래프는 집계값만 담고 원문·근거·사례 ID를 넣지 않는다. 렌더러 오류가 발생해도 완료된 평가 결과를 저장하며, manifest에 제한된 실패 코드와 종료 코드 1을 남긴다. matplotlib이 없으면 모델 호출 전에 설치 안내와 함께 중단한다. CI도 그래프 의존성을 설치해 합성 사례의 PNG 생성까지 검증한다.

오프라인 테스트·예제 그래프는 평가 코드 검증이다. **실제 200건 모델 성능이나 사람이 확정한 위험도·유형 정답을 대신하지 않는다.** 공개 Backend를 통한 실제 200건 태깅 실행 결과는 [공개 Backend 평가 가이드](backend_evaluation.md)에 기록했다. 현재 원본 골든셋에는 최종 위험도·세부 유형 정답이 없어 해당 지표는 미평가이며, 사람이 채운 확정 정답으로 별도 재평가해야 한다.
