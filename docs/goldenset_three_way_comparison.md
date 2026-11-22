# Golden Set 200건 — 위험요소 태깅 성능 3방식 비교

## 1. 실험 설계

같은 200개 골든셋(7개 태그, REPEAT 제외)에 대해 다음 세 출력을 평가합니다.

| 조건 | 입력/호출 | 주의 |
| --- | --- | --- |
| Rule Only | Backend DictionaryRuleBasedRiskDetector 결과 | 실제 Rule 실행 결과를 사용. 보고서 PDF의 집계값만으로는 사례별 통계 검정 불가 |
| LLM Only | 민원 + RAG → Claude, Rule results=[] | `--mode llm`, 모의 LLM 금지 |
| Rule+LLM | 민원 + RAG + 실제 Backend Rule 결과 → Claude → 최종 태그 결합 | 기존 11/17 Backend capture의 `final` **태그 결과** 재사용 가능. Risk Engine의 위험도 계산은 평가에서 제외 |

**유의:** 11/17 Backend 캡처는 운영 단계의 마스킹과 서버 설정이 적용된 것이고, AI 서버에 직접 요청한 LLM Only와 입력 전처리가 다를 수 있습니다. 세 결과를 나열하더라도 버전·전처리·RAG·모델·온도·SDK가 확인되기 전에는 통제된 A/B로 주장하지 않습니다. `REPEAT`는 역사 정보가 없으므로 태그 성능에서 제외합니다.

## 2. 준비된 소스

- 골든셋: `data/goldenset/TeacherCare_goldenset_200cases.csv`, `TeacherCare_goldenset_200risktages.csv`
- AI 평가: `scripts/evaluate_risk_prompt_updated.py`
- 실제 Backend 캡처: `scripts/evaluate_backend_goldenset.py` 및 11/17 `data/private/backend-g200-baseline/` (로컬 소유자에게 전달 요청)
- 오프라인 3방식 비교: `scripts/compare_goldenset_three_way.py`

## 3. 사전 점검 — 외부 모델 호출 없음

```bash
cd ~/Desktop/AI
source .venv/bin/activate
git switch feat/goldenset-three-way-comparison

python scripts/evaluate_risk_prompt_updated.py --dataset goldenset --validate-only
python -m pytest tests/test_three_way_comparison.py -v
```

## 4. 실제 LLM Only 수집

**실제 Claude API 키와 구동 중인 AI API 서버가 필요합니다.** API 키를 공유 채팅이나 Git에 남기지 마세요. `--mode llm`은 Rule 결과가 빈 배열이어야 합니다. 네트워크·모델 비용이 발생합니다.

```bash
# 먼저 3건 스모크 테스트
python scripts/evaluate_risk_prompt_updated.py \
  --dataset goldenset --mode llm --limit 3 \
  --report-dir reports/g200-llm-smoke

# 동일 설정을 확인한 뒤 200건 전체 실행 (스모크와 별개의 신규 평가)
python scripts/evaluate_risk_prompt_updated.py \
  --dataset goldenset --mode llm \
  --report-dir reports/g200-llm-only \
  --checkpoint-file data/private/llm-only-g200-checkpoint.jsonl
```

각 결과는 `reports/g200-llm-only/<run_id>/` 형태의 **불변 결과 폴더**에 저장됩니다. 중간 실패 시 checkpoint를 점검하여 중복 유료 호출을 방지하세요.

## 5. Rule Only 및 Rule+LLM 태깅 결과 준비

팀원의 기존 Backend 평가를 재사용할 수 있다면, 해당 평가의 `report_index.json`을 확인해 `rule`과 `final` **실제 실행 디렉터리**를 확보합니다. 보고서 PDF나 수치표가 아니라 `manifest.json`, `results.csv`, `cases.csv`를 모두 가진 디렉터리여야 합니다.

기존 기록에서 `final`은 Rule+LLM 결합으로 확정한 **위험요소 태그 상태**입니다. 단, Rule이 LLM에 제공된 방식 및 RAG/마스킹이 독립 LLM Only 실행과 동일 조건인지 따로 확인하세요. 동일 캡처의 `llm` 뷰는 **Rule-conditioned LLM**이므로 이번 실험의 LLM Only로 대체할 수 없습니다.

**Risk Engine은 태깅 이후 최종 위험도(LOW/MEDIUM/HIGH/EMERGENCY)를 결정하는 별도 단계입니다.** 이번 실험에서는 Risk Engine의 점수·등급·혼동행렬·위험도 재현율을 계산하거나 비교하지 않습니다.

## 6. 세 방식 결과 합치기 — 외부 호출 없음

```bash
python scripts/compare_goldenset_three_way.py \
  --rule-run "<RULE_RUN_DIRECTORY>" \
  --llm-run "<LLM_ONLY_RUN_DIRECTORY>" \
  --rule-llm-run "<BACKEND_FINAL_TAGGING_RUN_DIRECTORY>" \
  --output reports/g200-three-way/comparison.json \
  --bootstrap-rounds 1000
```

산출물:
- Rule Only / LLM Only / Rule+LLM 세 방식의 동일 데이터셋 해시·200건 사례 ID·태그 정답·파일 무결성 확인
- 세 실행에서 **모두 성공한 동일 사례**로 다시 산출한 7태그 Macro/Micro P·R·F1 및 태그별 F1
- 사례 단위 paired bootstrap으로 Macro F1 차이의 95% 구간
- 7태그 전체 정답 사례 비율에 대한 *사례 단위* exact McNemar 검정
- `comparison_tag_metrics.csv`: 방식×양성 판정 기준×태그별 P/R/F1 및 TP/FP/FN/TN, 비교 사례 수
- `comparison_disagreements.csv`: 같은 사례·태그에서 세 방식의 판정이 달랐던 항목만 저장 (case_id, 태그, 정답·예측 상태, 방식별 정오 판정)
- 민원 원문과 LLM 응답 본문은 새 CSV에 포함하지 않으며, 기존 결과 파일은 덮어쓰지 않습니다.
- 실행별 성공 수·공통 평가 수·지연시간(측정 경계가 다를 수 있음)

전체 200건이 모두 성공하지 않으면 `complete_200_case_comparison=false`로 표시하며, **누락 결과를 정답이나 정상 예측으로 간주하지 않습니다.**

## 7. 실험 해석에서 반드시 구분할 것

1. Rule Only 보고서의 PRESENT Macro F1 0.000과 후보 기준 Macro F1 0.300은 실제 200건 태깅 결과입니다.
2. 11/17 Backend 결합 PRESENT Macro F1 약 0.827은 **과거 실측값**이며, 통제된 LLM Only와의 인과 차이라고 말하면 안 됩니다.
3. 3방식의 입력 전처리와 LLM 생성 설정이 동일하지 않다면 '운영 성능 비교(관찰 연구)'로 표시하고, Rule 프롬프트 효과에 대한 통제 실험은 A(민원+RAG)와 B(민원+RAG+Rule)를 같은 API 버전에서 별도 실행합니다.
4. 200건은 AI로 생성한 합성 민원이라 실제 사용자 분포에 대한 일반화에는 제한이 있습니다.

## 이번 실험에서 제외하는 항목

- Backend `RiskEvaluator` / Risk Engine의 위험 점수 및 LOW·MEDIUM·HIGH·EMERGENCY 등급
- 위험도 등급 혼동행렬, 가중 Kappa, HIGH·EMERGENCY 재현율
- 위 항목들은 이후 별도 **최종 위험도 판정 성능 평가**에서 다룹니다.
