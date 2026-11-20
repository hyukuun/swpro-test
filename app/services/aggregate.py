"""[혁윤] D-03 단계별 결과 묶기 (칸/어절/문장).

인식·띄어쓰기 판정·획 판정 결과를 화면에 쓸 모양으로 묶는다.

입출력
- 입력: 요청(req), 인식 결과(recognitions), 정렬 결과(alignment), 칸별 획 판정 결과(strokes)
- 출력: AggregateResult (응답 GradeResponse의 cells·alignment·words·correct·perfect)

규칙 (schemas.Mark 참고)
- 칸 mark: 글자 오류 → char(빨강) / 띄어쓰기 오류 → spacing(빨강) / 획 오류 → stroke(주황) / 맞음 → none
- ORDER·DIRECTION·MISSING·EXTRA는 stroke로 묶는다. BALANCE는 아직 none (디자인 확정 전)
- 오류 위치: 칸 errors엔 글자 오류(CHAR_MISMATCH, EXTRA_CHAR)와 획 오류만. 띄어쓰기·빠뜨린 글자는 alignment에만
- 어절: 그 어절 자리에 글자 오류가 있거나, 어절 옆 띄어쓰기 자리에 오류가 있으면(양옆 어절 모두) 틀림.
  획 오류는 어절 정답 여부에 넣지 않는다
- correct: 글자 + 띄어쓰기 오류가 하나도 없음 / perfect: correct이고 mark가 stroke인 칸도 없음
"""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class AggregateResult:
    """응답에 들어갈 판정 결과 묶음."""

    cells: list[CellResult]  # 요청 cells와 같은 순서·개수
    alignment: list[AlignmentItem]  # AlignmentResult.items에 mark를 채운 것
    words: list[WordResult]  # 정답 문장의 어절마다 하나 (중수 빨간 상자)
    correct: bool
    perfect: bool


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
    return AggregateResult(
        cells=cells,
        alignment=items,
        words=_words(req.target, items),
        correct=correct,
        perfect=correct and not stroke_cells,
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

    cells: list[list[int]] = [[] for _ in texts]
    wrong = [False] * len(texts)
    current = 0  # 지금까지 지나온 마지막 어절
    for item in items:
        t = item.target_index
        if t is not None and t in word_of:  # 글자 자리
            current = word_of[t]
            if item.cell_index is not None:
                cells[current].append(item.cell_index)
            if item.error is not None:
                wrong[current] = True
        elif t is not None:  # 띄어쓰기 자리: 오류면 양옆 어절 모두 틀림
            if item.error is not None:
                wrong[current] = True
                if current + 1 < len(texts):
                    wrong[current + 1] = True
        elif item.error is not None:  # 정답에 없는 칸 (더 쓴 글자·빈 칸)
            wrong[current] = True
    return [WordResult(text=t, cell_indexes=c, correct=not x) for t, c, x in zip(texts, cells, wrong, strict=True)]
