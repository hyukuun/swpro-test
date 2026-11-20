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
    strokes = {0: StrokeCheckResult(passed=False, errors=[balance]), 1: StrokeCheckResult(passed=True)}
    alignment = spacing_align.align(req.target, req.stage, recognitions)
    result = aggregate(req, recognitions, alignment, strokes)
    assert result.cells[0].mark == "none" and result.cells[0].errors == [balance]
    assert result.perfect is True


# ---------------------------------------------------------------- 경우별 (인식 결과를 직접 만들어 넣음)


def _run(stage: str, target: str, written: list[str], strokes: dict | None = None):
    """written: 칸마다 쓴 글자, ' '는 빈 칸. 인식은 그 글자를 확신도 1로 썼다고 본다."""
    cells = [
        {
            "index": i,
            "strokes": [] if ch == " " else [{"points": [[10, 10, i * 100, 0.5], [80, 80, i * 100 + 50, 0.5]]}],
        }
        for i, ch in enumerate(written)
    ]
    req = GradeRequest.model_validate({"stage": stage, "target": target, "canvas": {"w": 96, "h": 96}, "cells": cells})
    recognitions = [
        Recognition(cell_index=i, kind=CellKind.EMPTY, candidates=[])
        if ch == " "
        else Recognition(cell_index=i, kind=CellKind.CHAR, candidates=[Candidate(char=ch, score=1.0)])
        for i, ch in enumerate(written)
    ]
    alignment = spacing_align.align(req.target, req.stage, recognitions)
    return aggregate(req, recognitions, alignment, strokes or {})


def _errors(result) -> list[str]:
    return [a.error.value for a in result.alignment if a.error]


@pytest.mark.parametrize(
    "target, written, error, words",
    [
        ("나 너", ["나", "너", " "], "MISSING_SPACE", [False, False]),  # 붙여 씀 (고수는 칸이 정답 칸 수 이상)
        ("나 너", ["나", " ", " ", "너"], "DOUBLE_SPACE", [False, False]),  # 두 칸 띄움
        ("좋아해", ["좋", " ", "아", "해"], "EXTRA_SPACE", [False]),  # 붙여 쓸 곳을 띄움
        ("나 너 좋아", ["나", " ", "너", " ", " ", "좋", "아"], "DOUBLE_SPACE", [True, False, False]),
    ],
    ids=["누락", "두 칸", "추가", "가운데 두 칸"],
)
def test_any_spacing_error_marks_both_neighbor_words(target, written, error, words):
    result = _run("advanced", target, written)
    assert _errors(result) == [error]
    assert [w.correct for w in result.words] == words
    assert result.correct is False
    assert all(
        e.type.value not in {"MISSING_SPACE", "EXTRA_SPACE", "DOUBLE_SPACE"} for c in result.cells for e in c.errors
    )


def test_blank_cell_with_spacing_error_is_marked_spacing():
    result = _run("advanced", "좋아해", ["좋", " ", "아", "해"])
    assert result.cells[1].mark == "spacing" and result.cells[1].errors == []


@pytest.mark.parametrize(
    "target, written, words, wrong_cell",
    [
        ("나 너", ["나", " ", "너", "다"], [True, False], 3),  # 맨 뒤에 더 씀 → 앞 어절
        ("나 너", ["다", "나", " ", "너"], [False, True], 0),  # 맨 앞에 더 씀 → 뒤 어절
    ],
    ids=["뒤에 더 씀", "앞에 더 씀"],
)
def test_extra_char_marks_the_nearest_word(target, written, words, wrong_cell):
    result = _run("advanced", target, written)
    assert _errors(result) == ["EXTRA_CHAR"]
    assert [w.correct for w in result.words] == words
    assert result.cells[wrong_cell].mark == "char"
    assert [e.type.value for e in result.cells[wrong_cell].errors] == ["EXTRA_CHAR"]


def test_missing_char_marks_its_word_but_no_cell():
    result = _run("advanced", "좋아해", ["좋", "해", " "])
    assert _errors(result) == ["MISSING_CHAR"]
    assert [w.correct for w in result.words] == [False]
    assert all(c.mark == "none" and c.errors == [] for c in result.cells)


def test_perfect_needs_every_stroke_check_done():
    """획 판정을 해야 하는 칸을 하나라도 못 했으면 perfect가 아님."""
    ok = StrokeCheckResult(passed=True)
    unchecked = _run("beginner", "바다", ["바", "다"])
    assert (unchecked.correct, unchecked.perfect, unchecked.unchecked_cells) == (True, False, [0, 1])
    half = _run("beginner", "바다", ["바", "다"], {0: ok})
    assert (half.perfect, half.unchecked_cells) == (False, [1])
    full = _run("beginner", "바다", ["바", "다"], {0: ok, 1: ok})
    assert (full.perfect, full.unchecked_cells) == (True, [])


def test_punctuation_and_blank_cells_do_not_need_stroke_check():
    ok = StrokeCheckResult(passed=True)
    result = _run("advanced", "나 너?", ["나", " ", "너", "?"], {0: ok, 2: ok})
    assert result.perfect is True and result.unchecked_cells == []
