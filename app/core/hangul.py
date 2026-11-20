"""[혁윤] 한글 음절 분해/조합, 겹받침, 음절 구조 유형 (D-05).

TODO: 한글 음절을 초성·중성·종성으로 나누고 겹받침과 음절 구조 유형을 알려 주는 함수를 만든다

입출력
- 자모는 호환용 자모(ㄱ U+3131 ~ ㅣ U+3163)로 다룬다.
- 받침이 없으면 jong = "" (빈 문자열).

쓰는 곳
- recognizer: 헷갈리는 후보 글자 만들기 (다 → 타·따·더)
- stroke_checker: 글자를 자모로 나눠 정답 획 찾기
- feedback_templates: 받침에 맞는 조사 고르기 ('바다'라고 / '밥'이라고)
"""

from __future__ import annotations

from dataclasses import dataclass

_BASE, _LAST = 0xAC00, 0xD7A3  # 가, 힣
CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
JONG = ("", *"ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ")


@dataclass(frozen=True)
class Syllable:
    """음절 하나를 자모로 나눈 결과."""

    cho: str  # 초성 (예: 'ㄷ')
    jung: str  # 중성 (예: 'ㅏ')
    jong: str  # 종성. 없으면 "" (겹받침은 'ㄺ'처럼 그대로)


def is_syllable(ch: str) -> bool:
    """완성형 한글 음절(가~힣)인지."""
    return len(ch) == 1 and _BASE <= ord(ch) <= _LAST


def is_jamo(ch: str) -> bool:
    """자모 단독(ㄱ~ㅣ)인지. 초보 자모 연습 칸."""
    return len(ch) == 1 and "ㄱ" <= ch <= "ㅣ"


def is_punctuation(ch: str) -> bool:
    """콘텐츠에 쓰는 문장부호(? ! . ,)인지."""
    raise NotImplementedError


def decompose(ch: str) -> Syllable:
    """'닭' → Syllable('ㄷ', 'ㅏ', 'ㄺ'). 음절이 아니면 ValueError."""
    if not is_syllable(ch):
        raise ValueError(f"한글 음절이 아님: {ch!r}")
    code = ord(ch) - _BASE
    return Syllable(CHO[code // 588], JUNG[code // 28 % 21], JONG[code % 28])


def compose(cho: str, jung: str, jong: str = "") -> str:
    """('ㅌ', 'ㅏ') → '타'. 조합할 수 없으면 ValueError."""
    raise NotImplementedError


def split_compound_jong(jong: str) -> tuple[str, ...]:
    """겹받침을 둘로 나눈다. 'ㄺ' → ('ㄹ', 'ㄱ'), 'ㄱ' → ('ㄱ',), '' → ()."""
    raise NotImplementedError


def last_jong(text: str) -> str:
    """마지막 한글 글자의 받침 (문장부호 등은 건너뜀). 없으면 "". 조사 고르기용.

    자모 하나는 이름의 끝소리로 본다: 자음(ㄷ 디귿, ㄹ 리을)은 그 자음, 모음(ㅏ 아)은 "".
    """
    for ch in reversed(text):
        if is_syllable(ch):
            return decompose(ch).jong
        if is_jamo(ch):
            return "" if ch in JUNG else ch
    return ""


def has_batchim(text: str) -> bool:
    """마지막 한글 글자에 받침이 있는지 (문장부호는 건너뜀). 조사 고르기용."""
    return last_jong(text) != ""
