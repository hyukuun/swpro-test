"""[혁윤] D-01 칸별 글자 인식 + D-01b 템플릿 매칭 대체.

TODO: 칸마다 손글씨 획을 보고 무슨 글자를 썼는지 인식한다

입출력
- 입력: 칸 하나(Cell), 칸 크기(Canvas), 이 칸에 올 수 있는 정답 글자들(expected)
- 출력: Recognition (칸 종류 + 점수 높은 순 후보 목록)

방식
- 학습자 획과 정답 획(core/reference.py)을 64×64 그림으로 그려 모양만 비교한다. 획순은 보지 않는다.
- 후보는 expected의 글자 + 각각과 헷갈리는 글자(다 → 타·따·더…)에서만 고른다.

쓰는 곳
- spacing_align: 정렬 비용 = 1 - score_of(정답 글자)
- aggregate: recognized(top), confidence, 글자 맞음(accepts)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.schemas import Canvas, Cell


class CellKind(str, Enum):
    """칸 종류."""

    EMPTY = "EMPTY"  # 획 없음 (= 띄어쓰기 후보)
    MARK = "MARK"  # 점·짧은 표시 (. , 후보). 마침표인지 실수인지는 정렬 단계에서 판단
    CHAR = "CHAR"  # 글자


@dataclass(frozen=True)
class Candidate:
    """인식 후보 하나."""

    char: str  # 글자 하나 (음절, 자모, 문장부호)
    score: float  # 이 글자일 가능성 0~1


@dataclass(frozen=True)
class Recognition:
    """칸 하나의 인식 결과."""

    cell_index: int
    kind: CellKind
    candidates: list[Candidate]  # 점수 높은 순, 최대 5개. EMPTY면 []

    @property
    def top(self) -> Candidate | None:
        """1순위 후보. 응답의 recognized·confidence, '이렇게 쓰셨어요'에 쓴다. EMPTY면 None."""
        raise NotImplementedError

    def score_of(self, char: str) -> float:
        """이 칸이 char일 점수. 후보에 없으면 0. EMPTY 칸은 char == ' '일 때 1."""
        raise NotImplementedError

    def accepts(self, char: str) -> bool:
        """char를 맞게 쓴 것으로 인정할지 (학습자에게 유리하게).

        기준(조정 가능): char가 1순위이거나, 1순위와 점수 차이가 작으면 인정.
        """
        raise NotImplementedError


def recognize(cell: Cell, canvas: Canvas, expected: list[str]) -> Recognition:
    """칸 하나에 무슨 글자를 썼는지 알아낸다.

    expected: 이 칸에 올 수 있는 정답 글자들 (공백 제외)
      - 초보·중수: 그 칸의 정답 글자 하나 (예: ["다"])
      - 고수: 칸이 밀릴 수 있으니 정답 문장의 글자 전부 (예: ["나", "너", "좋", "아", "하", "냐", "?"])
    """
    raise NotImplementedError
