# 개발셋 중심 개인정보 태깅 개선 후보

개선 버전은 `risk-dev-privacy-v1`이다. 개발셋에서 확인한 익명 인물 표지의 개인정보 과탐을
프롬프트에서 수정했다. **수정 후 실제 모델 성능 향상은 아직 검증하지 않았다.**
기존 공개 Backend로 수집하는 개발셋 실행은 배포 전 기준 결과다.

## 근거와 변경

검토 자료는 `data/dev/`의 100건·800개 AI_PROPOSED 라벨과 과거 개발셋 평가 결과다.
이번 튜닝에서 골든셋 개별 원문·정답·오답을 사용하지 않는다. 이미 알려진 기존 골든셋의
집계 성능은 보존하며, 이를 새 버전의 성능으로 재사용하지 않는다.

기존 PRIVACY 지침에는 익명 학생·교사 표지만 있어도 PRESENT로 판정하라는 문장이 있었다.
과거 개발셋 응답에는 이 지침을 따른 DEV025·DEV036·DEV068·DEV070·DEV081의 과탐이 있다.
학습 상담·일정 안내뿐 아니라 위해·모욕 문맥에서도 익명 표지 하나를 개인정보의 근거로 삼았다.
새 기준은 익명 인물 언급과 실제 연락정보 포함·제3자 비공개 정보 요구·신상 공개 압박을 구분한다.

- 익명 역할 표지만으로 개인정보 태그를 확정하지 않는다.
- 명시적인 연락처·주소 종류의 마스킹 표지는 개인정보 포함의 근거가 될 수 있다.
- 익명화했더라도 제3자의 성적·징계·연락처 등 비공개 정보 요구는 문맥으로 판단한다.
- THREAT·INSULT에 익명 인물이 등장한다는 사실을 PRIVACY에 복사하지 않는다.
- 개발 데이터 코드명은 실제 `PERSONAL_INFO_MISUSE_RISK`와 일치시킨다.

점수 가중치·위험도 임계값 또는 모델 출력을 정답으로 덮어쓰는 처리는 추가하지 않았다.
개별 사례 ID나 전체 문장을 조회해 정답을 반환하는 사전도 추가하지 않았다.

## 개발 라벨 검토 대기

DEV071의 PRIVACY=PRESENT 근거는 익명 표지의 포함 자체를 들고 있어 다른 익명 표지 사례와
기준이 충돌할 가능성이 있다. 관계·행동 정보의 맥락까지 포함한 사람 검토가 필요하다.
DEV096처럼 개인정보 요구 목적이 경계인 사례도 자동으로 재라벨링하지 않는다.
원본 CSV와 기존 검토 메타데이터를 유지하고, 전체 100건 평가에서 불리한 사례를 제외하지 않는다.
`review_required=NO`도 현직 교사 확정 정답이라는 뜻은 아니다.

과거 개발 보고서에는 모델명이 `claude-sonnet-5-5`로 기록되어 있고 배포 소스가 확인되지 않는다.
그 점수와 새 실행 점수를 통제된 개선 전후 실험으로 비교하지 않는다.

## 아까 사용한 공개 Backend 경로로 개발셋 실행

`evaluate_backend_goldenset.py`는 기존 파일명을 유지하면서 `--dataset dev`를 지원한다.
기본값은 기존 `goldenset`이다. 입력 원문만 독립 DRAFT로 만들며 정답·이력·규정 필드는 보내지 않는다.
API 키는 필요 없고 이전과 같은 테스트 PARENT 계정으로 로그인한다. 실제 모델 비용이 발생한다.

```bash
# 수정 전 서버의 개발셋 100건. 계정은 대화형 입력 또는 기존 환경변수로 제공한다.
python scripts/evaluate_backend_goldenset.py --dataset dev \
  --capture-dir data/private/backend_dev_before_privacy \
  --report-dir reports/backend_dev_before_privacy \
  --run-version dev-before-privacy --workers 2 --charts
```

기존 체크포인트가 있으면 같은 옵션에 `--resume`을 붙인다. 성공 사례는 재호출하지 않는다.
개발셋을 `--gold-standard-status team_approved`로 선언하거나 다른 데이터셋 보고서와
비교하려 하면 모델 호출 전에 거부한다. 재평가만 할 때에는 `--replay-only`를 사용한다.

## 수정 후 실제 검증 순서

1. AI 서버에 후보 소스를 배포하고 프로세스를 재시작한다. GitHub의 Backend 배포 workflow는
   Java 서버를 배포하므로 AI 프롬프트 반영 여부를 별도로 확인한다. 현재 AI 저장소 workflow는
   오프라인 테스트이며 AI 서버 배포를 수행하지 않는다.
2. 직접 AI 응답의 `metadata.evaluationProvenance.prompt_version`이 `risk-dev-privacy-v1`인지,
   `source_hashes`가 배포 소스와 맞는지 확인한다. 프롬프트 버전은 로드한 소스 상수를 사용하므로
   오래된 `PROMPT_VERSION` 환경변수만 바꿔서 새 버전으로 표시할 수 없다.
3. Backend가 해당 메타데이터를 전달하지 않으면 AI 서버의 응답·배포 기록으로 확인하고,
   공개 평가 결과에는 확인되지 않은 항목을 계속 `server_unreported`로 남긴다.
4. 같은 계정·학생·교사·모델·Rule·RAG·생성 설정으로 개발셋을 실행한다. 이전 final 경로는
   수정 전 capture의 `report_index.json.reports.final` 값을 사용한다.

```bash
python scripts/evaluate_backend_goldenset.py --dataset dev \
  --capture-dir data/private/backend_dev_after_privacy \
  --report-dir reports/backend_dev_after_privacy \
  --run-version dev-after-privacy --workers 2 --charts \
  --previous-final reports/backend_dev_before_privacy/final/<이전-실행-ID>
```

5. 전체 7종 P/R/F1·새 오답·실패/회복과 PRIVACY 과탐/미탐을 함께 확인한다. 일부 태그의 개선이
   다른 태그의 악화나 요청 실패로 상쇄되는지 본다. 실제 배포·검색·생성 설정이 불명확하면
   이 비교를 통제된 A/B로 표시하지 않는다.
6. 개발셋으로 설정을 확정한 뒤 후보 커밋·프롬프트 해시·모델·Rule·RAG 설정을 동결한다.
   그 뒤 동일 골든셋으로 한 번 최종 확인하며, 골든셋 결과를 보고 다시 이 후보를 튜닝하지 않는다.

골든셋 최종 실행은 아직 수행하지 않는다. 개발셋 검증과 후보 동결이 먼저다.
#26의 완료 범위는 200건·7종 태깅 파이프라인이며, 확장 평가는 #47·배포 버전은 #31에서 추적한다.

## 오프라인 검증의 의미

`python -m pytest`는 개발셋 선택·요청 경계·오류 처리·재개·데이터셋 간 혼입 차단 및 실제
로드된 프롬프트 버전 기록을 검사한다. 고정 모의 응답의 통과 수를 모델 성능 개선으로 해석하지 않는다.
