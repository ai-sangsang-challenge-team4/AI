# #26 공개 Backend를 통한 골든셋 평가

EC2 접속 없이 `POST /auth/login` → 평가용 민원 초안 생성 → 위험 분석 → detector-results 조회를 수행한다.
기존 AI 직접 평가기는 그대로 유지하며 `scripts/evaluate_backend_goldenset.py`가 실제 백엔드 결과를
수집해 기존 지표·보고서 코드에 연결한다. 위험 점수 로직은 Python에서 복제하지 않는다.

## 실행

개발셋 기반 개선에는 `--dataset dev`를 사용한다. 골든셋이 기본값이며, 기존 골든셋 명령과
체크포인트는 그대로 재사용한다. 개발셋 실행·설정 동결·골든셋 최종 확인 순서는
[개발셋 개선 가이드](dev_risk_calibration.md)를 따른다.

저장소 루트, Python 3.11 이상에서 실행한다. 테스트용 PARENT 계정과 연결된 학생·교사가 필요하다.
200건 실행은 DB에 독립된 민원 초안을 생성하고 실제 AI 호출 비용이 발생한다. 제출·전송 API는 호출하지 않는다.
동시 실행은 기본 1개, 최대 2개다. 분석 성공 후 서버의 비동기 수정안 생성도 실행될 수 있다.
종료 코드 0은 선택 사례 모두의 AI 수집과 보고서 생성이 성공한 경우다. 미시도·Rule-only
폴백·비교 또는 그래프 생성 실패가 남으면 1을 반환하며, 입력·인증·체크포인트 오류는 2다.
종료 코드 2에서는 안전한 고정 안내문과 `backend:http_401` 같은 제한된 오류 코드를 출력한다.
일반 검증 오류·파일 오류·누락 키는 원문이나 경로가 포함될 수 있어 공통 안내만 출력한다.

```bash
python3.11 -m venv /tmp/teachercare-eval-env
/tmp/teachercare-eval-env/bin/python -m pip install -r requirements-evaluation.txt

# 이메일과 비밀번호는 대화형 입력. 비밀번호는 화면에 출력하지 않는다.
/tmp/teachercare-eval-env/bin/python scripts/evaluate_backend_goldenset.py \
  --capture-dir data/private/backend-g200-baseline \
  --report-dir reports/backend-g200 \
  --run-version backend-g200-baseline --workers 2 --charts \
  --gold-standard-status team_approved
```

위 예시는 팀이 원본 CSV 두 파일을 최종 태깅 정답으로 승인한 데이터셋을 사용한다.
최종 위험도·세부 유형까지 평가하려면 [정답 양식 준비](supplemental_evaluation.md#1-정답-양식-준비)를
따라 사람이 확정한 파일을 만든 뒤 `--targets data/private/goldenset_evaluation_targets.csv`를 추가한다.
이 파일은 비공개이며 저장소를 새로 clone한 환경에는 없다. 태깅만 평가할 때는 필요하지 않다.

자동화에서는 `TEACHERHUB_EMAIL`, `TEACHERHUB_PASSWORD` 환경변수 또는 `--credentials-file`로
권한 600의 외부 JSON(`email`, `password`)을 제공할 수 있다. 인증 응답·토큰·비밀번호는
체크포인트·로그·보고서에 넣지 않는다. 원격 HTTP와 리다이렉트는 인증 정보 보호를 위해 거부한다.
학생이 여러 명이면 `--student-id`, 유일한 담임이 없으면 `--teacher-id`를 명시한다.

기존 검증 1건은 `--seed-smoke reports/backend_smoke_G001/smoke_result.json`으로 재사용할 수 있다.
같은 데이터셋·서버인지 확인하고, 현재 계정이 소유한 동일 본문의 DRAFT인지 GET으로 검증한다.

## 중단과 재개

동일 옵션에 `--resume`을 추가하면 완료 사례는 건너뛴다. `checkpoint.jsonl`에는 쓰기 요청 전에
intent를, 초안 생성 직후 complaintId를, 분석 성공 직후 summary를, 상세 조회 후 원본 결과를
각각 flush·fsync한다. 분석 후 상세 조회만 실패한 경우에는 GET만 재실행한다.
인증·토큰 갱신이 성공한 뒤 intent를 기록하며, 그 기록과 실제 POST 사이에 다시 로그인하지 않는다.
인증 갱신만 실패하면 기존 단계(미생성 또는 `draft`)를 유지해 복구 후 안전하게 재개한다.

POST 중 연결이 끊기면 서버가 실제 처리했는지 알 수 없다. `creating`·`analyzing` 단계는
자동 재호출하지 않으며, 이때는 기존 초안·분석을 확인한 뒤 복구해야 한다. 손상된 JSONL을
조용히 무시하지 않는다. 동시 두 프로세스의 같은 체크포인트 사용도 파일 잠금으로 차단한다.
연속 3건의 AI 폴백은 서버 장애 가능성이 있어 새 요청을 중단한다. 이미 진행 중인 요청은 보존한다.

서버가 복구된 뒤 `--resume --retry-fallbacks`를 함께 사용하면, 성공한 HYBRID 사례는 건너뛰고
미시도 사례와 Rule-only로 끝난 사례만 처리한다. 기존 Rule-only 민원은 서버에서 캐시되므로
해당 실패 사례에만 새 초안을 생성한다. 이전 민원·분석 ID와 시도 횟수는 체크포인트에 보존하며
`replaced_fallback_attempts`에 재시도 수를 기록한다. 복구 전 자동으로 반복 호출하지 않는다.

`--replay-only`는 인증·모델 호출 없이 기존 체크포인트에서 보고서만 다시 생성한다.
이전 최종 실행과 비교하려면 `--previous-final reports/<이전-final-실행-ID>`를 추가한다.
이 옵션은 final 뷰만 받으며, 기존 평가기의 데이터·정답·정책 일치와 산출물 해시 검증을 그대로 적용한다.
실제 배포/생성 설정이 확인되지 않으면 비교를 통제된 A/B로 표시하지 않는다.

```bash
/tmp/teachercare-eval-env/bin/python scripts/evaluate_backend_goldenset.py \
  --capture-dir data/private/backend-g200-baseline \
  --report-dir reports/backend-g200 --replay-only --charts \
  --gold-standard-status team_approved
```

## 산출물과 해석

capture-dir에 사례 ID ↔ 민원 ID ↔ 분석 ID, 실제 위험 점수·등급을 담은 `backend_cases.csv`,
세 뷰의 저장 예측, Rule 결과, 수집 manifest·checkpoint, `report_index.json`을 저장한다.
보고서는 `rule`, `llm`, `final`별 불변 실행 폴더로 저장하며 기존 results.csv, metrics.json,
mismatches.csv, 실패·근거·검토 그룹 지표와 그래프를 재사용한다. metrics.json에도 버전을 기록한다.
중단된 실행의 미시도 사례는 `not_attempted.csv`로 분리한다. coverage와 summary는 실제 수집의
성공·실패·미시도를 구분하고, 오프라인 재평가의 처리 수는 `replay_processing`에 별도로 보존한다.

- **rule**: 동일 실행에서 캡처한 Rule 상태다. 모델을 별도로 호출하지 않는다.
- **llm**: 백엔드가 마스킹·Rule 문맥을 적용한 LLM 결과다. 독립 LLM-only 평가와 다르다.
  HTTP 200이어도 RULE_ONLY 폴백이면 LLM 품질 평가에서는 실패로 제외하고 coverage에 남긴다.
- **final**: 서버가 결합한 최종 상태다. 운영 폴백 결과도 포함한다.
  detector-results에는 최종 근거가 없어 final 뷰의 근거 일치율은 미평가다.
- final의 `diff.json`, `newly_wrong.csv`는 같은 사례의 Rule 대비 최종 결합 효과를 비교한다.
  프롬프트 개선 전후 실험이 아니며, 통제된 A/B나 새 모델 버전의 성능 개선으로 해석하지 않는다.
- 검토 완료 `teacher_reviewed`와 `unconfirmed` 지표를 별도 보고한다. 전체 200건을 모두
  사람 확정 정답으로 간주하지 않는다. 팀이 두 원본 CSV를 최종 평가 기준으로 확정했다면
  `--gold-standard-status team_approved`를 명시한다. 이때 전체 200건 태깅 지표를 주 결과로
  보고하며, 기존 CSV의 검토 상태는 변경하지 않고 추적 정보로 보존한다.
- REPEAT는 제외한 7종 평가다. 골든셋의 이력·횟수·규정·학교급·정답 필드는 요청하지 않는다.
  각 사례는 동일한 데모 학생·교사 맥락의 독립 초안이며 원본 사례별 이력을 재현하지 않는다.
- 실제 마스킹된 모델 입력은 공개 API에서 캡처할 수 없으므로 입력 해시의 provenance는
  미확인으로 남긴다. 근거의 원문 존재 여부는 골든셋 원문에 대한 제한된 검사다.
- 서버가 실제 배포 SHA·프롬프트·Rule·RAG·SDK 생성 설정을 반환하지 않으면 null 또는
  `server_unreported`다. 저장소 HEAD를 배포 버전으로 기록하지 않는다.
- 최종 위험도는 **실제 서버 예측**을 저장한다. CONFIRMED 사람 정답이 있어야만 4×4
  혼동행렬·High/Emergency 재현율·과대평가율을 계산한다. 정답이 없으면 `not_evaluated`,
  재현율은 null이며 위험도 혼동행렬 PNG는 생성하지 않는다. 예측 등급 분포는 정확도가 아니다.

## 검증

`python -m pytest tests/test_backend_evaluation.py`는 외부 호출 없이 요청 경계, 비밀값 미노출,
체크포인트 재개·잠금, 불명확한 POST의 재호출 방지, 폴백·정답 누락 처리와 보고서 연결을 검증한다.

## 실제 200건 기준 결과 (2026-11-17)

팀이 승인한 원본 골든셋 200건으로 공개 Backend의 최종 태깅 결과를 평가했다.
크레딧 소진 후 복구한 실행이며 최종 HYBRID·AI 성공 200/200건, 실패·미시도 0건이다.
기존 성공 112건은 재호출하지 않았다. 보고된 모델명은 `claude-sonnet-4-6`이다.

| 양성 처리 정책 | Macro P | Macro R | Macro F1 | Micro P | Micro R | Micro F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| PRESENT | 0.7556 | 0.9739 | 0.8267 | 0.6936 | 0.9756 | 0.8108 |
| PRESENT + BOUNDARY | 0.7784 | 0.9690 | 0.8467 | 0.7371 | 0.9728 | 0.8387 |

REPEAT 제외 7종·1,400개 상태를 비교하고, 이진 지표는 정답 UNKNOWN 4개를 제외한
1,396개 라벨을 사용했다. 최종 상태 오답은 63개 사례·73개 라벨이다.
같은 실행에서 캡처한 LLM 구성요소와 최종 상태는 이번 7종 범위에서 일치했다.
이 결과는 원본 이력이 없는 동일 데모 맥락의 결합 실행이며, 독립 LLM-only 실험이나
프롬프트 개선 전후 비교로 해석하지 않는다.

원본 결과의 최종 실행 ID는 `20261117T072712022229Z_backend-g200-recovered-final_c59fe6cb`다.
`report_index.json`이 Rule·LLM·final 보고서 폴더를 가리킨다. 원본 응답·체크포인트·사례별
보고서는 `data/private/`와 `reports/`에 로컬 보관하며 PR에는 포함하지 않는다.
최종 위험도 예측은 200건 저장했지만 사람이 확정한 위험도·세부 유형·정당성 정답은 없어
해당 지표와 위험도 혼동행렬은 미평가다. #26의 남은 완료 조건으로 유지한다.
