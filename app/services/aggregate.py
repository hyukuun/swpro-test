"""[혁윤] D-03 단계별 결과 묶기 (칸/어절/문장).

인식·띄어쓰기 판정·획 판정 결과를 화면에 쓸 모양으로 묶는다.

입출력
- 입력: 요청(req), 인식 결과(recognitions), 정렬 결과(alignment), 칸별 획 판정 결과(strokes)
- 출력: AggregateResult (응답 GradeResponse의 cells·alignment·words·correct·perfect)

규칙 (schemas.Mark 참고)
- 칸 mark: 글자 오류 → char(빨강) / 띄어쓰기 오류 → spacing(빨강) / 획 오류 → stroke(주황) / 맞음 → none
- ORDER·DIRECTION·MISSING·EXTRA는 stroke로 묶는다. BALANCE는 아직 none (디자인 확정 전)
- 오류 위치: 칸 errors엔 글자 오류(CHAR_MISMATCH, EXTRA_CHAR)와 획 오류만. 띄어쓰기·빠뜨린 글자는 alignment에만
- 어절: 그 어절 자리에 글자 오류가 있으면 틀림. 띄어쓰기 오류(누락·추가·두 칸)는 종류와 상관없이
  그 자리 양옆 어절을 모두 틀림으로. 더 쓴 글자는 바로 앞 어절(없으면 뒤 어절)을 틀림으로.
  획 오류는 어절 정답 여부에 넣지 않는다
- correct: 글자 + 띄어쓰기 오류가 하나도 없음
- perfect: correct이고, 획 판정을 해야 하는 칸을 모두 판정했고, 그 칸들이 모두 통과(strokePass true)함.
  균형(BALANCE)만 틀려도 통과가 아니다 (칸 색은 none이어도). 정답 획 데이터가 없어 판정을 못 한 칸이 있어도 아니다
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.schemas import (
    CELL_ERROR_TYPES,
    AlignmentItem,
    Cell,
    CellError,
    CellResult,
    ErrorType,
    GradeRequest,
    Mark,
    WordResult,
)
from app.services.recognizer import CellKind, Recognition
from app.services.spacing_align import AlignmentResult
from app.services.stroke_checker import StrokeCheckResult

CHAR_ERRORS = frozenset({ErrorType.CHAR_MISMATCH, ErrorType.EXTRA_CHAR, ErrorType.MISSING_CHAR})
SPACING_ERRORS = frozenset({ErrorType.MISSING_SPACE, ErrorType.EXTRA_SPACE, ErrorType.DOUBLE_SPACE})
STROKE_MARK_ERRORS = frozenset({ErrorType.ORDER, ErrorType.DIRECTION, ErrorType.MISSING, ErrorType.EXTRA})
HANGUL = re.compile(r"[가-힣ㄱ-ㅣ]")  # 획 판정을 하는 글자: 한글 음절·자모 (문장부호는 하지 않음)


def needs_stroke_check(cell: Cell, alignment: AlignmentResult) -> bool:
    """획 판정을 해야 하는 칸인지: 획이 있고, 한글 정답 글자를 맞게 쓴 칸."""
    expected = alignment.expected.get(cell.index)
    return (
        bool(cell.strokes)
        and expected is not None
        and HANGUL.fullmatch(expected) is not None
        and alignment.char_correct.get(cell.index, False)
    )


@dataclass(frozen=True)
class AggregateResult:
    """응답에 들어갈 판정 결과 묶음."""

    cells: list[CellResult]  # 요청 cells와 같은 순서·개수
    alignment: list[AlignmentItem]  # AlignmentResult.items에 mark를 채운 것
    words: list[WordResult]  # 정답 문장의 어절마다 하나 (중수 빨간 상자)
    correct: bool
    perfect: bool
    # 획 판정을 해야 했지만 하지 못한 칸 (정답 획 데이터가 없거나 사전에 없는 글자)
    unchecked_cells: list[int] = field(default_factory=list)


def aggregate(
    req: GradeRequest,
    recognitions: list[Recognition],
    alignment: AlignmentResult,
    strokes: dict[int, StrokeCheckResult],  # 칸 번호 → 획 판정 결과. 획 검사를 안 한 칸은 없음
) -> AggregateResult:
    """인식·정렬·획 판정 결과를 화면에 쓸 모양으로 묶는다."""
    # 칸 번호 → 그 칸에 붙은 글자·띄어쓰기 오류 (alignment 기준)
    cell_errors: dict[int, list[ErrorType]] = {}
    for item in alignment.items:
        if item.cell_index is not None and item.error is not None:
            cell_errors.setdefault(item.cell_index, []).append(item.error)
    stroke_cells = {i for i, s in strokes.items() if any(e.type in STROKE_MARK_ERRORS for e in s.errors)}

    cells = [
        _cell_result(cell, rec, alignment, cell_errors.get(cell.index, []), strokes.get(cell.index), stroke_cells)
        for cell, rec in zip(req.cells, recognitions, strict=True)
    ]
    items = [item.model_copy(update={"mark": _item_mark(item, stroke_cells)}) for item in alignment.items]
    correct = all(item.error is None for item in items)
    unchecked = [c.index for c in req.cells if needs_stroke_check(c, alignment) and c.index not in strokes]
    return AggregateResult(
        cells=cells,
        alignment=items,
        words=_words(req.target, items),
        correct=correct,
        perfect=correct and not unchecked and all(s.passed for s in strokes.values()),
        unchecked_cells=unchecked,
    )


def _mark(errors: list[ErrorType], stroke_wrong: bool) -> Mark:
    if any(e in CHAR_ERRORS for e in errors):
        return Mark.CHAR
    if any(e in SPACING_ERRORS for e in errors):
        return Mark.SPACING
    return Mark.STROKE if stroke_wrong else Mark.NONE


def _item_mark(item: AlignmentItem, stroke_cells: set[int]) -> Mark:
    """정답 비교 줄의 라벨. 오류가 없으면 그 칸의 획 판정을 따른다."""
    return _mark([item.error] if item.error else [], item.cell_index in stroke_cells)


def _cell_result(
    cell: Cell,
    rec: Recognition,
    alignment: AlignmentResult,
    errors: list[ErrorType],
    stroke: StrokeCheckResult | None,
    stroke_cells: set[int],
) -> CellResult:
    i = cell.index
    top = None if rec.kind == CellKind.EMPTY else rec.top
    return CellResult(
        index=i,
        expected=alignment.expected.get(i),
        recognized=" " if rec.kind == CellKind.EMPTY else (top.char if top else None),
        confidence=top.score if top else None,
        char_correct=alignment.char_correct.get(i, True),
        mark=_mark(errors, i in stroke_cells),
        # 칸에는 글자 오류와 획 오류만 (띄어쓰기·빠뜨린 글자는 alignment에만)
        errors=[CellError(type=e) for e in errors if e in CELL_ERROR_TYPES] + (list(stroke.errors) if stroke else []),
        stroke_pass=stroke.passed if stroke else None,
        stroke_map=list(stroke.stroke_map) if stroke else None,
        duration_ms=stroke.duration_ms if stroke and stroke.duration_ms is not None else _duration_ms(cell),
    )


def _duration_ms(cell: Cell) -> float | None:
    """칸 안 첫 점 ~ 마지막 점 시간. 빈 칸이면 None."""
    times = [p[2] for s in cell.strokes for p in s.points]
    return max(times) - min(times) if times else None


def _words(target: str, items: list[AlignmentItem]) -> list[WordResult]:
    """정답 문장을 공백으로 나눈 어절마다: 그 어절의 칸, 맞음/틀림."""
    texts = target.split(" ")
    word_of: dict[int, int] = {}  # 정답 위치 → 어절 번호 (띄어쓰기 자리는 없음)
    pos = 0
    for w, text in enumerate(texts):
        for k in range(len(text)):
            word_of[pos + k] = w
        pos += len(text) + 1

    # 줄 맞춤 항목마다 바로 앞·뒤 글자 자리의 어절 (띄어쓰기 자리·더 쓴 칸의 양옆을 찾기 위해)
    word_at: list[int | None] = [
        word_of.get(item.target_index) if item.target_index is not None else None for item in items
    ]
    prev_word = nearest_word(word_at)  # 각 항목 바로 앞 글자 자리의 어절
    next_word = nearest_word(word_at[::-1])[::-1]  # 각 항목 바로 뒤 글자 자리의 어절

    cells: list[list[int]] = [[] for _ in texts]
    wrong = [False] * len(texts)

    def mark_wrong(word: int | None) -> None:
        if word is not None:
            wrong[word] = True

    for k, item in enumerate(items):
        here = word_at[k]
        if here is not None:  # 글자 자리
            if item.cell_index is not None:
                cells[here].append(item.cell_index)
            if item.error is not None:
                wrong[here] = True
        elif item.error in SPACING_ERRORS:  # 띄어쓰기 오류 (누락·추가·두 칸): 양옆 어절 모두 틀림
            mark_wrong(prev_word[k])
            mark_wrong(next_word[k])
        elif item.error is not None:  # 더 쓴 글자: 바로 앞 어절, 문장 맨 앞이면 뒤 어절
            mark_wrong(prev_word[k] if prev_word[k] is not None else next_word[k])
    return [WordResult(text=t, cell_indexes=c, correct=not x) for t, c, x in zip(texts, cells, wrong, strict=True)]


def nearest_word(words: list[int | None]) -> list[int | None]:
    """각 위치에서 그 앞(자기 자신 제외)에 마지막으로 나온 어절 번호. 없으면 None.

    더 쓴 칸·띄어쓰기 자리가 어느 어절에 붙는지 정할 때 쓴다. 빨간 어절(여기)과 설명 문장(feedback_templates)이
    같은 어절을 가리키도록 둘 다 이 함수를 쓴다. 뒤 어절은 뒤집어서 부른다: nearest_word(w[::-1])[::-1]
    """
    out: list[int | None] = []
    last: int | None = None
    for word in words:
        out.append(last)
        if word is not None:
            last = word
    return out
