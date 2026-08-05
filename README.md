# AI 민원 처리 시스템 - Backend

학교 민원 처리 지원 AI 서비스의 백엔드 서버입니다.

민원 내용을 분석하여 위험 요소를 탐지하고, 학교 규정(RAG)을 기반으로 답변 초안을 생성하며, 위험도에 따른 처리 워크플로우를 제공합니다.

---

# 기술 스택

- Python 3.13
- FastAPI
- Uvicorn
- Pydantic
- OpenAI API
- ChromaDB (RAG)
- SQLite (MVP)
- Git / GitHub

---

# 프로젝트 구조

```
Backend
│
├── app
│   ├── api
│   │   └── v1
│   │       └── endpoints
│   │
│   ├── core
│   │
│   ├── schemas
│   │
│   ├── services
│   │
│   ├── __init__.py
│   └── main.py
│
├── docs
├── tests
│
├── .env
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

---

# 주요 기능

## 1. RAG 검색

- 학교 규정 검색
- 학교 업무 매뉴얼 검색
- 관련 사례 검색
- 근거 문서 반환

---

## 2. 위험 요소 태깅

LLM(Few-shot)을 이용하여 민원의 위험 요소를 태깅합니다.

탐지 항목

- 욕설·감정 표현
- 직접 인격 공격
- 협박
- 법적 조치 언급
- 공개·유포 위험
- 반복성
- 부당 요구
- 개인정보 위험

LLM은 위험 요소만 태깅하며,
최종 위험도 계산은 Risk Engine이 수행합니다.

---

## 3. 답변 생성

RAG 검색 결과를 근거로

- 답변 초안 생성
- 완충 요약 생성
- 공식 답변 템플릿 생성

을 수행합니다.

---

# 시스템 구조

```
민원 입력

↓

개인정보 마스킹

↓

위험 요소 태깅 (LLM)

↓

Risk Engine

↓

위험도 계산

↓

RAG 검색

↓

답변 생성

↓

결과 반환
```

---

# API

## RAG Search API

```
POST /api/v1/rag/search
```

학교 규정 및 관련 문서를 검색합니다.

---

## Risk Tagging API

```
POST /api/v1/risk/tag
```

민원의 위험 요소를 태깅합니다.

---

## Answer Generation API

```
POST /api/v1/answer/generate
```

RAG 결과를 기반으로 답변 초안을 생성합니다.

---

# 개발 환경

Python

```
3.13+
```

가상환경 생성

```bash
python -m venv .venv
```

활성화

Mac / Linux

```bash
source .venv/bin/activate
```

Windows

```bash
.venv\Scripts\activate
```

패키지 설치

```bash
pip install -r requirements.txt
```

---

# 실행

```
uvicorn app.main:app --reload
```

Swagger

```
http://127.0.0.1:8000/docs
```

ReDoc

```
http://127.0.0.1:8000/redoc
```

---

# 환경 변수

`.env`

```
OPENAI_API_KEY=

DATABASE_URL=

SECRET_KEY=

DEBUG=True
```

---

# 브랜치 전략

```
main
```

배포 브랜치

```
develop
```

통합 개발 브랜치

기능 개발

```
feature/*
```

환경 설정

```
chore/*
```

문서 수정

```
docs/*
```

버그 수정

```
fix/*
```

---

# 커밋 컨벤션

```
feat:
```

새로운 기능

```
fix:
```

버그 수정

```
chore:
```

환경 설정

```
docs:
```

문서 수정

```
refactor:
```

리팩토링

```
test:
```

테스트

---

# 향후 개발 예정

- Rule Engine 구현
- RAG 검색 엔진 구축
- OpenAI 연동
- 위험도 계산 로직 구현
- 증빙 패키지 생성
- 민원 처리 상태 관리
- 관리자 승인 워크플로우
