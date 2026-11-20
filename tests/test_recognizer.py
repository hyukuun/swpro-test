"""services/recognizer.py: 칸별 글자 인식.

정답 획과 비교하는 테스트는 정답 획 사전이 있어야 해서, 없으면(CI) 건너뛴다.
빈 칸·점 칸·문장부호(? !)·헷갈리는 글자 목록은 사전 없이 확인한다.
"""

import numpy as np
import pytest

from app.core import reference
from app.schemas import Canvas, Cell, Stroke
from app.services.recognizer import CellKind, confusable_chars, recognize

CANVAS = Canvas(w=300, h=200)  # 가로세로가 다른 칸에서도 0~1 정규화가 맞는지 보려고 일부러 다르게

needs_data = pytest.mark.skipif(
    not reference.reference_available(), reason="정답 획 사전 없음 (python -m app.core.stroke_vectorizer.compose --all)"
)


def cell_of(strokes_points, index: int = 0) -> Cell:
    """0~1 점 목록들 → 칸 하나 (픽셀, 10ms 간격)."""
    t = 0.0
    strokes = []
    for pts in strokes_points:
        points = []
        for x, y in pts:
            points.append((x * CANVAS.w, y * CANVAS.h, t, 0.5))
            t += 10
        strokes.append(Stroke(points=points))
    return Cell(index=index, strokes=strokes)


def reference_points(char: str):
    """정답 획의 점들 (0~1, 쓰는 순서)."""
    return [s.points for s in reference.get_reference(char)]


def handwritten(char: str, seed: int = 0):
    """정답 획을 사람 손글씨처럼 흔든 것: 조금 작게·기울여 쓰고, 획마다 위치가 어긋나고 휘고 떨린다."""
    rng = np.random.default_rng(seed)
    th, shear = np.deg2rad(4), 0.08
    affine = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]]) @ np.array([[0.85, shear], [0, 0.8]])
    out = []
    for pts in reference_points(char):
        p = np.asarray(pts) + rng.normal(0, 0.02, 2)
        p = p + np.outer(np.sin(np.linspace(0, np.pi, len(p))), rng.normal(0, 0.012, 2))
        p = p + rng.normal(0, 0.003, p.shape)
        out.append((p - 0.5) @ affine.T + [0.53, 0.52])
    return out


# ---------------- 사전 없이 ----------------


def test_empty_cell():
    rec = recognize(Cell(index=3, strokes=[]), CANVAS, ["가"])
    assert (rec.cell_index, rec.kind, rec.candidates) == (3, CellKind.EMPTY, [])
    assert rec.accepts(" ") and not rec.accepts("가")


def test_small_dot_is_a_period_when_the_target_has_one():
    rec = recognize(cell_of([[(0.2, 0.8), (0.21, 0.81)]]), CANVAS, ["다", "."])
    assert rec.kind == CellKind.MARK
    assert rec.top is not None and rec.top.char == "."
    assert rec.accepts(".")


def test_short_tail_scores_comma_higher_than_period():
    rec = recognize(cell_of([[(0.2, 0.75), (0.17, 0.9)]]), CANVAS, [".", ","])
    assert rec.kind == CellKind.MARK
    assert [c.char for c in rec.candidates] == [",", "."]


def test_dot_without_punctuation_in_target_has_no_candidates():
    """정답에 . , 가 없으면 후보 없음 → 줄 맞춤이 '실수로 찍은 점'으로 본다."""
    rec = recognize(cell_of([[(0.5, 0.5)]]), CANVAS, ["가", "?"])
    assert rec.kind == CellKind.MARK and rec.candidates == []


def test_question_and_exclamation_marks_without_reference_data():
    question = [[(0.36, 0.3), (0.42, 0.18), (0.52, 0.15), (0.62, 0.22), (0.63, 0.32), (0.52, 0.45), (0.5, 0.6)]]
    question.append([(0.5, 0.8)])
    rec = recognize(cell_of(question), CANVAS, ["?", "!"])
    assert rec.kind == CellKind.CHAR and rec.top is not None and rec.top.char == "?"
    assert rec.accepts("?") and not rec.accepts("!")

    rec = recognize(cell_of([[(0.48, 0.12), (0.5, 0.6)], [(0.5, 0.82)]]), CANVAS, ["?", "!"])
    assert rec.top is not None and rec.top.char == "!"
    assert rec.accepts("!") and not rec.accepts("?")


@pytest.mark.parametrize(
    "char, includes",
    [
        ("다", {"타", "따", "더", "대", "닥", "단"}),  # 초성·중성, 받침 붙이기
        ("싶", {"십", "시"}),  # 받침 비슷한 자음, 받침 빠뜨림
        ("닭", {"달", "닥", "다"}),  # 겹받침 한쪽, 받침 빠뜨림
        ("달", {"닭", "닮", "닳"}),  # 그 자음이 든 겹받침
        ("ㄱ", {"ㅋ", "ㄲ"}),  # 자모 단독
        ("ㅏ", {"ㅓ", "ㅑ", "ㅐ"}),
    ],
)
def test_confusable_chars(char, includes):
    out = confusable_chars(char)
    assert includes <= set(out)
    assert char not in out and len(out) == len(set(out))


def test_confusable_chars_of_non_hangul_is_empty():
    assert confusable_chars("?") == [] and confusable_chars(".") == []


@pytest.mark.parametrize("a, b", [("다", "타"), ("다", "더"), ("싶", "십"), ("바", "파"), ("고", "구"), ("닭", "달")])
def test_confusable_chars_go_both_ways(a, b):
    """다를 쓰고 정답이 타여도, 타를 쓰고 정답이 다여도 서로 후보에 들어가야 다른 글자를 잡는다."""
    assert b in confusable_chars(a) and a in confusable_chars(b)


# ---------------- 정답 획 사전으로 ----------------


@needs_data
@pytest.mark.parametrize("char", ["가", "다", "싶", "닭", "좋", "ㄱ", "ㅏ"])
def test_writing_like_the_reference_is_recognized(char):
    rec = recognize(cell_of(reference_points(char)), CANVAS, [char])
    assert rec.kind == CellKind.CHAR
    assert rec.top is not None and rec.top.char == char and rec.top.score > 0.95
    assert rec.accepts(char)


@needs_data
@pytest.mark.parametrize("char", ["바", "다", "보", "고", "싶", "었", "어", "나", "너", "좋", "아", "하", "냐"])
def test_messy_handwriting_is_still_accepted(char):
    """기울이고 작게 쓰고 획이 조금씩 어긋나도 맞게 쓴 것으로 인정한다 (학습자에게 유리하게)."""
    rec = recognize(cell_of(handwritten(char)), CANVAS, [char])
    assert rec.accepts(char), rec.candidates


@needs_data
@pytest.mark.parametrize(
    "written, target",
    [
        ("십", "싶"),  # 중수 예시: 싶 → 십
        ("싶", "십"),
        ("각", "가"),  # 받침을 더 씀
        ("가", "각"),  # 받침을 빠뜨림
        ("달", "닭"),  # 겹받침 한쪽만
        ("바", "파"),  # 초성
        ("고", "구"),  # 중성
    ],
)
def test_wrong_char_is_not_accepted(written, target):
    rec = recognize(cell_of(handwritten(written)), CANVAS, [target])
    assert rec.top is not None and rec.top.char == written, rec.candidates
    assert not rec.accepts(target)


@needs_data
@pytest.mark.parametrize("written, target", [("타", "다"), ("더", "다")])
def test_close_wrong_char_is_recognized_but_still_accepted(written, target):
    """획 하나·모음 방향만 다른 글자는 1순위로 알아보지만, 점수 차이(약 0.07)가 ACCEPT_MARGIN(0.1)보다 작아
    지금 기준으로는 맞게 쓴 것으로 인정된다 (학습자에게 유리하게). 기준을 바꾸면 이 테스트도 바꾼다."""
    rec = recognize(cell_of(handwritten(written)), CANVAS, [target])
    assert rec.top is not None and rec.top.char == written, rec.candidates
    assert rec.accepts(target)


@needs_data
def test_scribble_is_not_accepted():
    rng = np.random.default_rng(1)
    for _ in range(20):
        scribble = [rng.uniform(0.1, 0.9, (rng.integers(2, 5), 2)) for _ in range(rng.integers(3, 7))]
        rec = recognize(cell_of(scribble), CANVAS, ["가"])
        assert not rec.accepts("가"), rec.candidates


@needs_data
def test_advanced_cell_finds_its_char_among_the_whole_sentence():
    """고수: 정답 문장의 글자 전부가 후보. 쓴 글자가 1순위이고 다른 정답 글자보다 점수가 높다."""
    sentence = ["나", "너", "좋", "아", "하", "냐", "?"]
    rec = recognize(cell_of(handwritten("좋")), CANVAS, sentence)
    assert rec.top is not None and rec.top.char == "좋"
    assert rec.accepts("좋")
    assert all(rec.score_of("좋") > rec.score_of(c) for c in sentence if c != "좋")
    assert len(rec.candidates) <= 5
    assert [c.score for c in rec.candidates] == sorted((c.score for c in rec.candidates), reverse=True)
