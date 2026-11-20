"""[혁윤] D-01 칸별 글자 인식 + D-01b 템플릿 매칭 대체.

칸마다 손글씨 획을 보고 무슨 글자를 썼는지 인식한다.

입출력
- 입력: 칸 하나(Cell), 칸 크기(Canvas), 이 칸에 올 수 있는 정답 글자들(expected)
- 출력: Recognition (칸 종류 + 점수 높은 순 후보 목록)

방식
- 칸 종류: 획이 없으면 EMPTY, 쓴 자국 전체가 칸의 MARK_MAX_SIZE보다 작으면 MARK(점·쉼표), 나머지는 CHAR.
- CHAR: 학습자 획과 정답 획(core/reference.py)을 64×64 그림으로 그려 모양만 비교한다. 획순은 보지 않는다.
    - 쓴 위치·크기는 보지 않는다 (둘 다 무게중심과 퍼진 정도를 맞춤, 가로세로 비율은 유지).
      위치·크기는 획 판정의 균형(BALANCE)이 본다.
    - 획을 방향(가로·세로·대각선 둘)별로 나눠, 같은 방향 획끼리만 가까운지 본다 (아무렇게나 그은 선이 점수를 못 받게).
    - 점수 = 학습자 획이 정답 획 가까이 있는 정도(정밀도)와 정답 획이 빠짐없이 쓰였는지(재현율)의 조화 평균.
      거리가 TOLERANCE_PX보다 멀어질수록 빠르게 0에 가까워진다.
    - 기준값(TOLERANCE_PX 등)은 정답 획을 흔들어 만든 가짜 손글씨로 맞췄다. 실제 손글씨로 다시 맞춰야 한다.
- 후보는 expected의 글자 + 각각과 헷갈리는 글자(다 → 타·따·더, 닭 → 달·닥)에서만 고른다 (confusable_chars).
- 문장부호는 정답 획 사전에 없다: ? ! 는 엔진에 둔 모양(_PUNCT_STROKES)과 비교하고, . , 는 MARK 칸의 크기로 점수를 준다.
- 정답 획 사전이 없으면 core.reference가 FileNotFoundError를 낸다 (그때 어떻게 할지는 부르는 쪽이 정한다).

쓰는 곳
- spacing_align: 정렬 비용 = 1 - score_of(정답 글자)
- aggregate: recognized(top), confidence, 글자 맞음(accepts)
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

import numpy as np
from numpy.typing import ArrayLike
from scipy.ndimage import distance_transform_edt

from app.core import hangul, reference
from app.schemas import Canvas, Cell

# accepts 기준 (조정 가능)
ACCEPT_MARGIN = 0.1  # 1순위와 점수 차이가 이만큼 이하면 맞게 쓴 것으로 인정 (학습자에게 유리하게)
MIN_ACCEPT_SCORE = 0.3  # 이보다 낮으면 인정하지 않음 (알아보기 힘든 낙서가 맞음이 되지 않게)

# 인식 기준 (조정 가능)
MAX_CANDIDATES = 5  # 돌려주는 후보 수
MARK_MAX_SIZE = 0.25  # 쓴 자국의 긴 변이 칸 크기의 이 비율보다 작으면 점·짧은 표시(MARK)
GRID = 64  # 비교 그림 크기 (픽셀)
SPREAD_PX = 12.0  # 글자 무게중심에서 획까지의 평균 거리(RMS)를 그림에서 이만큼으로 맞춘다 (위치·크기 맞추기)
TOLERANCE_PX = 2.5  # 학습자 획과 정답 획이 이만큼(그림 픽셀) 떨어지면 점수가 e^-1로 줄어든다
DIRECTION_WINDOW_DEG = 35.0  # 정답 획을 방향(가로·세로·대각선 둘)별로 나눌 때 각 방향에 넣는 범위 (±)
_SAMPLE_STEP = 0.006  # 획 위에 점을 찍는 간격 (칸 크기 = 1)
SHORTLIST = 3  # 정답 글자가 이보다 많으면(고수) 점수 높은 이만큼만 헷갈리는 글자를 펼친다 (속도)


class CellKind(str, Enum):
    """칸 종류."""

    EMPTY = "EMPTY"  # 획 없음 (= 띄어쓰기 후보)
    MARK = "MARK"  # 점·짧은 표시 (. , 후보). 마침표인지 실수인지는 정렬 단계에서 판단
    CHAR = "CHAR"  # 글자


@dataclass(frozen=True)
class Candidate:
    """인식 후보 하나."""

    char: str  # 글자 하나 (음절, 자모, 문장부호)
    score: float  # 이 글자일 가능성 0~1


@dataclass(frozen=True)
class Recognition:
    """칸 하나의 인식 결과."""

    cell_index: int
    kind: CellKind
    candidates: list[Candidate]  # 점수 높은 순, 최대 5개. EMPTY면 []

    @property
    def top(self) -> Candidate | None:
        """1순위 후보. 응답의 recognized·confidence, '이렇게 쓰셨어요'에 쓴다. EMPTY면 None."""
        return self.candidates[0] if self.candidates else None

    def score_of(self, char: str) -> float:
        """이 칸이 char일 점수. 후보에 없으면 0. EMPTY 칸은 char == ' '일 때 1."""
        if self.kind == CellKind.EMPTY:
            return 1.0 if char == " " else 0.0
        return next((c.score for c in self.candidates if c.char == char), 0.0)

    def accepts(self, char: str) -> bool:
        """char를 맞게 쓴 것으로 인정할지 (학습자에게 유리하게).

        기준(조정 가능): char의 점수가 MIN_ACCEPT_SCORE 이상이고,
        1순위이거나 1순위와 점수 차이가 ACCEPT_MARGIN 이하면 인정.
        EMPTY 칸은 char == ' '일 때만 인정.
        """
        if self.kind == CellKind.EMPTY:
            return char == " "
        top, score = self.top, self.score_of(char)
        return top is not None and score >= MIN_ACCEPT_SCORE and top.score - score <= ACCEPT_MARGIN


def recognize(cell: Cell, canvas: Canvas, expected: list[str]) -> Recognition:
    """칸 하나에 무슨 글자를 썼는지 알아낸다.

    expected: 이 칸에 올 수 있는 정답 글자들 (공백 제외)
      - 초보·중수: 그 칸의 정답 글자 하나 (예: ["다"])
      - 고수: 칸이 밀릴 수 있으니 정답 문장의 글자 전부 (예: ["나", "너", "좋", "아", "하", "냐", "?"])

    expected의 글자를 모두 비교한 뒤, 점수 높은 SHORTLIST개에 대해서만 헷갈리는 글자를 더 비교한다 (고수 속도).
    점수가 같으면 expected에 있는 글자를 앞에 둔다 (학습자에게 유리하게).
    """
    if not cell.strokes:
        return Recognition(cell_index=cell.index, kind=CellKind.EMPTY, candidates=[])
    strokes = [np.asarray(s.points, dtype=float)[:, :2] / [canvas.w, canvas.h] for s in cell.strokes]
    targets = list(dict.fromkeys(ch for ch in expected if ch != " "))

    if _size(strokes) < MARK_MAX_SIZE:
        return Recognition(cell_index=cell.index, kind=CellKind.MARK, candidates=_mark_candidates(strokes, targets))

    user = _Image.of(strokes)
    targets = [t for t in targets if _comparable(t)]
    score = {t: user.similarity(_reference_image(t)) for t in targets}
    near_targets = sorted(targets, key=lambda t: -score[t])[:SHORTLIST]
    for c in dict.fromkeys(c for t in near_targets for c in confusable_chars(t)):
        if c not in score and _comparable(c):
            score[c] = user.similarity(_reference_image(c))
    scored = [(round(v, 3), c) for c, v in score.items()]
    in_targets = set(targets)
    scored.sort(key=lambda sc: (-sc[0], sc[1] not in in_targets))  # sort는 안정 정렬: 그다음은 후보를 만든 순서
    candidates = [Candidate(char=c, score=s) for s, c in scored[:MAX_CANDIDATES]]
    return Recognition(cell_index=cell.index, kind=CellKind.CHAR, candidates=candidates)


# =====================================================================
# 헷갈리는 글자
# =====================================================================

# 모양이 비슷해 서로 헷갈리는 자모 (양쪽으로 쓴다)
_SIMILAR_CONSONANTS = [
    "ㄱㅋ", "ㄱㄲ", "ㅋㄲ",
    "ㄴㄷ", "ㄷㄹ", "ㄷㅌ", "ㄷㄸ", "ㅌㄸ",
    "ㅁㅂ", "ㅁㅇ", "ㅂㅍ", "ㅂㅃ", "ㅍㅃ",
    "ㅅㅆ", "ㅅㅈ", "ㅈㅊ", "ㅈㅉ", "ㅊㅉ",
    "ㅇㅎ",
]  # fmt: skip
_SIMILAR_VOWELS = [
    "ㅏㅓ", "ㅏㅑ", "ㅓㅕ", "ㅏㅐ", "ㅓㅔ", "ㅐㅔ", "ㅑㅒ", "ㅕㅖ", "ㅐㅒ", "ㅔㅖ",
    "ㅗㅜ", "ㅗㅛ", "ㅜㅠ", "ㅛㅠ", "ㅡㅗ", "ㅡㅜ",
    "ㅘㅝ", "ㅙㅞ", "ㅚㅟ", "ㅘㅙ", "ㅝㅞ", "ㅚㅙ", "ㅟㅞ", "ㅚㅢ", "ㅟㅢ", "ㅡㅢ", "ㅣㅢ",
]  # fmt: skip


def _neighbors(pairs: list[str]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for pair in pairs:
        a, b = pair[0], pair[1]
        out.setdefault(a, []).append(b)
        out.setdefault(b, []).append(a)
    return out


_SIMILAR = _neighbors(_SIMILAR_CONSONANTS + _SIMILAR_VOWELS)


_COMMON_JONG = "ㄱㄴㄹㅁㅂㅅㅇ"  # 받침 없는 글자에 잘못 붙이기 쉬운 받침 (가 → 각·간…)


def _similar_jong(jong: str) -> list[str]:
    """받침 자리에서 헷갈리는 것: 비슷한 자음, 겹받침의 한쪽(ㄺ → ㄹ·ㄱ), 그 자음이 든 겹받침, 받침 빠뜨림,
    받침이 없으면 흔한 받침을 붙인 것."""
    if not jong:
        return list(_COMMON_JONG)
    out = [j for j in _SIMILAR.get(jong, []) if j in hangul.JONG]
    out += [p for p in hangul.split_compound_jong(jong) if p != jong]
    out += [c for c in hangul.JONG if len(hangul.split_compound_jong(c)) == 2 and jong in hangul.split_compound_jong(c)]
    out.append("")
    return out


def confusable_chars(ch: str) -> list[str]:
    """ch와 모양이 비슷해 헷갈리는 글자들 (ch 자신은 빼고, 중복 없이).

    음절은 초성·중성·종성 중 하나만 바꾼다: 다 → 타·따·나·라·더·대·닥·단…, 싶 → 십, 닭 → 달·닥.
    자모 단독은 비슷한 자모 (ㄱ → ㅋ·ㄲ). 그 밖의 글자(문장부호 등)는 [].
    """
    if hangul.is_jamo(ch):
        return list(_SIMILAR.get(ch, []))
    if not hangul.is_syllable(ch):
        return []
    s = hangul.decompose(ch)
    out = [hangul.compose(c, s.jung, s.jong) for c in _SIMILAR.get(s.cho, []) if c in hangul.CHO]
    out += [hangul.compose(s.cho, v, s.jong) for v in _SIMILAR.get(s.jung, [])]
    out += [hangul.compose(s.cho, s.jung, j) for j in _similar_jong(s.jong)]
    return [c for c in dict.fromkeys(out) if c != ch]


# =====================================================================
# 모양 비교
# =====================================================================

# 정답 획 사전에 없는 문장부호의 모양 (칸 기준 0~1, 쓰는 순서). 크기·위치는 비교할 때 맞추므로 모양만 중요하다.
_PUNCT_STROKES: dict[str, list[list[tuple[float, float]]]] = {
    "?": [
        [(0.35, 0.3), (0.4, 0.2), (0.5, 0.15), (0.6, 0.2), (0.65, 0.3), (0.6, 0.4), (0.5, 0.48), (0.5, 0.62)],
        [(0.5, 0.8)],
    ],
    "!": [[(0.5, 0.15), (0.5, 0.62)], [(0.5, 0.8)]],
}


def _comparable(ch: str) -> bool:
    """CHAR 칸에서 그림으로 비교할 수 있는 글자인지 (. , 는 MARK 칸에서만 본다)."""
    return ch in _PUNCT_STROKES or ((hangul.is_syllable(ch) or hangul.is_jamo(ch)) and reference.has_reference(ch))


def _size(strokes: Sequence[np.ndarray]) -> float:
    """쓴 자국 전체 테두리 상자의 긴 변 (칸 크기 = 1)."""
    pts = np.concatenate(strokes)
    return float((pts.max(axis=0) - pts.min(axis=0)).max())


def _mark_candidates(strokes: Sequence[np.ndarray], targets: list[str]) -> list[Candidate]:
    """MARK 칸의 후보: 정답에 있는 . , 만. 아주 작으면 마침표, 클수록 쉼표에 점수를 더 준다.

    정답에 . , 가 없으면 후보 없음 → 줄 맞춤이 '실수로 찍은 점'으로 본다.
    """
    ext = min(_size(strokes) / MARK_MAX_SIZE, 1.0)  # 0(점) ~ 1(MARK 최대 크기)
    scores = {".": 0.9 - 0.6 * ext, ",": 0.3 + 0.6 * ext}
    out = [Candidate(char=c, score=round(scores[c], 3)) for c in targets if c in scores]
    return sorted(out, key=lambda c: -c.score)


_DIRECTIONS = np.deg2rad([0.0, 45.0, 90.0, 135.0])  # 가로, 대각선(\ 화면 기준), 세로, 대각선(/)


def _sample(strokes: Sequence[ArrayLike]) -> tuple[np.ndarray, np.ndarray]:
    """획 위에 같은 간격으로 점을 찍는다 → (점 (N, 2), 그 점의 획 방향 0~π (N,), 점 하나짜리 획은 nan)."""
    pts, angles = [], []
    for s in strokes:
        a = np.asarray(s, dtype=float).reshape(-1, 2)
        a = a[np.r_[True, np.any(np.diff(a, axis=0) != 0, axis=1)]]  # 같은 자리 연속 점 제거
        if len(a) == 1:
            pts.append(a)
            angles.append(np.array([np.nan]))
            continue
        d = np.diff(a, axis=0)
        s_cum = np.concatenate([[0.0], np.cumsum(np.linalg.norm(d, axis=1))])
        t = np.append(np.arange(0.0, s_cum[-1], _SAMPLE_STEP), s_cum[-1])
        seg = np.clip(np.searchsorted(s_cum, t, side="right") - 1, 0, len(d) - 1)
        pts.append(np.stack([np.interp(t, s_cum, a[:, 0]), np.interp(t, s_cum, a[:, 1])], axis=1))
        angles.append(np.arctan2(d[seg, 1], d[seg, 0]) % np.pi)
    return np.concatenate(pts), np.concatenate(angles)


def _direction_gap(angles: np.ndarray) -> np.ndarray:
    """(N,) 획 방향 → (N, 4) 각 기준 방향과의 각도 차이 0~π/2."""
    gap = np.abs(angles[:, None] - _DIRECTIONS[None, :]) % np.pi
    return np.minimum(gap, np.pi - gap)


@dataclass(frozen=True)
class _Image:
    """비교용 그림. 획 위의 점들을 방향(가로·세로·대각선 둘)별로 나눠 둔다.

    - 위치·크기 맞추기: 점들의 무게중심을 그림 가운데로, 무게중심에서의 평균 거리(RMS)를 SPREAD_PX로.
      테두리 상자로 맞추면 길게 삐친 획 하나에 글자 전체가 줄어들어서 이 방식을 쓴다. 가로세로 비율은 유지한다.
    - 방향: 같은 자리라도 방향이 다른 획(가로획 자리에 세로획)은 맞은 것으로 치지 않는다. 낙서를 걸러 낸다.
    """

    xy: np.ndarray  # (N, 2) 점의 그림 픽셀 위치 (x, y)
    weight: np.ndarray  # (N, 4) 점이 각 방향에 속하는 정도, 행 합 = 1 (점 하나짜리 획은 모든 방향 0.25)
    near: np.ndarray  # (4, GRID, GRID) 방향마다, 각 픽셀이 그 방향 획에 가까운 정도 exp(-(거리/TOLERANCE_PX)²)

    @staticmethod
    def of(strokes: Sequence[ArrayLike]) -> _Image:
        pts, angles = _sample(strokes)
        center = pts.mean(axis=0)
        rms = float(np.sqrt(((pts - center) ** 2).sum(axis=1).mean()))
        p = (pts - center) * (SPREAD_PX / max(rms, 1e-6)) + (GRID - 1) / 2
        xy = np.clip(np.rint(p).astype(int), 0, GRID - 1)

        dot = np.isnan(angles)
        gap = _direction_gap(np.where(dot, 0.0, angles))
        weight = np.clip(np.cos(2 * gap), 0.0, None)  # 기준 방향과 같으면 1, 45° 벌어지면 0
        weight[dot] = 1.0
        weight /= weight.sum(axis=1, keepdims=True)
        member = (gap <= np.deg2rad(DIRECTION_WINDOW_DEG)) | dot[:, None]

        near = np.zeros((len(_DIRECTIONS), GRID, GRID), dtype=np.float32)  # 그 방향 획이 없으면 0
        for k in range(len(_DIRECTIONS)):
            if member[:, k].any():
                ink = np.zeros((GRID, GRID), dtype=bool)
                ink[xy[member[:, k], 1], xy[member[:, k], 0]] = True
                near[k] = np.exp(-((distance_transform_edt(~ink) / TOLERANCE_PX) ** 2))
        return _Image(xy=xy, weight=weight, near=near)

    def _closeness(self, other: _Image) -> float:
        """내 점들이 other의 같은 방향 획 가까이 있는 정도 0~1."""
        return float((self.weight * other.near[:, self.xy[:, 1], self.xy[:, 0]].T).sum(axis=1).mean())

    def similarity(self, ref: _Image) -> float:
        """0~1. 내 획이 정답 획 가까이 있는 정도(정밀도)와 정답 획이 빠짐없이 쓰였는지(재현율)의 조화 평균."""
        precision, recall = self._closeness(ref), ref._closeness(self)
        return 2 * precision * recall / (precision + recall) if precision + recall else 0.0


@lru_cache(maxsize=1024)  # 그림 하나 약 70KB → 최대 약 70MB
def _reference_image(ch: str) -> _Image:
    """정답 글자의 비교용 그림 (최근 쓴 글자는 다시 그리지 않는다)."""
    if ch in _PUNCT_STROKES:
        return _Image.of(_PUNCT_STROKES[ch])
    return _Image.of([s.points for s in reference.get_reference(ch)])
