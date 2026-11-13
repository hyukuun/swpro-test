# Python-correction-engine

한글 손글씨 교정엔진. 원고지 칸 배열(획 좌표)을 받아 **글자 → 띄어쓰기 → 획순** 순서로 판정합니다.

```
FE (iPad Safari) → Spring Boot → 교정엔진 (FastAPI)
```

## 구조

```
app/
├── main.py                    # FastAPI 엔드포인트 (스프링부트와 통신)
├── config.py                  # 환경변수 설정
├── errors.py                  # 오류 응답 (400·422·404·405·500을 한 가지 모양으로)
├── schemas.py                 # 요청/응답 모델
├── pipeline.py                # 인식 → 정렬 → 획순 → 결과 종합 흐름
├── core/
│   ├── hangul.py              # 음절 분해/조합, 겹받침, 음절 구조 유형 (D-05)
│   └── reference.py           # 정답 획 데이터 읽기 (compose() 결과)
├── services/
│   ├── recognizer.py          # 칸별 글자 인식
│   ├── stroke_checker.py      # 획 수·획순·방향
│   ├── spacing_align.py       # 문장 정렬, 띄어쓰기
│   ├── aggregate.py           # 단계별 결과 묶기
│   ├── feedback_templates.py  # 설명 문장, 킹세종 템플릿
    └── llm_feedback.py        # 킹세종 LLM 한마디
tests/
```

## 입력과 출력 한눈에 보기

### 1. 바깥: 스프링부트 ↔ 교정엔진

스프링부트가 원고지에 쓴 내용을 보내면(`POST /grade`), 엔진이 판정 결과를 돌려줍니다. 형식은 `app/schemas.py`에 있습니다.

**보내는 것 (요청)**: "이 문장을 이 단계에서 이렇게 썼어요"

```jsonc
{
  "stage": "advanced",            // 학습 단계: beginner(초보) | intermediate(중수) | advanced(고수)
  "target": "나 너",              // 정답 문장 (띄어쓰기 포함)
  "locale": "ko",                 // 피드백 문장 언어: ko | en
  "canvas": { "w": 300, "h": 300 }, // 원고지 칸 하나의 크기(px)
  "cells": [                      // 원고지 칸 전체, 왼쪽→오른쪽·위→아래 순서
    { "index": 0, "strokes": [    // 칸 0에 쓴 획들 (쓴 순서대로)
        { "points": [[75, 60, 0, 0.5], [75, 150, 80, 0.5]] }   // 점 하나 = [x, y, 시간ms, 필압]
    ] },
    { "index": 1, "strokes": [] } // 빈 칸 = 띄어쓰기
  ]
}
```

- 좌표 `x, y`는 **그 칸의 왼쪽 위가 (0, 0)**인 픽셀. 칸 경계를 넘어가도 처음 펜을 댄 칸에 넣는다
- 점은 객체가 아니라 **숫자 4개짜리 배열** `[x, y, t, p]`. 자바에서는 `List<double[]>`(또는 `List<List<Double>>`)로 받으면 됩니다. JSON Schema에는 `prefixItems`로 적혀 있는데, 이 문법을 모르는 DTO 생성 도구가 있으니 이 필드는 직접 타입을 지정하세요
- 초보·중수는 칸 수 = 정답 글자 수(공백 제외). 고수는 칸을 넉넉히 주고, 빈 칸이 띄어쓰기

**요청 검사 규칙**: 아래를 어기면 엔진이 판정하지 않고 **422**와 이유 문장을 돌려줍니다. 기준 숫자는 `app/schemas.py` 맨 위 `MAX_*` 상수에서 바꿉니다.

| 항목 | 규칙 |
| --- | --- |
| 정답 문장 `target` | 한글, 띄어쓰기, 문장부호 `? ! . ,` 만. 1~20칸(띄어쓰기 포함). 앞뒤 공백·연속 공백 없음 |
| 초보 | 띄어쓰기 없는 단어 하나, 또는 자모 하나(ㄱ, ㅏ). 칸 수 = 글자 수 |
| 중수 | 어절 3개 이하. 자모 단독 안 됨. 칸 수 = 공백 뺀 글자 수 |
| 고수 | 자모 단독 안 됨. 칸 수 ≥ 정답 칸 수(띄어쓰기 포함) |
| 칸 `cells` | 1~30칸. `index`가 0부터 빠짐없이 순서대로 |
| 칸 크기 `canvas` | 0보다 큼 |
| 획 `strokes` | 획 하나에 점 1개 이상 |
| 점 `[x, y, t, p]` | 숫자 4개 |
| 필드 이름 | 정해지지 않은 필드가 오면 거절 (오타 방지) |

획이 하나도 없는 제출(빈 원고지)은 거절하지 않고 판정합니다. 결과는 모든 칸이 글자 오류입니다.

규칙별 예시는 `tests/test_request_rules.py`에 있습니다.

**판정하지 못했을 때 (오류 응답)**: 200이 아니면 항상 이 한 가지 모양입니다. 스프링부트는 `code`로 분기하면 됩니다.

```json
{
  "code": "INVALID_REQUEST",
  "message": "요청 값이 규칙에 맞지 않아요 (2개)",
  "details": [
    { "field": "canvas.w", "message": "Input should be greater than 0" },
    { "field": "typo", "message": "Extra inputs are not permitted" }
  ],
  "engineVersion": "0.1.0-stub"
}
```

값 하나하나의 오류(형식·범위, pydantic 기본 영어 문장)를 먼저 모두 알려 주고, 그게 없을 때 단계 규칙(예: `"field": null, "message": "초보는 띄어쓰기 없는 단어 하나(또는 자모 하나)만 써요"`)을 검사합니다.

| HTTP | `code` | 언제 | 스프링부트는 |
| --- | --- | --- | --- |
| 400 | `INVALID_JSON` | 본문이 JSON이 아님 | 보내는 코드 버그. 다시 보내도 같음 |
| 422 | `INVALID_REQUEST` | 위 요청 검사 규칙을 어김. `details`에 틀린 값 위치(`field`)와 이유 | 보내는 값 확인. 다시 보내도 같음 |
| 404 | `NOT_FOUND` | 없는 주소 | 주소 확인 |
| 405 | `METHOD_NOT_ALLOWED` | GET/POST가 다름 | 방식 확인 |
| 500 | `INTERNAL_ERROR` | 엔진 내부 오류 (내용은 엔진 로그에만 남김) | 잠시 뒤 다시 시도할 수 있음 |

- `field`는 요청 JSON 기준 위치 (`cells[0].strokes[1].points`). 요청 전체에 걸친 규칙이면 `null`
- 형식: `app/schemas.py`의 `ErrorResponse`, JSON Schema: `docs/schema/error_response.schema.json`, 처리 코드: `app/errors.py`

**받는 것 (응답)**: "어디가 맞고 어디가 틀렸어요"

| 필드 | 뜻 | 화면에서 쓰는 곳 |
| --- | --- | --- |
| `sessionId` | 요청의 `sessionId`를 그대로 돌려줌 | 스프링부트 로그 맞추기 |
| `correct` | 글자 + 띄어쓰기가 모두 맞음 | 고수 결과(맞음/틀림), 쓰기 기록 |
| `perfect` | `correct`이고 획순도 모두 맞음 | 쓰기 기록, 칭찬 |
| `cells[]` | 칸마다의 결과 (요청 칸과 같은 순서) | 초보 결과 화면 |
| `cells[].expected` / `recognized` | 이 칸의 정답 글자 / 학습자가 쓴 글자 | '이렇게 쓰셨어요' |
| `cells[].mark` | 칸 표시: `none` 맞음, `char` 빨강(글자), `spacing` 빨강(띄어쓰기), `stroke` 주황(획순) | 상자 색 |
| `cells[].errors[]` | 획순·글자 오류 상세 (`ORDER`, `DIRECTION`, `CHAR_MISMATCH` …) | 숙련도 집계, 획 빨갛게 표시 |
| `cells[].strokeMap[]` | 학습자 획 ↔ 정답 획 짝 | 나란히 리플레이 |
| `alignment[]` | 내가 쓴 줄 ↔ 정답 줄을 칸끼리 맞춘 것 | '정답 비교' 화면 |
| `words[]` | 어절별 맞음/틀림 | 중수 결과(어절 빨간 상자) |
| `explanations[]` | '이렇게 고쳐요' 문장 (예: 십었어라고 쓰셨는데 싶었어라고 써야 해요.) | 정답 공개 |
| `sejong` | 킹세종 말풍선 (`text`, `subText`, 표정) | 결과 화면 위 |

전체 예시는 `tests/fixtures/grade_request_*.json`, `grade_response_*.json` (초보 바다 / 중수 보고 싶었어 / 고수 나 너 좋아하냐?)에 있습니다.

### 2. 안쪽: 엔진 모듈끼리

`/grade` 요청 하나가 아래 순서로 지나갑니다. 각 함수의 자세한 입력·출력은 파일 맨 위 설명에 있습니다.

```
요청
 │
 ├─① recognize      칸마다 "무슨 글자를 썼나?"          → 후보 목록  [("십", 0.6), ("싶", 0.3)]
 ├─② align          정답 문장과 칸을 줄 맞춤              → 칸별 정답 글자, 띄어쓰기 오류
 ├─③ check_strokes  글자가 맞은 칸만 "순서대로 썼나?"     → 획순 오류, 획 짝
 ├─④ aggregate      ①②③을 화면용으로 묶기                → 칸 색(mark), 어절 결과, correct·perfect
 ├─⑤ explanations   틀린 곳 설명 문장 만들기              → '이렇게 고쳐요'
 └─⑥ sejong_message 킹세종 말풍선 (LLM이 되면 sejong_line) → 말풍선
 ▼
응답
```

| 단계 | 함수 | 파일 | 담당 | 받는 것 | 주는 것 |
| --- | --- | --- | --- | --- | --- |
| ① 글자 인식 | `recognize` | `services/recognizer.py` | 혁윤 | 칸, 칸 크기, 올 수 있는 정답 글자 | 칸 종류(빈 칸·점·글자) + 점수 높은 순 후보 |
| ② 줄 맞춤 | `align` | `services/spacing_align.py` | 혁윤 | 정답 문장, 단계, ①의 결과 전부 | 칸별 정답 글자·맞음 여부, 띄어쓰기 오류 |
| ③ 획순 | `check_strokes` | `services/stroke_checker.py` | 정진 | 정답 글자, 칸 크기, 학습자 획 | 통과 여부, 획 오류, 획 짝, 걸린 시간 |
| ④ 묶기 | `aggregate` | `services/aggregate.py` | 혁윤 | 요청, ①②③ 결과 | 칸 결과, 줄 맞춤, 어절 결과, correct·perfect |
| ⑤ 설명 | `explanations` | `services/feedback_templates.py` | 혁윤 | 요청, ④ 결과 | 설명 문장 목록 |
| ⑥ 말풍선 | `sejong_message` / `sejong_line` | `feedback_templates.py` / `llm_feedback.py` | 혁윤 | 요청, ④ 결과 | 킹세종 말풍선 (LLM이 실패하면 템플릿) |

①과 ③은 정답 획 데이터를 `core/reference.py`의 `get_reference(글자)`로 꺼내 씁니다. 함수 이름이나 매개변수를 바꾸면 `tests/test_interfaces.py`가 알려 주니, 바꿀 때는 이 표와 테스트를 같이 고치세요.

## 실행

**Python 3.12**를 씁니다 (`.python-version`, CI도 같은 버전). 다른 버전으로 가상환경을 만들면 라이브러리 설치나 동작이 달라질 수 있어요.

```bash
python -m venv .venv            # python --version 이 3.12인지 먼저 확인
.venv/Scripts/activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload   # http://localhost:8000/health
```

## 검사 (CI와 같은 순서)

```bash
pip install -r requirements-dev.txt   # pytest, httpx, ruff, mypy
ruff check .            # 린트. 자동 수정: ruff check . --fix
ruff format .           # 포맷 자동 정리 (CI는 ruff format --check .)
mypy                    # 타입 검사: 모듈끼리 주고받는 값의 모양이 맞는지
pytest
```

GitHub에 push하거나 PR을 올리면 `.github/workflows/ci.yml`이 위 네 가지를 자동으로 검사합니다.
설정은 `ruff.toml`, `mypy.ini`에 있습니다. 테스트에서 예시 JSON을 읽거나 클라이언트를 만들 때는 `tests/helpers.py`를 씁니다.

> Windows에서 mypy가 `DLL load failed`로 실행되지 않으면 프로젝트 폴더 경로가 너무 긴 경우예요. 경로가 짧은 곳(예: `C:\dev\`)에 clone하면 됩니다.

## 스프링부트 연동 (D-09)

| 주소 | 설명 |
|---|---|
| `POST /grade` | 판정 요청 → 판정 결과. **지금은 형식만 맞춘 임시 응답** (`engineVersion`이 `-stub`으로 끝남) |
| `GET /health` | 살아 있는지 확인. `{"status": "ok", "engineVersion": "0.1.0-stub"}` — `-stub`이면 임시 응답 중 |
| `GET /docs` | 필드 설명을 브라우저에서 보고 직접 호출해 볼 수 있음 |

- 형식 정의: `app/schemas.py`
- 백엔드용 JSON Schema: `docs/schema/*.schema.json` (`python -m scripts.export_json_schema`로 다시 만듦)
- 피그마 장면별 예시: `tests/fixtures/grade_request_*.json`, `grade_response_*.json`
  - `beginner` 바다 (다 획순 틀림) / `intermediate` 보고 싶었어 (싶→십) / `advanced` 나 너 좋아하냐? (나너 붙여 씀)
  - 응답 예시는 진짜 판정이 나올 모양이다. 지금 `/grade`는 형식만 맞춘 임시 응답(모든 칸 맞음)을 돌려준다
- 잘못된 요청은 422 (규칙은 위 '요청 검사 규칙' 표)

다른 컴퓨터(백엔드)에서 호출하려면 `--host 0.0.0.0`으로 띄운다:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```
