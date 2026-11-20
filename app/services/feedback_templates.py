"""[혁윤] E-03·E-06 오답 설명 문장, 킹세종 말풍선 템플릿.

틀린 곳을 정리해서 "바타라고 쓰셨는데 바다라고 써야 해요." 같은 설명 문장과 킹세종 말풍선을 만든다.
LLM 없이 항상 만들 수 있는 문장이라, LLM이 실패하거나 꺼져 있어도 화면은 이 문장으로 돌아간다.

입출력
- 입력: 요청(req, locale 포함), 묶은 결과(AggregateResult)
- 출력:
    explanations  → list[Explanation]  ('이렇게 고쳐요' 화면, 틀린 곳마다 한 줄, 문장 앞쪽부터)
    sejong_message → SejongMessage     (결과 화면 위 킹세종 말풍선, source = template)

틀린 곳 정리 (한 곳 = 한 줄)
- 글자: 글자 오류(다른 글자·빠뜨림·더 씀)가 있는 어절 하나. 더 쓴 글자는 바로 앞 어절(없으면 뒤 어절)에 붙인다
- 띄어쓰기: 띄어쓰기 오류 양옆 어절. 어절이 겹치는 오류는 한 줄로 합친다 ('나너좋아' → 나 너 좋아)
- 획순: 획순 오류(주황)가 있는 칸 하나. 균형(BALANCE)은 디자인 확정 전이라 아직 문장 없음

문장 형식 (tests/fixtures/grade_response_*.json의 피그마 예시와 같게)
- text에는 따옴표를 넣지 않는다. 강조는 Explanation.wrong·right 필드로 따로 준다.
- 글자:     십었어라고 쓰셨는데 싶었어라고 써야 해요.      (wrong=십었어, right=싶었어)
- 띄어쓰기: 나너는 나 너로 띄어 써요.                      (wrong=나너, right=나 너)
- 획순:     다의 ㄷ은 쓰는 순서가 달라요.                  (right=다, jamo=ㄷ)
    피그마처럼 '위 가로획을 먼저 쓰고…'로 자세히 쓰려면 자모마다 쓰는 법 설명이 있어야 한다 (나중에)
- 조사(라고/이라고, 는/은, 로/으로, 를/을)는 받침에 맞춘다 (core/hangul.last_jong).
"""

from __future__ import annotations

from app.core.hangul import last_jong
from app.schemas import ErrorType, Explanation, GradeRequest, Mark, SejongMessage
from app.services.aggregate import CHAR_ERRORS, SPACING_ERRORS, STROKE_MARK_ERRORS, AggregateResult

E = ErrorType
STROKE_PRIORITY = [E.ORDER, E.DIRECTION, E.MISSING, E.EXTRA]  # 한 칸에 획 오류가 여럿이면 앞의 것으로 설명


def explanations(req: GradeRequest, result: AggregateResult) -> list[Explanation]:
    """정답 공개 화면의 설명 문장 목록. 모두 맞으면 []."""
    en = req.locale == "en"
    texts = req.target.split(" ")
    items = result.alignment

    # 줄 맞춤 항목마다 어절: 글자 자리는 그 어절, 나머지(띄어쓰기 자리·더 쓴 칸)는 바로 앞·뒤 어절
    word_of: dict[int, int] = {}
    pos = 0
    for w, text in enumerate(texts):
        for k in range(len(text)):
            word_of[pos + k] = w
        pos += len(text) + 1
    here = [word_of.get(it.target_index) if it.target_index is not None else None for it in items]
    prev, nxt = _nearest(here), _nearest(here[::-1])[::-1]

    def owner(k: int) -> int | None:
        """항목 k가 속한 어절 (더 쓴 칸은 앞 어절, 문장 맨 앞이면 뒤 어절)."""
        return next((w for w in (here[k], prev[k], nxt[k]) if w is not None), None)

    blank = {it.cell_index for it in items if it.error in SPACING_ERRORS or it.target_char == " "}
    word_cells: dict[int, list[int]] = {}  # 어절 → 그 어절의 칸 (더 쓴 글자 칸 포함, 빈 칸 제외)
    for k, it in enumerate(items):
        if it.cell_index is not None and it.cell_index not in blank and (ow := owner(k)) is not None:
            word_cells.setdefault(ow, []).append(it.cell_index)
    order = sorted(c.index for c in result.cells)
    shown = {c.index: c.recognized for c in result.cells}

    def span(cells: list[int]) -> list[int]:
        """cells의 처음~끝 사이 모든 칸 (사이의 빈 칸 포함)."""
        return [i for i in order if min(cells) <= i <= max(cells)] if cells else []

    def written(cells: list[int]) -> str:
        """학습자가 그 칸들에 쓴 글. 빈 칸은 공백, 알아보지 못한 칸은 ?."""
        return "".join(" " if i in blank else (shown[i] or "?") for i in cells).strip()

    lines: list[tuple[int, Explanation]] = []  # (줄 맞춤 위치, 문장): 문장 앞쪽부터 보여 주려고

    # 글자: 글자 오류가 있는 어절마다 한 줄
    char_words: dict[int, int] = {}
    for k, it in enumerate(items):
        if it.error in CHAR_ERRORS and (ow := owner(k)) is not None:
            char_words.setdefault(ow, k)
    for w, k in char_words.items():
        cells = span(word_cells.get(w, []))
        lines.append((k, _char_line(cells, written(cells), texts[w], en)))

    # 띄어쓰기: 오류 양옆 어절. 앞 오류와 어절이 겹치면 한 줄로 합친다
    spots: list[tuple[int, int, set[ErrorType], int, list[int]]] = []  # (첫 어절, 끝 어절, 오류들, 위치, 빈 칸)
    for k, it in enumerate(items):
        if it.error not in SPACING_ERRORS:
            continue
        a = prev[k] if prev[k] is not None else nxt[k]
        b = nxt[k] if nxt[k] is not None else prev[k]
        if a is None or b is None:
            continue
        extra = [it.cell_index] if it.cell_index is not None else []
        if spots and spots[-1][1] >= a:
            first, last, kinds, at, blanks = spots[-1]
            spots[-1] = (first, max(b, last), kinds | {it.error}, at, blanks + extra)
        else:
            spots.append((a, b, {it.error}, k, extra))
    for a, b, kinds, k, blanks in spots:
        cells = span([c for w in range(a, b + 1) for c in word_cells.get(w, [])] + blanks)
        lines.append((k, _spacing_line(cells, written(cells), " ".join(texts[a : b + 1]), kinds, en)))

    # 획순: 주황 칸마다 한 줄
    at_of = {it.cell_index: k for k, it in enumerate(items) if it.cell_index is not None}
    for c in result.cells:
        errs = [e for e in c.errors if e.type in STROKE_MARK_ERRORS]
        if c.mark != Mark.STROKE or not errs or c.expected is None:
            continue
        e = min(errs, key=lambda e: STROKE_PRIORITY.index(e.type))
        lines.append((at_of.get(c.index, len(items)), _stroke_line(c.index, c.expected, e.type, e.jamo, en)))

    return [line for _, line in sorted(lines, key=lambda x: x[0])]


def _char_line(cells: list[int], wrong: str, right: str, en: bool) -> Explanation:
    if not wrong:  # 어절을 통째로 빠뜨림
        text = f"You left out {right}." if en else f"{right}{_eul(right)} 빠뜨렸어요."
        return Explanation(kind=Mark.CHAR, cell_indexes=cells, wrong=None, right=right, text=text)
    if en:
        text = f"You wrote {wrong}, but it should be {right}."
    else:
        text = f"{wrong}{_rago(wrong)} 쓰셨는데 {right}{_rago(right)} 써야 해요."
    return Explanation(kind=Mark.CHAR, cell_indexes=cells, wrong=wrong, right=right, text=text)


_SPACING_HOW = {
    # 오류 종류: (한국어, 영어)
    E.MISSING_SPACE: ("띄어 써요", " with a space"),
    E.EXTRA_SPACE: ("붙여 써요", " without a space"),
    E.DOUBLE_SPACE: ("한 칸만 띄어 써요", " with just one space"),
}


def _spacing_line(cells: list[int], wrong: str, right: str, kinds: set[ErrorType], en: bool) -> Explanation:
    ko_how, en_how = _SPACING_HOW[next(iter(kinds))] if len(kinds) == 1 else ("써요", "")  # 여러 종류면 그냥 '써요'
    text = f"Write {wrong} as {right}{en_how}." if en else f"{wrong}{_eun(wrong)} {right}{_euro(right)} {ko_how}."
    return Explanation(kind=Mark.SPACING, cell_indexes=cells, wrong=wrong or None, right=right, text=text)


_STROKE_HOW = {
    # 오류 종류: (한국어, 영어). {c} 글자, {j} 자모, {p} 자모 뒤 조사(은/는)
    E.ORDER: ("{c}의 {j}{p} 쓰는 순서가 달라요.", "In {c}, check the stroke order of {j}."),
    E.DIRECTION: ("{c}의 {j}{p} 쓰는 방향이 거꾸로예요.", "In {c}, a stroke of {j} goes the wrong way."),
    E.MISSING: ("{c}의 {j}에 빠진 획이 있어요.", "In {c}, {j} is missing a stroke."),
    E.EXTRA: ("{c}에 더 쓴 획이 있어요.", "{c} has an extra stroke."),
}


def _stroke_line(cell: int, char: str, kind: ErrorType, jamo: str | None, en: bool) -> Explanation:
    ko, eng = _STROKE_HOW[kind]
    template = eng if en else ko
    if jamo is None and "{j}" in template:  # 자모를 모르면 글자 전체로 말한다
        template = "In {c}, check the strokes again." if en else "{c}의 획을 다시 확인해요."
    text = template.format(c=char, j=jamo, p=_eun(jamo or ""))
    return Explanation(kind=Mark.STROKE, cell_indexes=[cell], wrong=None, right=char, jamo=jamo, text=text)


# 조사: 앞말 마지막 글자의 받침에 맞춘다
def _rago(word: str) -> str:
    return "이라고" if last_jong(word) else "라고"


def _eun(word: str) -> str:
    return "은" if last_jong(word) else "는"


def _eul(word: str) -> str:
    return "을" if last_jong(word) else "를"


def _euro(word: str) -> str:
    return "로" if last_jong(word) in ("", "ㄹ") else "으로"


def _nearest(words: list[int | None]) -> list[int | None]:
    """각 위치에서 그 앞(자기 자신 제외)에 마지막으로 나온 어절 번호. 없으면 None."""
    out: list[int | None] = []
    last: int | None = None
    for word in words:
        out.append(last)
        if word is not None:
            last = word
    return out


_SEJONG = {
    # 상황: (표정, 한국어 (첫 줄, 둘째 줄), 영어 (첫 줄, 둘째 줄))
    "perfect": (
        "praise",
        ("참 잘했어요!", "글자도 띄어쓰기도 쓰는 순서도 다 맞았어요."),
        ("Well done!", "Letters, spacing and stroke order are all correct."),
    ),
    "stroke": (
        "encourage",
        ("글자는 다 맞았어요", "주황 상자에서 쓰는 순서를 다시 볼까요?"),
        ("All the letters are right", "Check the stroke order in the orange boxes."),
    ),
    "balance": (
        "encourage",
        ("글자는 다 맞았어요", "글자 모양을 조금만 다듬어 볼까요?"),
        ("All the letters are right", "Let's tidy up the letter shapes a little."),
    ),
    "unchecked": (
        "praise",
        ("글자와 띄어쓰기는 다 맞았어요", "쓰는 순서는 이번에 확인하지 못했어요."),
        ("Letters and spacing are correct", "Stroke order could not be checked this time."),
    ),
    "wrong": (
        "regret",
        ("아쉬워요, 다른 곳이 있어요", "빨간 상자를 다시 볼까요?"),
        ("So close!", "Take another look at the red boxes."),
    ),
}


def sejong_message(req: GradeRequest, result: AggregateResult) -> SejongMessage:
    """결과에 맞는 킹세종 말풍선 (칭찬·아쉬움·격려). LLM이 실패해도 항상 이 문장을 쓸 수 있다.

    표정(expression)은 결과로 정한다:
    - 다 맞음 (perfect) → praise
    - 글자나 띄어쓰기가 틀림 → regret
    - 글자·띄어쓰기는 맞고 획순이 틀린 칸(주황)이 있음 → encourage
    - 글자·띄어쓰기·획순은 맞고 균형(글자 모양)만 통과하지 못한 칸이 있음 → encourage
    - 다 맞았지만 획 판정을 못 한 칸이 있음 → praise (확인 못 했다고 알림)
    """
    if result.perfect:
        key = "perfect"
    elif not result.correct:
        key = "wrong"
    elif any(c.mark == Mark.STROKE for c in result.cells):
        key = "stroke"
    elif any(c.stroke_pass is False for c in result.cells):
        key = "balance"
    else:
        key = "unchecked"
    expression, ko, en = _SEJONG[key]
    text, sub_text = en if req.locale == "en" else ko
    return SejongMessage(text=text, sub_text=sub_text, expression=expression, source="template")
