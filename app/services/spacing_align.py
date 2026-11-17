"""[혁윤] D-02 문장 정렬(편집 거리) 및 띄어쓰기 판정.

쓴 칸 배열을 정답 문장과 맞대어 글자·띄어쓰기 오류를 찾는다.

입출력
- 입력: 정답 문장(target), 학습 단계(stage), 칸마다의 인식 결과(recognitions, 칸 번호 순)
- 출력: AlignmentResult

단계별 규칙 (schemas.Stage 참고)
- 초보·중수: 칸 i ↔ 공백을 뺀 정답의 i번째 글자 (1:1). 띄어쓰기 판정 없음
- 고수: 편집 거리 정렬. 비용 = 1 - recognition.score_of(정답 글자)
    띄어쓰기 누락·추가, 빈 칸 2개 연속, 빠뜨린 글자, 더 쓴 글자를 찾는다
    빈 칸은 띄어쓰기 자리에만, 글자를 쓴 칸은 글자 자리에만 맞춘다. 나머지는 더 쓴 칸·빠뜨린 자리로 본다
    점·짧은 표시(MARK) 칸은 문장부호 자리에 맞추거나, 띄어쓰기 자리에서는 빈 칸으로 본다.
    어디에도 맞지 않으면 실수로 찍은 점으로 보고 무시한다 (오류 아님)
    정답을 다 쓴 뒤의 빈 칸·점은 무시한다 (ignored_cells)
        - 띄어쓰기 자리에 칸이 없음         → MISSING_SPACE
        - 정답에 없는 빈 칸                → 이어진 빈 칸 중 하나가 띄어쓰기 자리면 DOUBLE_SPACE, 아니면 EXTRA_SPACE
        - 글자 자리에 칸이 없음             → MISSING_CHAR
        - 정답에 없는 글자 칸               → EXTRA_CHAR
        - 글자 자리에 다른 글자             → CHAR_MISMATCH (recognition.accepts가 False)
    비용이 같은 정렬이 여러 개면 글자끼리 맞춘 쪽 → 빠뜨린 자리 → 더 쓴 칸 순서로 고른다
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas import AlignmentItem, ErrorType, Stage
from app.services.recognizer import CellKind, Recognition

_EPS = 1e-9  # 비용 비교 오차


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
    # 고수: 판정하지 않고 무시한 칸 (다 쓴 뒤 남은 빈 칸·점, 실수로 찍은 점)
    ignored_cells: set[int] = field(default_factory=set)


def align(target: str, stage: Stage, recognitions: list[Recognition]) -> AlignmentResult:
    """쓴 칸 배열을 정답 문장과 맞춘다."""
    if stage == Stage.ADVANCED:
        return _align_advanced(target, recognitions)
    return _align_one_to_one(target, recognitions)


def _align_one_to_one(target: str, recognitions: list[Recognition]) -> AlignmentResult:
    """초보·중수: 칸 i ↔ 공백을 뺀 정답의 i번째 글자. 공백 자리는 칸이 없다 (오류 아님)."""
    items: list[AlignmentItem] = []
    expected: dict[int, str | None] = {}
    char_correct: dict[int, bool] = {}
    c = 0
    for t, ch in enumerate(target):
        if ch == " ":
            items.append(AlignmentItem(target_index=t, target_char=ch, cell_index=None))
            continue
        ok = recognitions[c].accepts(ch)
        expected[c], char_correct[c] = ch, ok
        items.append(
            AlignmentItem(target_index=t, target_char=ch, cell_index=c, error=None if ok else ErrorType.CHAR_MISMATCH)
        )
        c += 1
    return AlignmentResult(items=items, expected=expected, char_correct=char_correct)


def _match_cost(rec: Recognition, ch: str) -> float | None:
    """칸 ↔ 정답 자리 하나를 짝지을 때 비용. 짝지을 수 없으면 None."""
    if ch == " ":  # 띄어쓰기 자리: 빈 칸, 또는 실수로 점이 찍힌 칸
        return 0.0 if rec.kind in (CellKind.EMPTY, CellKind.MARK) else None
    return None if rec.kind == CellKind.EMPTY else 1.0 - rec.score_of(ch)


def _skip_cost(rec: Recognition, done: bool) -> float:
    """칸을 정답에 맞추지 않고 건너뛸 때 비용. done = 정답 자리를 다 맞췄고 이 칸 뒤로 글자 칸이 없음.

    0이면 무시한 칸(오류 아님), 1이면 더 쓴 칸(오류).
    """
    if rec.kind == CellKind.MARK:
        return 0.0  # 실수로 찍은 점
    if rec.kind == CellKind.EMPTY and done:
        return 0.0  # 다 쓴 뒤 남은 빈 칸
    return 1.0


def _align_advanced(target: str, recognitions: list[Recognition]) -> AlignmentResult:
    """고수: 편집 거리 정렬 (칸을 건너뛰면 더 쓴 칸, 정답 자리를 건너뛰면 빠뜨린 자리, 비용 1)."""
    cells = recognitions
    n, m = len(cells), len(target)
    last_char = max((k for k, r in enumerate(cells) if r.kind == CellKind.CHAR), default=-1)

    def done(i: int, j: int) -> bool:
        """i번째 칸(1부터)을 건너뛸 때 '다 쓴 뒤'인지: 정답을 다 맞췄고 뒤에 글자 칸이 없음."""
        return j == m and i - 1 > last_char

    def pair(i: int, j: int) -> float | None:
        """i번째 칸 ↔ j번째 정답 자리(둘 다 1부터) 비용. 마지막 글자 칸 뒤의 칸은 띄어쓰기 자리가 될 수 없다."""
        if target[j - 1] == " " and i - 1 > last_char:
            return None
        return _match_cost(cells[i - 1], target[j - 1])

    # cost[i][j] = 칸 i개와 정답 j자리를 맞춘 최소 비용
    inf = float("inf")
    cost = [[inf] * (m + 1) for _ in range(n + 1)]
    cost[0][0] = 0.0
    for i in range(n + 1):
        for j in range(m + 1):
            if i and j and (mc := pair(i, j)) is not None:
                cost[i][j] = min(cost[i][j], cost[i - 1][j - 1] + mc)
            if j:
                cost[i][j] = min(cost[i][j], cost[i][j - 1] + 1)  # 정답 자리를 빠뜨림
            if i:
                cost[i][j] = min(cost[i][j], cost[i - 1][j] + _skip_cost(cells[i - 1], done(i, j)))  # 칸 건너뜀

    # 뒤에서부터 거슬러 올라가며 짝을 정한다 (같은 비용이면 짝 → 빠뜨림 → 더 씀)
    steps: list[tuple[int | None, int | None]] = []  # (칸 위치, 정답 자리). 건너뛴 칸은 정답 자리 None
    ignored: set[int] = set()
    i, j = n, m
    while i or j:
        mc = pair(i, j) if i and j else None
        if mc is not None and abs(cost[i][j] - (cost[i - 1][j - 1] + mc)) < _EPS:
            steps.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif j and abs(cost[i][j] - (cost[i][j - 1] + 1)) < _EPS:
            steps.append((None, j - 1))
            j -= 1
        elif _skip_cost(cells[i - 1], done(i, j)) == 0:
            ignored.add(cells[i - 1].cell_index)  # 무시한 칸: 결과에 넣지 않음
            i -= 1
        else:
            steps.append((i - 1, None))
            i -= 1
    steps.reverse()
    space_cells = {ci for ci, tj in steps if ci is not None and tj is not None and target[tj] == " "}

    items: list[AlignmentItem] = []
    expected: dict[int, str | None] = {r.cell_index: None for r in recognitions}
    char_correct: dict[int, bool] = {r.cell_index: True for r in recognitions}
    for ci, tj in steps:
        if ci is None:  # 정답 자리에 칸이 없음
            assert tj is not None
            ch = target[tj]
            error = ErrorType.MISSING_SPACE if ch == " " else ErrorType.MISSING_CHAR
            items.append(AlignmentItem(target_index=tj, target_char=ch, cell_index=None, error=error))
        elif tj is None:  # 정답에 없는 칸
            rec = cells[ci]
            if rec.kind == CellKind.EMPTY:
                error = ErrorType.DOUBLE_SPACE if _in_space_run(cells, ci, space_cells) else ErrorType.EXTRA_SPACE
            else:
                error = ErrorType.EXTRA_CHAR
                char_correct[rec.cell_index] = False
            items.append(AlignmentItem(target_index=None, target_char=None, cell_index=rec.cell_index, error=error))
        else:
            rec, ch = cells[ci], target[tj]
            ok = ch == " " or rec.accepts(ch)  # 띄어쓰기 자리는 빈 칸이든 실수 점이든 맞음
            expected[rec.cell_index], char_correct[rec.cell_index] = ch, ok
            items.append(
                AlignmentItem(
                    target_index=tj,
                    target_char=ch,
                    cell_index=rec.cell_index,
                    error=None if ok else ErrorType.CHAR_MISMATCH,
                )
            )
    return AlignmentResult(items=items, expected=expected, char_correct=char_correct, ignored_cells=ignored)


def _in_space_run(cells: list[Recognition], i: int, space_cells: set[int]) -> bool:
    """i번째 빈 칸과 이어진 빈 칸들 중에 띄어쓰기 자리에 맞춘 칸이 있는지 (= 띄어 쓸 곳을 두 칸 이상 띄움)."""
    lo = hi = i
    while lo > 0 and cells[lo - 1].kind == CellKind.EMPTY:
        lo -= 1
    while hi + 1 < len(cells) and cells[hi + 1].kind == CellKind.EMPTY:
        hi += 1
    return any(k in space_cells for k in range(lo, hi + 1))
