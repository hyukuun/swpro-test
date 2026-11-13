"""[혁윤] D-09 교정엔진 요청/응답 형식 (스프링부트 ↔ 교정엔진).

- 파이썬 코드에서는 snake_case, JSON에서는 camelCase로 자동 변환됩니다.
  예) cell_index (파이썬) ↔ cellIndex (JSON)
- 필드를 추가/수정할 때는 해당 클래스에 한 줄만 고치면 됩니다.

흐름: Spring Boot ──GradeRequest──▶ POST /grade ──GradeResponse──▶ Spring Boot
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

# =====================================================================
# 요청 검사 기준 (기획서·기능명세 기준). 바꿀 때는 여기 숫자만 고치면 된다.
# =====================================================================

MAX_TARGET_LENGTH = 20  # 정답 문장 최대 칸 수 (띄어쓰기 포함). 콘텐츠 규칙: 고수 문장 최대 20칸
MAX_INTERMEDIATE_WORDS = 3  # 중수: 단어 ~ 어절 2~3개
MAX_CELLS = 30  # 원고지 칸 최대 개수 (세로 화면 한 줄 10칸 × 3줄)

# 정답 문장에 쓸 수 있는 글자: 한글 음절, 자모(초보 자모 연습), 띄어쓰기, 문장부호 ? ! . ,
TARGET_PATTERN = re.compile(r"[가-힣ㄱ-ㅣ ?!.,]+")
JAMO_PATTERN = re.compile(r"[ㄱ-ㅣ]")


class CamelModel(BaseModel):
    """모든 모델의 부모. JSON 필드를 camelCase로 주고받게 해 줍니다."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class RequestModel(CamelModel):
    """요청 모델의 부모. 정해지지 않은 필드가 오면 422로 거절한다 (필드 이름 오타를 조용히 무시하지 않기 위해)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


# =====================================================================
# 공통 값
# =====================================================================


class Stage(str, Enum):
    """학습 단계 (피그마 '따라 쓰기' 화면 기준).

    | 단계 | 칸                                   | 가이드 글자 | 띄어쓰기 판정 |
    |------|--------------------------------------|-------------|---------------|
    | 초보 | 정답 글자 수만큼 (단어 하나 또는 자모 하나) | 회색 있음   | 없음          |
    | 중수 | 어절마다 묶인 칸, 정답 글자 수만큼     | 없음        | 없음 (묶음 사이가 띄어쓰기) |
    | 고수 | 넉넉한 칸, 빈 칸 = 띄어쓰기            | 없음        | 있음          |

    초보·중수: cells 수 = 정답에서 공백을 뺀 글자 수, 칸 i ↔ 공백 뺀 정답의 i번째 글자.
    """

    BEGINNER = "beginner"  # 초보
    INTERMEDIATE = "intermediate"  # 중수
    ADVANCED = "advanced"  # 고수


class Locale(str, Enum):
    KO = "ko"
    EN = "en"


class ErrorType(str, Enum):
    """오류 종류. 새 오류가 생기면 여기에 한 줄 추가.

    어디에 들어오나 (CELL_ERROR_TYPES / ALIGNMENT_ERROR_TYPES):
    - cells[].errors   : 학습자가 글자를 쓴 칸의 오류 → CHAR_MISMATCH, EXTRA_CHAR, 획·균형 오류
    - alignment[].error: 정답 자리 기준 글자·띄어쓰기 오류 → 글자·띄어쓰기 6종 전부
      MISSING_CHAR·MISSING_SPACE는 학습자 칸이 없는 자리라 alignment에만 나온다 (cellIndex = null)
      띄어쓰기 오류 3종은 칸(빈 칸 포함)에 붙이지 않고 alignment에만 둔다. 칸 색은 mark = spacing
    """

    # 글자 (cells[].errors + alignment[].error)
    CHAR_MISMATCH = "CHAR_MISMATCH"  # 다른 글자를 씀
    EXTRA_CHAR = "EXTRA_CHAR"  # (고수) 없는 글자를 더 씀
    # 글자 (alignment[].error 에만)
    MISSING_CHAR = "MISSING_CHAR"  # (고수) 글자를 빠뜨림
    # 띄어쓰기 (고수, alignment[].error 에만)
    MISSING_SPACE = "MISSING_SPACE"  # 띄어야 하는데 붙여 씀
    EXTRA_SPACE = "EXTRA_SPACE"  # 붙여야 하는데 띄어 씀
    DOUBLE_SPACE = "DOUBLE_SPACE"  # 빈 칸 2개 연속
    # 획·균형 (D-04, 글자가 맞은 칸만) — 정진 명세 3번과 이름이 같아야 서버 집계가 맞는다
    ORDER = "ORDER"  # 순서가 틀린 획 (최소한으로 옮겨야 할 획만)
    DIRECTION = "DIRECTION"  # 거꾸로 쓴 획
    MISSING = "MISSING"  # 안 쓴 정답 획
    EXTRA = "EXTRA"  # 어느 정답 획과도 짝이 안 되는 획
    BALANCE = "BALANCE"  # 글자·자모 크기와 위치


# 오류가 들어갈 수 있는 곳 (ErrorType 설명 참고). 테스트가 이 규칙을 확인한다.
CELL_ERROR_TYPES = frozenset(
    {
        ErrorType.CHAR_MISMATCH,
        ErrorType.EXTRA_CHAR,
        ErrorType.ORDER,
        ErrorType.DIRECTION,
        ErrorType.MISSING,
        ErrorType.EXTRA,
        ErrorType.BALANCE,
    }
)
ALIGNMENT_ERROR_TYPES = frozenset(
    {
        ErrorType.CHAR_MISMATCH,
        ErrorType.EXTRA_CHAR,
        ErrorType.MISSING_CHAR,
        ErrorType.MISSING_SPACE,
        ErrorType.EXTRA_SPACE,
        ErrorType.DOUBLE_SPACE,
    }
)


class Mark(str, Enum):
    """화면에 칸을 어떻게 표시할지 (피그마 범례 기준). 프론트는 이 값만 보고 색을 칠한다.

    어떤 오류를 어느 표시로 묶을지는 엔진이 한곳(aggregate)에서 정한다.
    - DIRECTION·MISSING·EXTRA는 ORDER와 같이 STROKE로 묶는다.
    - BALANCE는 아직 표시하지 않는다 (NONE).
    """

    NONE = "none"  # 표시 없음 (맞음)
    CHAR = "char"  # 빨간 상자 — 글자가 달라요
    SPACING = "spacing"  # 빨간 상자 — 띄어 써요
    STROKE = "stroke"  # 주황 상자 — 쓰는 순서가 달라요


class Role(str, Enum):
    """자모의 자리. 정답 데이터와 엔진 출력 모두 영어로 통일."""

    CHO = "cho"  # 초성
    JUNG = "jung"  # 중성
    JONG = "jong"  # 종성


class BalanceMetric(str, Enum):
    """BALANCE 오류의 세부 항목. 글자 전체 항목에서 걸리면 자모 항목은 검사하지 않는다."""

    GLYPH_SIZE = "glyph_size"  # 글자 전체: 상자 높이 ÷ 칸 높이
    GLYPH_OFFSET = "glyph_offset"  # 글자 전체: 상자 중심 ↔ 칸 중심 거리 (dx, dy)
    JAMO_POSITION = "jamo_position"  # 자모: 정답 상자 + 칸의 0.15 밖으로 나간 양 (exceed)
    JAMO_SIZE = "jamo_size"  # 자모: 상자 대각선 ÷ 정답 상자 대각선


Side = Literal["left", "right", "top", "bottom"]


# =====================================================================
# 요청: Spring Boot → 교정엔진
# =====================================================================


# 점 하나 = [x, y, t, p] (정진 명세 1번)
#   x, y : 그 칸의 왼쪽 위를 (0, 0)으로 한 픽셀 좌표. x는 오른쪽, y는 아래로 증가
#   t    : 타임스탬프(ms). 제출 세션 기준이라 칸이 바뀌어도 이어진다 (durationMs 계산용)
#   p    : 필압 0~1. 지원하지 않으면 0.5 고정 (아직 판정에 쓰지 않음)
Point = tuple[float, float, float, float]


class Canvas(RequestModel):
    """원고지 칸 하나의 크기(px). 모든 칸이 같은 크기라고 본다.

    엔진은 x / w, y / h로 좌표를 0~1로 바꿔 정답 획 데이터(0~1)와 비교한다.
    칸 전체 = 정답 글자 프레임(0~1). 가이드 글자도 칸 전체에 맞춰 그린다.
    """

    w: float = Field(gt=0, description="칸 너비(px)")
    h: float = Field(gt=0, description="칸 높이(px)")


class Stroke(RequestModel):
    """획 하나 = 펜을 대고 뗄 때까지 찍힌 점들. 점은 찍힌 순서대로."""

    points: list[Point] = Field(min_length=1, description="[x, y, t, p] 배열의 목록")


class Cell(RequestModel):
    """원고지 칸 하나. 획이 없으면 빈 칸(= 띄어쓰기).

    프론트가 지키는 규칙:
    - 획은 펜을 댄 칸에 속한다. 칸 경계를 넘어가도 시작한 칸에 넣는다.
    - 좌표는 그 칸의 왼쪽 위 기준 픽셀 (Point 설명 참고).
    - strokes는 학습자가 쓴 순서대로 담는다. 획순(ORDER) 판정이 이 순서를 그대로 쓴다.
    - '한 획 지우기'·'칸 지우기'로 지운 획은 빼고, 제출 시점에 남아 있는 획만 보낸다.
    - 고수: 마지막으로 글자를 쓴 칸 뒤의 빈 칸은 엔진이 무시한다 (띄어쓰기 오류로 보지 않음).
    - 초보·중수: 칸 수가 정답 글자 수(공백 제외)와 같아야 한다 (Stage 설명 참고).
    """

    index: int = Field(ge=0, description="0부터 시작하는 칸 번호 (왼쪽→오른쪽, 위→아래)")
    strokes: list[Stroke] = Field(default_factory=list, description="쓴 순서대로. 빈 칸이면 []")


class GradeRequest(RequestModel):
    """판정 요청 (제출할 때 한 번). 단어 하나만 쓰는 초보도 같은 형식.

    검사 규칙 (어기면 422, 기준 숫자는 파일 맨 위 MAX_* 상수):
    - target: 한글 음절·자모·띄어쓰기·? ! . , 만, 1~20칸, 앞뒤 공백·연속 공백 없음
        초보: 띄어쓰기 없음 (단어 하나 또는 자모 하나). 자모는 초보에서 한 글자만
        중수: 어절 3개 이하
    - cells: index가 0부터 빠짐없이 순서대로, 최대 30칸
        초보·중수: 칸 수 = 정답 글자 수(공백 제외)
        고수: 칸 수 ≥ 정답 칸 수(띄어쓰기 포함)
    - 획이 하나도 없는 제출도 받는다 (판정 결과: 모든 칸 틀림)
    """

    session_id: str | None = Field(default=None, max_length=100, description="스프링부트 쪽 쓰기 세션 ID (로그용)")
    stage: Stage
    target: str = Field(description="정답 문장. 이 단계에서 써야 하는 텍스트 (예: '나 너 좋아하냐?')")
    locale: Locale = Locale.KO
    canvas: Canvas = Field(description="칸 하나의 크기(px)")
    cells: list[Cell] = Field(min_length=1, max_length=MAX_CELLS)

    @field_validator("target")
    @classmethod
    def _check_target(cls, target: str) -> str:
        if not target or len(target) > MAX_TARGET_LENGTH:
            raise ValueError(f"정답 문장은 1~{MAX_TARGET_LENGTH}칸(띄어쓰기 포함)이어야 해요")
        if not TARGET_PATTERN.fullmatch(target):
            raise ValueError("정답 문장에는 한글, 띄어쓰기, 문장부호 ? ! . , 만 쓸 수 있어요")
        if target != target.strip() or "  " in target:
            raise ValueError("정답 문장의 앞뒤 공백이나 연속 공백은 안 돼요")
        return target

    @model_validator(mode="after")
    def _check_stage_rules(self) -> GradeRequest:
        target, stage, cells = self.target, self.stage, self.cells

        # 단계별 정답 문장 규칙
        has_jamo = bool(JAMO_PATTERN.search(target))
        if has_jamo and (stage != Stage.BEGINNER or len(target) != 1):
            raise ValueError("자모 단독(ㄱ, ㅏ 등)은 초보 단계에서 한 글자만 쓸 수 있어요")
        if stage == Stage.BEGINNER and " " in target:
            raise ValueError("초보는 띄어쓰기 없는 단어 하나(또는 자모 하나)만 써요")
        if stage == Stage.INTERMEDIATE and len(target.split(" ")) > MAX_INTERMEDIATE_WORDS:
            raise ValueError(f"중수는 어절 {MAX_INTERMEDIATE_WORDS}개 이하만 써요")

        # 칸 번호
        for expected_index, cell in enumerate(cells):
            if cell.index != expected_index:
                raise ValueError(
                    f"cells의 index는 0부터 빠짐없이 순서대로 와야 해요 ({expected_index}번 자리에 {cell.index})"
                )

        # 칸 수
        if stage == Stage.ADVANCED:
            if len(cells) < len(target):
                raise ValueError(
                    f"advanced: 칸 {len(cells)}개로는 정답 {len(target)}칸(띄어쓰기 포함)을 다 쓸 수 없어요"
                )
        else:
            need = len(target.replace(" ", ""))
            if len(cells) != need:
                raise ValueError(f"{stage.value}: 칸 {len(cells)}개, 정답 글자 수 {need}개와 달라요")

        return self


# =====================================================================
# 응답: 교정엔진 → Spring Boot
# =====================================================================


class CellError(CamelModel):
    """칸 하나에 붙는 오류 (글자 오류 + 획·균형 오류). 정진 명세 2번 `errors[]` 항목과 같은 모양.

    들어오는 종류: CELL_ERROR_TYPES (CHAR_MISMATCH, EXTRA_CHAR, 획·균형 오류).
    빠뜨린 글자·띄어쓰기 오류는 여기 오지 않고 alignment[].error에만 온다.

    오류 종류마다 쓰는 필드만 채우고 나머지는 null로 온다 (필드 자체는 응답에 있음).
    - ORDER      : jamo, role, strokeIndex, expected, actual
    - DIRECTION  : jamo, role, strokeIndex
    - MISSING    : jamo, role, strokeNo        (strokeIndex 없음)
    - EXTRA      : strokeIndex                 (jamo, role 없음)
    - BALANCE    : metric, value, range, message (+ exceed 또는 dx·dy). 글자 전체 항목은 jamo, role 없음
    - 글자 오류(CHAR_MISMATCH 등): type만
    서버 숙련도 집계 기준 = type + jamo + role
    """

    type: ErrorType
    jamo: str | None = Field(default=None, description="오류가 난 자모 (예: 'ㄱ'). EXTRA·글자 전체 BALANCE는 null")
    role: Role | None = Field(default=None, description="자모의 자리 cho | jung | jong")
    stroke_index: int | None = Field(
        default=None, ge=0, description="학습자가 쓴 획 순번, 0부터. 프론트가 이 획을 빨갛게 표시"
    )
    stroke_no: int | None = Field(default=None, ge=1, description="MISSING: 그 자모 안에서 몇 번째 획, 1부터")
    expected: int | None = Field(default=None, ge=1, description="ORDER: 글자 전체 기준 써야 했던 순번, 1부터")
    actual: int | None = Field(
        default=None, ge=1, description="ORDER: 글자 전체 기준 실제로 쓴 순번, 1부터 (EXTRA 획은 세지 않음)"
    )
    # BALANCE 전용
    metric: BalanceMetric | None = None
    value: float | None = Field(default=None, description="BALANCE: 실제로 잰 값")
    range: tuple[float, float] | None = Field(default=None, description="BALANCE: 정상 범위 [최소, 최대]")
    exceed: dict[Side, float] | None = Field(default=None, description="jamo_position: 나간 쪽과 양 (칸 대비 비율)")
    dx: float | None = Field(default=None, description="glyph_offset: + 오른쪽으로 치우침")
    dy: float | None = Field(default=None, description="glyph_offset: + 아래쪽으로 치우침")
    message: str | None = Field(default=None, description="바로 보여 줄 기본 문장 (지금은 BALANCE만)")


class StrokeMapItem(CamelModel):
    """학습자 획 하나 ↔ 정답 획 짝 (정진 명세 2번 strokeMap). 학습자 획마다 하나.

    'ㄷ 쓰는 순서' 화면에서 내가 쓴 획에 번호를 붙이고, 정답 리플레이와 나란히 보여 줄 때 쓴다.
    짝이 없는 획(EXTRA)은 jamo·role·strokeNo가 null.
    """

    user_index: int = Field(ge=0, description="학습자가 쓴 획 순번, 0부터")
    jamo: str | None = None
    role: Role | None = None
    stroke_no: int | None = Field(default=None, ge=1, description="그 자모 안에서 몇 번째 획, 1부터")


class CellResult(CamelModel):
    """학습자가 쓴 칸별 결과. '결과' 화면은 이 순서(쓴 칸 순서) 그대로 그린다."""

    index: int
    expected: str | None = Field(description="이 칸의 정답 글자. 정답에 없는 칸이면 null")
    recognized: str | None = Field(description="인식한 글자. 빈 칸은 ' ', 알 수 없으면 null")
    confidence: float | None = Field(default=None, description="인식 확신도 0~1")
    char_correct: bool
    mark: Mark = Field(default=Mark.NONE, description="결과 화면의 상자 색 (빨강 char / 주황 stroke)")
    errors: list[CellError] = Field(default_factory=list)
    # 획 판정 결과 (정진 명세 2번). 글자가 틀렸거나 빈 칸·문장부호라 검사하지 않았으면 null
    stroke_pass: bool | None = Field(default=None, description="정진 명세의 pass. 획 오류가 없으면 true")
    stroke_map: list[StrokeMapItem] | None = None
    duration_ms: float | None = Field(default=None, description="이 칸 첫 점 ~ 마지막 점 시간(ms)")


class AlignmentItem(CamelModel):
    """'정답 비교' 화면용 줄 맞춤 한 칸 (D-02 정렬 결과).

    위 줄(내가 쓴 글)과 아래 줄(정답)을 같은 칸끼리 맞춰 그린다.
    - 정답에 있는데 안 쓴 자리(빠뜨린 글자·띄어쓰기): cellIndex = null → 위 줄에 빈 칸을 끼워 넣는다
    - 정답에 없는데 더 쓴 칸: targetIndex = null → 아래 줄에 빈 칸을 끼워 넣는다
    """

    target_index: int | None = Field(description="정답 문장 기준 위치 (공백 포함). 더 쓴 칸이면 null")
    target_char: str | None = Field(description="정답 글자. 띄어쓰기 자리는 ' ', 더 쓴 칸이면 null")
    cell_index: int | None = Field(description="학습자가 쓴 칸 번호. 안 쓴 자리면 null")
    mark: Mark = Field(default=Mark.NONE, description="이 칸 아래 라벨: 글자 / 띄어쓰기 / 획순")
    error: ErrorType | None = Field(
        default=None,
        description="글자·띄어쓰기 오류 (ALIGNMENT_ERROR_TYPES). 빠뜨린 글자·띄어쓰기는 여기에만 온다. 맞으면 null",
    )


class Explanation(CamelModel):
    """'이렇게 고쳐요' 한 줄 (E-03).

    화면: [내 손글씨 십었어] 라고 쓰셨는데 [싶었어] 라고 써야 해요.
    - 손글씨 부분은 cellIndexes 칸의 획을 프론트가 그대로 그린다.
    - text는 따옴표 없는 완성 문장이다 (예: '십었어라고 쓰셨는데 싶었어라고 써야 해요.').
      강조할 부분은 text 안에 표시하지 않고 wrong·right 필드로 따로 준다.
    - kind = stroke이면 char·jamo로 '‘다’ 쓰는 순서만 크게 보기' 화면을 연다.
    """

    kind: Mark = Field(description="char | spacing | stroke")
    cell_indexes: list[int] = Field(default_factory=list, description="손글씨로 보여 줄 학습자 칸")
    wrong: str | None = Field(default=None, description="학습자가 쓴 텍스트 (예: '십었어', '나너')")
    right: str = Field(description="맞는 텍스트 (예: '싶었어', '나 너', 획순이면 '다')")
    jamo: str | None = Field(default=None, description="stroke: 순서가 틀린 자모 (예: 'ㄷ')")
    text: str = Field(description="화면에 보여 줄 완성 문장, 따옴표 없음 (locale 언어)")


class WordResult(CamelModel):
    """어절별 결과. 중수 '결과' 화면에서 틀린 어절 전체에 빨간 상자를 그린다."""

    text: str
    cell_indexes: list[int]
    correct: bool


class SejongMessage(CamelModel):
    """킹세종 말풍선 (결과 화면 위쪽)."""

    text: str = Field(description="굵은 첫 줄 (예: '아쉬워요, 한 어절이 달라요')")
    sub_text: str | None = Field(
        default=None, description="둘째 줄 (예: '빨간 상자 안에서 어느 글자가 다른지 찾아볼까요?')"
    )
    expression: str = Field(description="default | praise | regret | encourage")
    source: str = Field(default="template", description="template | llm")


class GradeResponse(CamelModel):
    """판정 결과.

    화면별로 쓰는 필드:
    - 결과(초보)    : cells[].mark (빨강·주황 상자), sejong
    - 결과(중수)    : words (틀린 어절 빨간 상자), sejong
    - 결과(고수)    : correct만 (상자 없음), sejong
    - 정답 비교     : alignment (두 줄 맞춤 + 라벨), explanations, cells[].strokeMap (리플레이)
    - 쓰기 기록     : correct, perfect, 획순 오류 칸 수 (= cells 중 mark가 stroke인 칸)
    - 숙련도(서버)  : cells[].errors 의 type + jamo + role
    """

    session_id: str | None = Field(default=None, description="요청의 sessionId를 그대로 돌려준다 (로그 맞추기용)")
    engine_version: str
    stage: Stage
    correct: bool = Field(description="글자 + 띄어쓰기가 모두 맞음 (획 제외)")
    perfect: bool = Field(description="correct이고 mark가 stroke인 칸도 없음.")
    cells: list[CellResult]
    alignment: list[AlignmentItem] = Field(default_factory=list)
    words: list[WordResult] = Field(default_factory=list)
    explanations: list[Explanation] = Field(default_factory=list)
    sejong: SejongMessage


# =====================================================================
# 오류 응답: 교정엔진 → Spring Boot (판정하지 못했을 때)
# 모든 오류는 HTTP 상태 코드와 상관없이 이 한 가지 모양으로 돌려준다. (app/errors.py)
# =====================================================================


class ErrorCode(str, Enum):
    """오류 종류. HTTP 상태 코드와 1:1로 대응한다. 스프링부트는 이 값으로 분기하면 된다."""

    INVALID_JSON = "INVALID_JSON"  # 400: 본문이 JSON이 아님 (괄호·따옴표 등 문법 오류)
    INVALID_REQUEST = "INVALID_REQUEST"  # 422: JSON은 맞지만 요청 검사 규칙을 어김
    NOT_FOUND = "NOT_FOUND"  # 404: 없는 주소
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"  # 405: 주소는 있는데 GET/POST가 다름
    INTERNAL_ERROR = "INTERNAL_ERROR"  # 500: 엔진 내부 오류 (다시 시도해 볼 수 있음)


class ErrorDetail(CamelModel):
    """어느 값이 왜 틀렸는지 하나."""

    field: str | None = Field(
        default=None, description="틀린 값의 위치 (예: 'cells[0].strokes[1].points'). 요청 전체 규칙이면 null"
    )
    message: str = Field(description="이유 (예: '정답 문장에는 한글, 띄어쓰기, 문장부호 ? ! . , 만 쓸 수 있어요')")


class ErrorResponse(CamelModel):
    """오류 응답. 성공(200)이 아니면 항상 이 모양이다."""

    code: ErrorCode
    message: str = Field(description="사람이 읽을 요약 한 줄")
    details: list[ErrorDetail] = Field(default_factory=list, description="INVALID_REQUEST일 때 틀린 값 목록")
    engine_version: str


# =====================================================================
# 정답 획 데이터 (엔진 안쪽: core/reference.py가 돌려주는 모양)
# =====================================================================


class ReferenceStroke(CamelModel):
    """정답 획 하나 (정진 명세 5번 compose() 출력과 같은 모양)."""

    order: int = Field(ge=1, description="글자 전체 기준 획 번호, 1부터 = 쓰는 순서")
    jamo: str
    role: Role
    stroke_no: int = Field(ge=1, description="그 자모 안에서 몇 번째 획, 1부터")
    points: list[tuple[float, float]] = Field(description="획 중심선 [x, y] 0~1, 쓰는 방향 순서")
    description: str | None = Field(default=None, description="획 설명 (예: '위 가로획을 왼쪽에서 오른쪽으로')")


# =====================================================================
# 상태 확인: GET /health
# =====================================================================


class HealthResponse(CamelModel):
    """엔진이 살아 있는지. 스프링부트는 engineVersion이 '-stub'으로 끝나면 임시 응답 중임을 알 수 있다."""

    status: Literal["ok"] = "ok"
    engine_version: str
