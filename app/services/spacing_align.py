"""[혁윤] D-02 문장 정렬(편집 거리) 및 띄어쓰기 판정.

TODO: 쓴 칸 배열을 정답 문장과 맞대어 띄어쓰기 오류와 빠뜨린 글자를 찾는다

입출력
- 입력: 정답 문장(target), 학습 단계(stage), 칸마다의 인식 결과(recognitions, 칸 번호 순)
- 출력: AlignmentResult

단계별 규칙 (schemas.Stage 참고)
- 초보·중수: 칸 i ↔ 공백을 뺀 정답의 i번째 글자 (1:1). 띄어쓰기 판정 없음
- 고수: 편집 거리 정렬. 비용 = 1 - recognition.score_of(정답 글자)
    띄어쓰기 누락·추가, 빈 칸 2개 연속, 빠뜨린 글자, 더 쓴 글자를 찾는다
    마지막 글자를 쓴 칸 뒤의 빈 칸은 무시한다 (ignored_cells)
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas import AlignmentItem, Stage
from app.services.recognizer import Recognition


@dataclass(frozen=True)
class AlignmentResult:
    """정렬 결과."""

    # 응답 alignment로 그대로 나간다. 정답 문장의 모든 자리(공백 포함) + 더 쓴 칸.
    # error는 여기서 채우고(CHAR_MISMATCH, MISSING_SPACE 등), mark는 aggregate가 채운다.
    items: list[AlignmentItem]
    # 칸 번호 → 그 칸의 정답 글자. ' ' = 띄어쓰기 자리, None = 대응하는 정답 없음(더 쓴 칸·무시한 칸)
    expected: dict[int, str | None]
    # 칸 번호 → 글자를 맞게 썼는지 (recognition.accepts 결과). 빈 칸이 띄어쓰기 자리면 True
    char_correct: dict[int, bool]
    # 고수: 마지막 글자 뒤 남은 빈 칸 (판정하지 않음)
    ignored_cells: set[int] = field(default_factory=set)


def align(target: str, stage: Stage, recognitions: list[Recognition]) -> AlignmentResult:
    """쓴 칸 배열을 정답 문장과 맞춘다."""
    raise NotImplementedError
