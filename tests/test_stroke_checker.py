"""정답 획 사전(get_reference)과 획순·균형 판정(check_strokes) 확인.

정답 획 사전(data/extracted/<폰트>/composed_all.json)이 없으면 건너뛴다.
"""

import pytest

from app.core.reference import get_reference, has_reference
from app.core.stroke_vectorizer.compose import composed_path
from app.schemas import Canvas, ErrorType, Role, Stroke
from app.services.stroke_checker import check_strokes, writing_variants

pytestmark = pytest.mark.skipif(
    not composed_path().exists(), reason="정답 획 사전 없음 (python -m app.core.stroke_vectorizer.compose --all)"
)

CANVAS = Canvas(w=300, h=300)


def written_like_reference(char: str) -> list[Stroke]:
    """정답 획을 그대로 따라 쓴 학습자 획 (픽셀, 10ms 간격)"""
    return written_like([s.points for s in get_reference(char)])


def written_like(strokes_points) -> list[Stroke]:
    """0~1 점 목록들 → 그대로 따라 쓴 학습자 획 (픽셀, 10ms 간격)"""
    t = 0.0
    strokes = []
    for pts in strokes_points:
        points = []
        for x, y in pts:
            points.append((x * CANVAS.w, y * CANVAS.h, t, 0.5))
            t += 10
        strokes.append(Stroke(points=points))
    return strokes


def variant(char: str, n_strokes: int, horizontal_first: bool):
    """쓰기 방식 변형 중 획 수와 첫 획 모양(가로 꼭지인지)이 맞는 정답 후보의 점들"""
    for cand in writing_variants([s.model_dump(mode="json") for s in get_reference(char)]):
        first = cand[0]["points"]
        is_horizontal = len(first) == 2 and first[0][1] == first[-1][1]
        if len(cand) == n_strokes and is_horizontal == horizontal_first:
            return [s["points"] for s in cand]
    raise AssertionError(f"{char}: {n_strokes}획 변형 없음")


def test_correct_writing_passes():
    result = check_strokes("가", CANVAS, written_like_reference("가"))
    assert result.passed
    assert result.errors == []
    assert [m.role for m in result.stroke_map] == [Role.CHO, Role.JUNG, Role.JUNG]
    assert result.duration_ms is not None and result.duration_ms > 0


def test_wrong_order_is_reported():
    strokes = written_like_reference("가")[::-1]
    result = check_strokes("가", CANVAS, strokes)
    assert not result.passed
    assert ErrorType.ORDER in {e.type for e in result.errors}


def test_missing_stroke_is_reported():
    strokes = written_like_reference("가")[:-1]
    result = check_strokes("가", CANVAS, strokes)
    missing = [e for e in result.errors if e.type == ErrorType.MISSING]
    assert len(missing) == 1
    assert missing[0].role == Role.JUNG


def test_reference_covers_all_syllables_and_jamo():
    assert has_reference("가") and has_reference("똠")  # 똠: 완성형 2,350자에 없는 글자
    assert has_reference("ㄱ") and has_reference("ㅘ") and has_reference("ㄳ")
    assert not has_reference("A")
    ref = get_reference("뒁")
    assert [s.order for s in ref] == list(range(1, len(ref) + 1))
    assert [(s.jamo, s.stroke_no) for s in ref if s.role == Role.CHO] == [("ㄷ", 1), ("ㄷ", 2)]
    with pytest.raises(KeyError):
        get_reference("A")


def test_jamo_alone_can_be_checked():
    result = check_strokes("ㄱ", CANVAS, written_like_reference("ㄱ"))
    # 획순 오류는 없어야 한다. BALANCE는 보지 않음: 폰트의 자모 단독 ㄱ은 높이가 칸의 0.46이라
    # 글자 크기 기준(0.5~1.0)에 정답 자체가 걸린다 (기준을 자모 단독용으로 정할 때까지)
    assert [e for e in result.errors if e.type != ErrorType.BALANCE] == []
    assert [m.role for m in result.stroke_map] == [Role.CHO]


def test_standard_jieut_still_passes():
    result = check_strokes("자", CANVAS, written_like_reference("자"))
    assert result.passed
    assert len(result.stroke_map) == 5  # ㅈ 3획 + ㅏ 2획


def test_jieut_in_two_strokes_passes():
    # ㅈ을 "7"자처럼 2획으로 (ㅡ+왼다리 / 오른다리) → 자 = 2 + ㅏ 2 = 4획
    result = check_strokes("자", CANVAS, written_like(variant("자", 4, horizontal_first=False)))
    assert result.passed, result.errors
    assert [m.jamo for m in result.stroke_map] == ["ㅈ", "ㅈ", "ㅏ", "ㅏ"]


@pytest.mark.parametrize("char, n_strokes", [("하", 5), ("차", 6), ("차", 5)])
def test_horizontal_tick_passes(char, n_strokes):
    # ㅎ·ㅊ 꼭지를 가로로 (차 5획 = 가로 꼭지 + ㅈ 부분 2획)
    result = check_strokes(char, CANVAS, written_like(variant(char, n_strokes, horizontal_first=True)))
    assert result.passed, result.errors
    assert not any(e.type == ErrorType.DIRECTION for e in result.errors)


def test_variants_cover_compound_jamo():
    # 겹자모 안의 부품에도 적용: ㅉ = ㅈ 2개 → 2 × 2 = 4가지
    cands = writing_variants([s.model_dump(mode="json") for s in get_reference("짜")])
    assert sorted({len(c) for c in cands}) == [6, 7, 8]
    assert len(cands) == 4
