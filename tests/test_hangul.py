"""core/hangul.py: 음절 분해·조합, 겹받침 나누기, 문장부호 구분."""

import pytest

from app.core.hangul import CHO, JONG, JUNG, compose, decompose, is_punctuation, split_compound_jong


@pytest.mark.parametrize(
    "parts, char",
    [
        (("ㅌ", "ㅏ"), "타"),
        (("ㄱ", "ㅏ"), "가"),
        (("ㅎ", "ㅣ", "ㅎ"), "힣"),
        (("ㄷ", "ㅏ", "ㄺ"), "닭"),
        (("ㅅ", "ㅣ", "ㅍ"), "싶"),
        (("ㄸ", "ㅗ", "ㅇ"), "똥"),
        (("ㄷ", "ㅝ", "ㅇ"), "뒁"),
    ],
)
def test_compose(parts, char):
    assert compose(*parts) == char


def test_compose_is_reverse_of_decompose_for_every_syllable():
    """가~힣 11,172자 모두: 나눴다가 다시 조합하면 같은 글자."""
    for code in range(0xAC00, 0xD7A4):
        ch = chr(code)
        s = decompose(ch)
        assert compose(s.cho, s.jung, s.jong) == ch
    assert len(CHO) * len(JUNG) * len(JONG) == 11172


@pytest.mark.parametrize(
    "parts",
    [
        ("ㅏ", "ㄱ"),  # 초성 자리에 모음
        ("ㄺ", "ㅏ"),  # 겹받침은 초성이 될 수 없음
        ("ㄱ", "ㄴ"),  # 중성 자리에 자음
        ("ㄷ", "ㅏ", "ㄸ"),  # ㄸ은 받침이 될 수 없음
        ("ㄷ", "ㅏ", "ㅏ"),  # 종성 자리에 모음
        ("", "ㅏ"),  # 빈 초성
        ("ㄱㄲ", "ㅏ"),  # 여러 글자
        ("ㄱ", "ㅏㅐ"),
        ("ㄱ", "ㅏ", "ㄱㄴ"),
        ("가", "ㅏ"),  # 자모가 아닌 음절
    ],
)
def test_compose_rejects_impossible_parts(parts):
    with pytest.raises(ValueError):
        compose(*parts)


@pytest.mark.parametrize(
    "jong, parts",
    [
        ("ㄺ", ("ㄹ", "ㄱ")),
        ("ㄳ", ("ㄱ", "ㅅ")),
        ("ㄵ", ("ㄴ", "ㅈ")),
        ("ㄶ", ("ㄴ", "ㅎ")),
        ("ㄻ", ("ㄹ", "ㅁ")),
        ("ㄼ", ("ㄹ", "ㅂ")),
        ("ㄽ", ("ㄹ", "ㅅ")),
        ("ㄾ", ("ㄹ", "ㅌ")),
        ("ㄿ", ("ㄹ", "ㅍ")),
        ("ㅀ", ("ㄹ", "ㅎ")),
        ("ㅄ", ("ㅂ", "ㅅ")),
        ("ㄱ", ("ㄱ",)),
        ("ㄲ", ("ㄲ",)),  # 쌍받침은 겹받침이 아님 (한 자음)
        ("ㅆ", ("ㅆ",)),
        ("", ()),
    ],
)
def test_split_compound_jong(jong, parts):
    assert split_compound_jong(jong) == parts


def test_split_compound_jong_parts_make_real_syllables():
    """겹받침을 나눈 자음은 각각 받침으로 쓸 수 있다 (닭 → 달·닥 후보를 만들 수 있음)."""
    for jong in JONG:
        for part in split_compound_jong(jong):
            assert part in JONG
    assert [compose("ㄷ", "ㅏ", p) for p in split_compound_jong("ㄺ")] == ["달", "닥"]


@pytest.mark.parametrize("jong", ["ㄸ", "ㅃ", "ㅉ", "ㅏ", "가", "ㄱㄴ"])
def test_split_compound_jong_rejects_non_jong(jong):
    with pytest.raises(ValueError):
        split_compound_jong(jong)


@pytest.mark.parametrize("ch", ["?", "!", ".", ","])
def test_is_punctuation(ch):
    assert is_punctuation(ch)


@pytest.mark.parametrize("ch", ["가", "ㄱ", "ㅏ", " ", "", "?!", "~", ";", "？"])
def test_is_not_punctuation(ch):
    assert not is_punctuation(ch)
