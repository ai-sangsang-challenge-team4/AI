# TeacherCare 최종 평가 기준 200건

팀이 공유한 「TeacherCare 최종 Golden Set 200건 공유」의 승인 결정을 적용한다.
최초 Claude AI 판정에서 19개 태그 상태를
수정한 최종 CSV 두 파일이 기준이다. 과거 v0.2 AI 초안이나 그 패키지의
`backend_privacy_tag`로 최종 `state`를 덮어쓰지 않는다.

## 확정 범위와 파일 식별

- 사례 200건, 사례당 8종 태그, 총 1,600개 상태가 팀 승인 평가 정답이다.
- 라벨 CSV의 현재 `state`를 사용하며, 사례 CSV의 8개 태그 컬럼과 일치해야 한다.
- `initial_v02_first_pass_state`, `v02_second_pass_state`, `prior_v04_state`는 변경 이력이다.
- `teacher_review_status`, `reviewStatus`, `decision_source`는 개별 검토 이력이다.
  `AI_PROPOSED_UNCONFIRMED`가 남아 있어도 팀 승인된 현재 `state`를 평가에서 제외하지 않는다.
  팀 승인과 2인 독립 라벨링·전체 교사 검증 완료는 구분하며, 원본 검토 표기는 보존한다.
- 최종 위험도, 정당한 민원 여부, PRIVACY/THREAT 세부 유형의 사례별 확정 정답은
  이번 승인 범위에 포함되지 않는다.

사용자가 제공한 CSV와 저장소 CSV는 바이트 단위로 동일하다.

| 파일 | 행 수 | SHA-256 |
| --- | ---: | --- |
| `TeacherCare_goldenset_200cases.csv` | 200 | `6320eb6270afc7db77588b763ab9d9b9538ed01b60567ea5126f00fc91c97cca` |
| `TeacherCare_goldenset_200risktages.csv` | 1,600 | `5b6e3a0688baf2e7fcc0b0de54024d0856c6621d2e86fbdc75deb731691804b7` |

## 태그 해석

공유문과 함께 제공된 `TeacherCare_goldenset_200cases.csv.xlsx`의 `코드북` 시트를
기준으로 정리했다. 워크북의 사례 원문·이력·규정과 1,600개 태그의 현재 상태·검토 표기가
대응 CSV와 일치하는 것도 확인했다. 개별 사례를 프롬프트 개선에 사용하지 않는다.

| 태그 | 평가 기준 |
| --- | --- |
| PROFANITY | 욕설·비속어 또는 거친 감정 표출. 일반적인 불만 자체는 제외 |
| INSULT | 교사·학생·학부모 등 특정 개인의 인격·능력·자격에 대한 직접 비하 |
| THREAT | 교사 외 학생·학부모·제3자 대상의 위해·보복·불이익 예고도 포함. 피해 사실의 단순 보고와 구분 |
| LEGAL | 실제 법적·행정적 공식 절차의 문의·신고·신청·진행 언급. 정당한 권리행사도 태그가 존재할 수 있으며 고위험 여부는 별개 |
| EXPOSURE | 외부 공개·유포를 통한 압박 또는 평판 위해 문맥 |
| REPEAT | 관련 과거 이력 또는 원문에 명시된 구체적인 이전 연락 사실. 반복 존재와 악성 여부는 별개 |
| UNFAIR_REQUEST | 규정·학교 권한·공정한 절차·형평성을 벗어난 구체적인 요구 |
| PRIVACY | 실제 식별 가능한 개인정보의 공개·요구·악용 또는 타인의 비공개 정보 요구. 합성 익명 표지나 가상 연락처 표지만으로 양성 판정하지 않음 |

상태는 `PRESENT/ABSENT/BOUNDARY/UNKNOWN`을 보존한다. 태그의 존재가 곧
악성 민원 또는 특정 위험도 등급의 정답을 뜻하지 않는다.

## 평가와 후속 작업

공개 Backend의 기존 실제 보고서는 `gold_standard_acceptance.status=team_approved`로
200건 전체를 평가했다. 원본 이력을 입력하지 않은 실행이므로 성능 지표는 REPEAT 제외
7종이며, 8종 응답은 모두 저장했다. 교사 검토 표기별 지표는 보조 분석이다.

`goldenset_evaluation_targets.csv`의 `PENDING`은 별도로 추가할 위험도·정당성·세부 유형
정답의 검토 상태다. 위 1,600개 태깅 정답의 팀 승인을 취소하거나 보류한다는 뜻이 아니다.
추가 값이 없는 상태에서 `CONFIRMED`로 일괄 변경하지 않는다.

- [#26 태깅 평가 계약](../../docs/evaluation_contract.md)
- [실제 Backend 평가 및 기존 200건 결과](../../docs/backend_evaluation.md)
- [#47 위험도·세부 유형 확장 평가](../../docs/supplemental_evaluation.md)

모델·프롬프트 개선은 개발셋에서 수행하고, 설정 동결 후 같은 골든셋으로 최종 확인한다.

## 최종 위험도 정답셋

`goldenset_risk_targets.csv`는 기존 골든셋 200건에 대한 최종 위험도 정답이다.
기존 위험 요소 태그와 사례 문맥을 참고해 사람이 검토하고, 200건 모두 `CONFIRMED`로 확정했다.
기존 사례 및 태그 CSV와는 `case_id`로 연결한다.

| 위험도 | 건수 | 검토 기준 |
|---|---:|---|
| `LOW` | 87 | 일반 문의, 정당한 이의 제기, 구체적 위해 신호가 없는 요청 |
| `MEDIUM` | 71 | 욕설, 모욕, 압박 또는 부당 요구 등 대응이 필요한 상황 |
| `HIGH` | 27 | 학생 피해, 개인정보 노출, 구체적인 위협 등 신속한 확인과 보호가 필요한 상황 |
| `EMERGENCY` | 15 | 임박한 신체 위해, 실종 의심, 급박한 학생 안전 신호 등 즉시 개입이 필요한 상황 |

위험 분석 API의 `riskLevel`을 정답의 `risk_level`과 비교한다.
측정 시간은 `backend_cases.csv`의 `latency_ms`를 사용하며, 위험 분석 POST 응답 시간을 뜻한다.