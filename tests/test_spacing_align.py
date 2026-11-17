"""줄 맞춤·띄어쓰기 판정 (services/spacing_align.py)과 인식 결과의 점수 함수 (services/recognizer.py).

인식 결과는 테스트에서 직접 만든다: "이 칸은 '나'를 0.9점으로 인식"처럼.
"""

from app.schemas import ErrorType, Stage
from app.services.recognizer import Candidate, CellKind, Recognition
from app.services.spacing_align import align
from tests.helpers import load_fixture

E = ErrorType


def wrote(i: int, char: str, score: float = 0.95, **others: float) -> Recognition:
    """칸 i에 char를 썼다고 인식 (others: 다른 후보 글자와 점수)."""
    cands = [Candidate(char, score), *(Candidate(c, s) for c, s in others.items())]
    cands.sort(key=lambda c: -c.score)
    return Recognition(cell_index=i, kind=CellKind.CHAR, candidates=cands)


def empty(i: int) -> Recognition:
    return Recognition(cell_index=i, kind=CellKind.EMPTY, candidates=[])


def cells(text: str) -> list[Recognition]:
    """'나너_좋' → 칸마다 그 글자를 썼다고 인식 ('_' = 빈 칸)."""
    return [empty(i) if ch == "_" else wrote(i, ch) for i, ch in enumerate(text)]


def summary(result) -> list[tuple]:
    """alignment를 (정답 자리, 칸 번호, 오류)만 남겨 비교하기 쉽게."""
    return [(a.target_index, a.cell_index, a.error) for a in result.items]


# ----------------------------------------------------------------- 인식 결과 점수 함수


def test_recognition_score_functions():
    rec = wrote(0, "십", 0.88, 싶=0.82, 섭=0.4)
    assert rec.top == Candidate("십", 0.88)
    assert rec.score_of("싶") == 0.82
    assert rec.score_of("가") == 0.0
    assert rec.accepts("십")
    assert rec.accepts("싶")  # 1순위와 0.06 차이 → 인정 (학습자에게 유리하게)
    assert not rec.accepts("섭")
    assert not rec.accepts("가")


def test_scribble_with_low_scores_is_not_accepted():
    rec = Recognition(cell_index=0, kind=CellKind.CHAR, candidates=[Candidate("가", 0.06), Candidate("나", 0.05)])
    assert not rec.accepts("나")
    assert not rec.accepts("가")  # 1순위여도 점수가 너무 낮으면 인정 안 함


def test_empty_cell_is_a_space():
    rec = empty(3)
    assert rec.top is None
    assert rec.score_of(" ") == 1.0 and rec.score_of("가") == 0.0
    assert rec.accepts(" ") and not rec.accepts("가")


# ----------------------------------------------------------------- 초보·중수: 1:1


def test_beginner_one_to_one():
    result = align("바다", Stage.BEGINNER, [wrote(0, "바"), wrote(1, "타", 0.9, 다=0.3)])
    assert summary(result) == [(0, 0, None), (1, 1, E.CHAR_MISMATCH)]
    assert result.expected == {0: "바", 1: "다"}
    assert result.char_correct == {0: True, 1: False}


def test_intermediate_matches_figma_example():
    """피그마 중수 장면: '보고 싶었어'의 싶을 십으로 씀. 띄어쓰기 자리는 칸이 없고 판정하지 않는다."""
    recs = [wrote(0, "보"), wrote(1, "고"), wrote(2, "십", 0.88, 싶=0.1), wrote(3, "었"), wrote(4, "어")]
    result = align("보고 싶었어", Stage.INTERMEDIATE, recs)
    expected = load_fixture("grade_response_intermediate.json")["alignment"]
    assert summary(result) == [(a["targetIndex"], a["cellIndex"], a["error"]) for a in expected]
    assert result.expected[2] == "싶"


# ----------------------------------------------------------------- 고수: 띄어쓰기


def test_advanced_matches_figma_example():
    """피그마 고수 장면: '나 너 좋아하냐?'를 '나너 좋아하냐?'로 씀 (뒤에 빈 칸 3개)."""
    result = align("나 너 좋아하냐?", Stage.ADVANCED, cells("나너_좋아하냐?___"))
    expected = load_fixture("grade_response_advanced.json")["alignment"]
    assert summary(result) == [(a["targetIndex"], a["cellIndex"], a["error"]) for a in expected]
    assert result.ignored_cells == {8, 9, 10}
    assert result.expected[2] == " " and result.expected[8] is None


def test_extra_space():
    result = align("좋아하냐", Stage.ADVANCED, cells("좋아_하냐"))
    assert summary(result) == [(0, 0, None), (1, 1, None), (None, 2, E.EXTRA_SPACE), (2, 3, None), (3, 4, None)]
    assert result.char_correct[2] is True  # 띄어쓰기 오류지 글자 오류는 아님


def test_double_space():
    result = align("나 너", Stage.ADVANCED, cells("나__너"))
    assert summary(result) == [(0, 0, None), (None, 1, E.DOUBLE_SPACE), (1, 2, None), (2, 3, None)]


def test_three_blanks_where_one_space_belongs():
    result = align("나 너", Stage.ADVANCED, cells("나___너"))
    assert [a.error for a in result.items if a.error] == [E.DOUBLE_SPACE, E.DOUBLE_SPACE]


def test_two_blanks_where_no_space_belongs_is_extra_not_double():
    """'나너'(붙여 씀)를 '나  너'로 쓰면 띄어 쓸 곳이 아니니 DOUBLE_SPACE가 아니라 EXTRA_SPACE."""
    result = align("나너", Stage.ADVANCED, cells("나__너"))
    assert [a.error for a in result.items if a.error] == [E.EXTRA_SPACE, E.EXTRA_SPACE]


def test_missing_space_between_every_word():
    result = align("나 너 좋아", Stage.ADVANCED, cells("나너좋아"))
    errors = [(a.target_index, a.error) for a in result.items if a.error]
    assert errors == [(1, E.MISSING_SPACE), (3, E.MISSING_SPACE)]


# ----------------------------------------------------------------- 고수: 글자


def test_missing_char():
    result = align("가나다", Stage.ADVANCED, cells("가다"))
    assert summary(result) == [(0, 0, None), (1, None, E.MISSING_CHAR), (2, 1, None)]


def test_extra_char():
    result = align("가나", Stage.ADVANCED, cells("가라나"))
    assert summary(result) == [(0, 0, None), (None, 1, E.EXTRA_CHAR), (1, 2, None)]
    assert result.expected[1] is None and result.char_correct[1] is False


def test_wrong_char_in_place_is_a_mismatch_not_missing_plus_extra():
    recs = [wrote(0, "가"), wrote(1, "다", 0.9, 나=0.1)]
    result = align("가나", Stage.ADVANCED, recs)
    assert summary(result) == [(0, 0, None), (1, 1, E.CHAR_MISMATCH)]
    assert result.expected[1] == "나" and result.char_correct[1] is False


def test_blank_where_a_char_should_be_is_missing_char():
    """빈 칸은 글자 자리에 맞추지 않는다: '가 다'(가나다에서 나 대신 빈 칸) → 띄어쓰기 추가 + 글자 빠뜨림."""
    result = align("가나다", Stage.ADVANCED, cells("가_다"))
    assert {a.error for a in result.items if a.error} == {E.EXTRA_SPACE, E.MISSING_CHAR}


def mark(i: int) -> Recognition:
    """칸 i에 점·짧은 표시만 있음 (마침표·쉼표 후보)."""
    return Recognition(cell_index=i, kind=CellKind.MARK, candidates=[Candidate(".", 0.6), Candidate(",", 0.3)])


def test_stray_dot_in_a_space_cell_counts_as_the_space():
    """띄어쓰기 칸에 펜이 닿아 점이 찍혀도 띄어 쓴 것으로 본다."""
    result = align("나 너", Stage.ADVANCED, [wrote(0, "나"), mark(1), wrote(2, "너")])
    assert summary(result) == [(0, 0, None), (1, 1, None), (2, 2, None)]


def test_stray_dot_after_the_sentence_is_ignored_with_the_blanks_before_it():
    result = align("나 너", Stage.ADVANCED, [wrote(0, "나"), empty(1), wrote(2, "너"), empty(3), empty(4), mark(5)])
    assert [a.error for a in result.items if a.error] == []
    assert result.ignored_cells == {3, 4, 5}


def test_stray_dot_cell_counts_as_a_blank_cell():
    """점이 찍힌 칸도 비워 둔 칸과 같다: 붙여 쓸 곳에 있으면 띄어쓰기 추가, 빈 칸 옆이면 두 칸 띄움."""
    result = align("가나", Stage.ADVANCED, [wrote(0, "가"), mark(1), wrote(2, "나")])
    assert summary(result) == [(0, 0, None), (None, 1, E.EXTRA_SPACE), (1, 2, None)]
    result = align("나 너", Stage.ADVANCED, [wrote(0, "나"), empty(1), mark(2), wrote(3, "너")])
    assert [a.error for a in result.items if a.error] == [E.DOUBLE_SPACE]


def test_clear_comma_in_a_space_cell_is_a_real_comma():
    """또렷한 쉼표는 실수 점이 아니다: '나 너'를 '나,너'로 쓰면 쉼표를 더 쓰고 띄어쓰기를 빠뜨린 것."""
    comma = Recognition(cell_index=1, kind=CellKind.MARK, candidates=[Candidate(",", 0.95)])
    result = align("나 너", Stage.ADVANCED, [wrote(0, "나"), comma, wrote(2, "너")])
    assert [a.error for a in result.items if a.error] == [E.EXTRA_CHAR, E.MISSING_SPACE]


def test_faint_comma_is_treated_as_a_stray_mark():  # 흐릿하면 실수 점 = 빈 칸 → 띄어쓰기 자리
    faint = Recognition(cell_index=1, kind=CellKind.MARK, candidates=[Candidate(",", 0.2)])
    result = align("나 너", Stage.ADVANCED, [wrote(0, "나"), faint, wrote(2, "너")])
    assert [a.error for a in result.items if a.error] == []


def test_comma_is_matched_to_a_comma():
    comma = Recognition(cell_index=1, kind=CellKind.MARK, candidates=[Candidate(",", 0.95)])
    result = align("나,너", Stage.ADVANCED, [wrote(0, "나"), comma, wrote(2, "너")])
    assert summary(result) == [(0, 0, None), (1, 1, None), (2, 2, None)]


def test_dot_is_matched_to_a_period():
    result = align("나.", Stage.ADVANCED, [wrote(0, "나"), mark(1)])
    assert summary(result) == [(0, 0, None), (1, 1, None)]


def test_stopping_early_leaves_the_rest_missing_and_blanks_ignored():
    result = align("가나다", Stage.ADVANCED, cells("가___"))
    assert summary(result) == [(0, 0, None), (1, None, E.MISSING_CHAR), (2, None, E.MISSING_CHAR)]
    assert result.ignored_cells == {1, 2, 3}


def test_nothing_written_is_all_missing():
    result = align("나 너", Stage.ADVANCED, cells("_____"))
    assert summary(result) == [(0, None, E.MISSING_CHAR), (1, None, E.MISSING_SPACE), (2, None, E.MISSING_CHAR)]
    assert result.ignored_cells == {0, 1, 2, 3, 4}


def test_every_target_position_appears_once_in_order():
    result = align("나 너 좋아하냐?", Stage.ADVANCED, cells("나_너좋아_하냐?"))
    positions = [a.target_index for a in result.items if a.target_index is not None]
    assert positions == list(range(len("나 너 좋아하냐?")))
