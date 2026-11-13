"""[정진] D-04 획 수·획순·방향 판정 (글자가 맞은 칸만).

TODO: 글자가 맞은 칸의 획 수·획순·방향을 정답 획 데이터와 비교한다

입출력 (정진님 교정 엔진 명세 1·2번과 같은 내용)
- 입력: 정답 글자(target), 칸 크기(canvas), 학습자 획(strokes, 쓴 순서대로, 칸 기준 픽셀 좌표)
- 출력: StrokeCheckResult
    passed      : 명세의 pass. errors가 비었으면 True
    errors      : ORDER / DIRECTION / MISSING / EXTRA / BALANCE (schemas.CellError 형식)
    stroke_map  : 학습자 획 ↔ 정답 획 짝, 학습자 획마다 하나 (schemas.StrokeMapItem 형식)
    duration_ms : 첫 점 ~ 마지막 점 시간(ms)
- role은 cho / jung / jong 으로 쓴다 (명세의 '초성/중성/종성' 대신, schemas.Role).

부르는 조건 (pipeline이 지킨다)
- recognizer가 정답 글자를 맞게 썼다고 인정한 칸만
- target이 한글 음절 또는 자모 단독일 때만 (문장부호·빈 칸은 부르지 않음)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas import Canvas, CellError, Stroke, StrokeMapItem


@dataclass(frozen=True)
class StrokeCheckResult:
    """칸 하나의 획 판정 결과. 응답 CellResult의 strokePass·errors·strokeMap·durationMs로 그대로 들어간다."""

    passed: bool
    errors: list[CellError] = field(default_factory=list)
    stroke_map: list[StrokeMapItem] = field(default_factory=list)
    duration_ms: float | None = None


def check_strokes(target: str, canvas: Canvas, strokes: list[Stroke]) -> StrokeCheckResult:
    """학습자 획을 target의 정답 획(core/reference.py)과 비교한다."""
    raise NotImplementedError
