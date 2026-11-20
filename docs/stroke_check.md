# 획순·균형 판정 (`app/services/stroke_checker.py`, `stroke_balance.py`)

학습자가 쓴 획을 정답 획과 비교해 획 수·획순·방향·균형 오류를 찾습니다.

## 입출력

```python
check_strokes(target, canvas, strokes) -> StrokeCheckResult
```

| 입력 | 뜻 |
|---|---|
| `target` | 정답 글자 하나 (한글 음절 또는 자모 단독) |
| `canvas` | 칸 크기 (px) |
| `strokes` | 학습자 획, 쓴 순서대로, 칸 기준 픽셀 좌표 `[x, y, t, p]` |

| 출력 | 뜻 |
|---|---|
| `passed` | 명세의 pass. `errors`가 비었으면 True |
| `errors` | `ORDER` / `DIRECTION` / `MISSING` / `EXTRA` / `BALANCE` (`schemas.CellError` 형식) |
| `stroke_map` | 학습자 획 ↔ 정답 획 짝, 학습자 획마다 하나 (`schemas.StrokeMapItem` 형식) |
| `duration_ms` | 첫 점 ~ 마지막 점 시간(ms) |

- role은 `cho` / `jung` / `jong`으로 씁니다 (명세의 '초성/중성/종성' 대신, `schemas.Role`).
- **부르는 조건** (pipeline이 지킴): recognizer가 정답 글자를 맞게 썼다고 인정한 칸만,
  target이 한글 음절 또는 자모 단독일 때만 (문장부호·빈 칸은 부르지 않음).

## 구성

```
check_strokes()  ─┬─ 정답: core/reference.py get_reference() (정답 획 사전 composed_all.json)
 (진입점)          ├─ judge()                 획순: EXTRA / MISSING / DIRECTION / ORDER
                  └─ stroke_balance.check()  균형: BALANCE
                  → schemas 형식으로 바꿔 돌려줌
```

- `judge()`는 dict 입출력이고, role은 `check_strokes()`와 같이 `cho/jung/jong`입니다.
  필기 테스트(`scripts/hand_writing_confirm.py`)가 이 함수를 직접 부릅니다.

`judge()` 입력 예:
```json
{"target": "가", "canvas": {"w": 300, "h": 300},
 "strokes": [{"points": [[x, y, t_ms, pressure], ...]}, ...]}
```

## 획순 판정 과정 (`judge`)

참고: Nguyen et al. (2019), Pattern Recognition Letters 121, 140-149.

1. **맞추기**: 학습자 획을 칸 크기로 나눠 0~1로 바꾸고(`normalize`), 학습자·정답 획을 모두 32점으로 같은 간격으로 다시 찍습니다(`resample`).
2. **짝 비용**: 학습자 획 × 정답 획마다
   `비용 = ALPHA × SCF 차이 + (1 − ALPHA) × 위치 차이(32점 평균 거리)`.
   SCF는 획의 시작점·끝점에서 본 글자 전체 점들의 분포(8×8 격자)입니다.
   학습자 획을 **정방향·뒤집은 방향 둘 다** 계산해 작은 쪽을 쓰고, 뒤집은 쪽이 작았는지 기록합니다.
3. **짝짓기**: 비용 합이 가장 작은 1:1 짝을 헝가리안 알고리즘으로 찾고, 비용이 `REJECT`보다 큰 짝은 끊습니다.
4. **오류 구분**:

| 오류 | 기준 |
|---|---|
| `EXTRA` (더 씀) | 짝이 없는 학습자 획. 순서 셀 때와 자모별 균형에서 빠짐 |
| `MISSING` (덜 씀) | 짝이 없는 정답 획 |
| `DIRECTION` (거꾸로) | 짝은 있는데 뒤집은 쪽 비용이 더 작았음 |
| `ORDER` (순서) | 짝 번호를 쓴 순서대로 늘어놓고, 가장 긴 증가 순서(LIS)에 못 든 획만 (최소한으로 옮겨야 할 획) |

다른 획을 잘못 쓰면 `EXTRA`와 `MISSING`이 같이 나옵니다. 한 획에 `ORDER`와 `DIRECTION`이 같이 나올 수 있습니다.

| 파라미터 | 값 | 뜻 |
|---|---|---|
| `N_POINTS` | 32 | 획당 리샘플 점 수 |
| `GRID` | 8 | SCF 격자 8×8 |
| `HALF` | 1.0 | 격자 반폭 (기준점 ±1.0 → 칸 전체 포함) |
| `ALPHA` | 0.5 | SCF와 위치 차이의 비율 |
| `REJECT` | 0.45 | 비용이 이보다 크면 짝 없음. 낮추면 엄격, 높이면 관대 |

## 쓰기 방식 변형 (`WRITING_VARIANTS`)

정답은 폰트 모양 한 가지뿐이라, 손글씨에서 흔한 다른 쓰는 방법을 자모마다 허용합니다. 획 번호는 그 자모 안에서 0부터입니다.

| 방법 | 뜻 | 변형 정답 만드는 법 |
|---|---|---|
| `horizontal_tick: n` | n번 획(꼭지)을 가로(ㅡ)로 써도 됨 | 꼭지의 중심·길이는 그대로, 왼→오 가로선으로 바꿈 |
| `merge_strokes: (a, b)` | a번·b번 획을 한 번에 이어 써도 됨 | a번 획 끝 → b번 획 끝 직선을 이어 한 획("7"자 ㅈ), b번 획은 지움 |

```python
WRITING_VARIANTS = {
    "ㅈ": {"merge_strokes": (0, 1)},  # 0:ㅡ  1:왼다리  2:오른다리
    "ㅊ": {"horizontal_tick": 0, "merge_strokes": (1, 2)},  # 0:꼭지  1:ㅡ  2:왼다리  3:오른다리
    "ㅎ": {"horizontal_tick": 0},  # 0:꼭지  1:ㅡ  2:ㅇ
}
```

- 방법마다 켜고 끄는 선택지라, 정답 후보 = 표준 모양 + 방법들을 켠 조합 전부입니다 (ㅈ 2개, ㅊ 4개, ㅎ 2개).
- 겹자모 안의 부품에도 적용됩니다 (ㅉ, ㄵ, ㄶ, ㅀ). 예: "짜"는 4개.
- 후보마다 판정해서 **오류가 가장 적은 후보**, 같으면 **짝 비용 합이 가장 작은 후보**를 고릅니다.
  고른 정답은 `judge()` 결과의 `"reference"`에 담겨 균형 판정도 같은 정답을 씁니다.
- 변형 정답은 파일로 저장하지 않고 판정할 때마다 정답 획 사전 값으로 계산합니다 (`writing_variants()`).
- 2획으로 썼으면 strokeNo 등도 2획 기준으로 나옵니다.

## 균형 판정 (`stroke_balance.check`)

넉넉한 기준으로 상자(bbox)만 봅니다. 좌표는 전부 0~1 (칸 = 캔버스 전체).

| 단계 | 항목 (`metric`) | 재는 법 | 기준 (시작값) |
|---|---|---|---|
| 글자 전체 | 크기 `glyph_size` | 전체 상자 높이 ÷ 칸 높이 | 0.5 미만 / 1.0 초과 |
| | 위치 `glyph_offset` | 전체 상자 중심 ↔ 칸 중심 거리 | 칸 크기의 0.2 이상 |
| 자모별 | 위치 `jamo_position` | 자모 상자가 (정답 상자 + 여유) 밖으로 나감 | 여유 = 칸 크기의 0.15 |
| | 크기 `jamo_size` | 자모 상자 대각선 ÷ 정답 상자 대각선 | 0.6 미만 / 1.5 초과 |

- 글자 전체에서 걸리면 자모별은 건너뜁니다 (전체가 치우치면 자모가 전부 벗어나서 피드백이 쏟아짐).
- 학습자 획은 획순 판정 결과의 `strokeMap`으로 자모별로 묶습니다 (`EXTRA` 획은 제외).
- 오류마다 `message`에 학습자에게 보여 줄 문장이 들어갑니다 ("글자를 조금 더 크게 써보세요", "ㅏ를 조금 더 위에 쓰세요" 등).
- 기준 숫자는 `stroke_balance.py` 위쪽 상수(`GLYPH_SIZE`, `GLYPH_OFFSET`, `JAMO_MARGIN`, `JAMO_SIZE`)에서 바꿉니다.

## 번호 규칙 (10/31 초안)

| 필드 | 뜻 | 시작 |
|---|---|---|
| `strokeIndex`, `userIndex` | 학습자 획 순번 | 0부터 |
| `strokeNo` | 해당 자모 안에서 몇 번째 획 | 1부터 |
| `expected`, `actual` | 글자 전체 기준 몇 번째로 써야 했나 / 실제로 썼나 (`EXTRA` 획은 세지 않음) | 1부터 |