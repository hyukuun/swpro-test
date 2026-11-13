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


@dataclass(frozen=True)
class Syllable:
    """음절 하나를 자모로 나눈 결과."""

    cho: str  # 초성 (예: 'ㄷ')
    jung: str  # 중성 (예: 'ㅏ')
    jong: str  # 종성. 없으면 "" (겹받침은 'ㄺ'처럼 그대로)


def is_syllable(ch: str) -> bool:
    """완성형 한글 음절(가~힣)인지."""
    raise NotImplementedError


def is_jamo(ch: str) -> bool:
    """자모 단독(ㄱ~ㅣ)인지. 초보 자모 연습 칸."""
    raise NotImplementedError


def is_punctuation(ch: str) -> bool:
    """콘텐츠에 쓰는 문장부호(? ! . ,)인지."""
    raise NotImplementedError


def decompose(ch: str) -> Syllable:
    """'닭' → Syllable('ㄷ', 'ㅏ', 'ㄺ'). 음절이 아니면 ValueError."""
    raise NotImplementedError


def compose(cho: str, jung: str, jong: str = "") -> str:
    """('ㅌ', 'ㅏ') → '타'. 조합할 수 없으면 ValueError."""
    raise NotImplementedError


def split_compound_jong(jong: str) -> tuple[str, ...]:
    """겹받침을 둘로 나눈다. 'ㄺ' → ('ㄹ', 'ㄱ'), 'ㄱ' → ('ㄱ',), '' → ()."""
    raise NotImplementedError


def has_batchim(text: str) -> bool:
    """마지막 한글 글자에 받침이 있는지 (문장부호는 건너뜀). 조사 고르기용."""
    raise NotImplementedError
