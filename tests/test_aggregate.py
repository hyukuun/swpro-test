"""결과 묶기(aggregate): 피그마 예시 요청에 예시와 같은 인식·획 판정 결과를 넣으면, 예시 응답과 같은 결과가 나오는지.

인식 결과와 획 판정 결과는 예시 응답에서 꺼내 주입하고, 띄어쓰기 판정(spacing_align)은 진짜로 돌린다.
"""

import pytest

from app.schemas import CellError, CellResult, GradeRequest, GradeResponse
from app.services import spacing_align
from app.services.aggregate import STROKE_MARK_ERRORS, aggregate
from app.services.recognizer import Candidate, CellKind, Recognition
from app.services.stroke_checker import StrokeCheckResult
from tests.helpers import STAGES, load_fixture

STROKE_TYPES = {t.value for t in STROKE_MARK_ERRORS} | {"BALANCE"}


def _inputs(stage: str):
    req = GradeRequest.model_validate(load_fixture(f"grade_request_{stage}.json"))
    res = GradeResponse.model_validate(load_fixture(f"grade_response_{stage}.json"))
    recognitions = []
    for cell, out in zip(req.cells, res.cells, strict=True):
        if not cell.strokes:
            recognitions.append(Recognition(cell_index=cell.index, kind=CellKind.EMPTY, candidates=[]))
        else:
            cand = [Candidate(char=out.recognized, score=out.confidence or 1.0)] if out.recognized else []
            recognitions.append(Recognition(cell_index=cell.index, kind=CellKind.CHAR, candidates=cand))
    strokes = {
        out.index: StrokeCheckResult(
            passed=out.stroke_pass,
            errors=[e for e in out.errors if e.type.value in STROKE_TYPES],
            stroke_map=out.stroke_map or [],
            duration_ms=out.duration_ms,
        )
        for out in res.cells
        if out.stroke_pass is not None
    }
    return req, res, recognitions, strokes


def _same(cell: CellResult) -> CellResult:
    """duration_ms는 예시 값이 임의라 비교에서 뺀다 (획 판정한 칸은 아래에서 따로 확인)."""
    return cell.model_copy(update={"duration_ms": None})


@pytest.mark.parametrize("stage", STAGES)
def test_aggregate_reproduces_figma_example(stage):
    req, res, recognitions, strokes = _inputs(stage)
    alignment = spacing_align.align(req.target, req.stage, recognitions)
    result = aggregate(req, recognitions, alignment, strokes)

    assert [_same(c) for c in result.cells] == [_same(c) for c in res.cells]
    assert result.alignment == res.alignment
    assert result.words == res.words
    assert (result.correct, result.perfect) == (res.correct, res.perfect)
    for c in result.cells:
        if c.index in strokes:
            assert c.duration_ms == strokes[c.index].duration_ms


def test_cell_errors_never_hold_spacing_or_missing_char():
    """고수 '나너' 붙여 쓰기: 띄어쓰기 오류는 alignment에만, 칸 errors엔 없음."""
    req, _, recognitions, strokes = _inputs("advanced")
    alignment = spacing_align.align(req.target, req.stage, recognitions)
    result = aggregate(req, recognitions, alignment, strokes)
    assert all(
        e.type.value not in {"MISSING_SPACE", "EXTRA_SPACE", "DOUBLE_SPACE", "MISSING_CHAR"}
        for c in result.cells
        for e in c.errors
    )
    assert [a.error for a in result.alignment if a.error] == ["MISSING_SPACE"]


def test_balance_alone_does_not_mark_stroke():
    """균형(BALANCE)만 틀리면 칸 색은 아직 none (디자인 확정 전)."""
    req, _, recognitions, _ = _inputs("beginner")
    balance = CellError(type="BALANCE", metric="glyph_size", value=0.4, range=(0.5, 1.0))
    strokes = {0: StrokeCheckResult(passed=False, errors=[balance])}
    alignment = spacing_align.align(req.target, req.stage, recognitions)
    result = aggregate(req, recognitions, alignment, strokes)
    assert result.cells[0].mark == "none" and result.cells[0].errors == [balance]
    assert result.perfect is True
