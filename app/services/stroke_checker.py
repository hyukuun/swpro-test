"""[정진] D-04 획 수·획순·방향 판정 (글자가 맞은 칸만).

- 진입점 check_strokes(target, canvas, strokes) → StrokeCheckResult (passed, errors, stroke_map, duration_ms)
- 획순은 judge(), 균형(BALANCE)은 services/stroke_balance.py, 정답은 core/reference.py 정답 획 사전
- 판정 과정, 쓰기 방식 변형, 번호 규칙: docs/stroke_check.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations, product
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from app.config import ENGINE_VERSION
from app.core.reference import get_reference
from app.core.stroke_vectorizer.jamo_templates import PIECES, STROKE_COUNT
from app.schemas import Canvas, CellError, Stroke, StrokeMapItem


@dataclass(frozen=True)
class StrokeCheckResult:
    """칸 하나의 획 판정 결과. 응답 CellResult의 strokePass·errors·strokeMap·durationMs로 그대로 들어간다."""

    passed: bool
    errors: list[CellError] = field(default_factory=list)
    stroke_map: list[StrokeMapItem] = field(default_factory=list)
    duration_ms: float | None = None


# =====================================================================
# 획순 판정
# =====================================================================

# ---- 파라미터 (논문 값 출발, 테스트로 조정) ----
N_POINTS = 32  # 획당 리샘플 점 수
GRID = 8  # SCF 바둑판 8×8
HALF = 1.0  # 바둑판 반폭 (기준점 ±1.0 → 캔버스 전체 포함)
ALPHA = 0.5  # 비용 = ALPHA·SCF + (1-ALPHA)·위치
REJECT = 0.45  # 비용이 이보다 크면 짝 없음 → EXTRA / MISSING


# ---------------- 전처리 ----------------
def normalize(stroke, canvas):
    """[[x, y, t, p], ...] 픽셀 → [[x, y], ...] 0~1."""
    p = np.asarray(stroke["points"], dtype=float)[:, :2]
    return p / [canvas["w"], canvas["h"]]


def resample(pts, n=N_POINTS):
    """호 길이 기준 n점 리샘플."""
    p = np.asarray(pts, dtype=float)
    seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    if len(p) == 1 or s[-1] == 0:
        return np.repeat(p[:1], n, axis=0)
    t = np.linspace(0, s[-1], n)
    return np.stack([np.interp(t, s, p[:, 0]), np.interp(t, s, p[:, 1])], axis=1)


# ---------------- SCF ----------------
_c = (np.arange(GRID) + 0.5) / GRID * 2 * HALF - HALF  # 칸 중심
_CX, _CY = np.meshgrid(_c, _c)
_SIGMA = HALF / GRID  # 칸 폭의 절반


def scf_at(p, cloud):
    """점 p에서 본 주변 풍경: cloud 점들을 8×8 칸에 가우시안으로 나눠 담은 히스토그램 (합 1)."""
    d = cloud - p
    dx = d[:, 0, None, None] - _CX
    dy = d[:, 1, None, None] - _CY
    h = np.exp(-(dx**2 + dy**2) / (2 * _SIGMA**2)).sum(axis=0).ravel()
    return h / (h.sum() + 1e-12)


def stroke_scf(stroke, cloud):
    """시작점·끝점 SCF를 이어 붙임 (128개)."""
    return np.concatenate([scf_at(stroke[0], cloud), scf_at(stroke[-1], cloud)])


def chi2(a, b):
    """χ² 거리. 시작·끝 두 표의 평균이라 0~1."""
    return 0.25 * np.sum((a - b) ** 2 / (a + b + 1e-12))


# ---------------- 비용 ----------------
def pair_cost(u, r, cloud_u, cloud_r):
    """학습자 획 u ↔ 정답 획 r. 정방향·역방향 중 싼 쪽과 역방향 여부 반환."""
    s_ref = stroke_scf(r, cloud_r)
    best = None
    for rev, uu in ((False, u), (True, u[::-1])):
        pos = np.linalg.norm(uu - r, axis=1).mean()
        scf = chi2(stroke_scf(uu, cloud_u), s_ref)
        c = ALPHA * scf + (1 - ALPHA) * pos
        if best is None or c < best[0]:
            best = (c, rev)
    return best


def match(user, ref):
    """전체 그림 기준 비용 행렬 → 헝가리안. m[i] = 정답 획 번호(0부터) 또는 None.
    → (m, 역방향 여부, 짝지은 획들의 비용 합)"""
    cloud_u, cloud_r = np.concatenate(user), np.concatenate(ref)
    C = np.empty((len(user), len(ref)))
    rev = np.zeros_like(C, dtype=bool)
    for i, u in enumerate(user):
        for j, r in enumerate(ref):
            C[i, j], rev[i, j] = pair_cost(u, r, cloud_u, cloud_r)
    m: list[int | None] = [None] * len(user)
    reversed_ = [False] * len(user)
    cost = 0.0
    for i, j in zip(*linear_sum_assignment(C), strict=False):
        if C[i, j] <= REJECT:
            m[i], reversed_[i] = int(j), bool(rev[i, j])
            cost += float(C[i, j])
    return m, reversed_, cost


# ---------------- 획순 ----------------
def order_ok(m):
    """짝 번호 수열의 최장 증가 부분수열(LIS)에 든 획만 순서 OK.
    → 최소한으로 옮겨야 할 획만 ORDER. 예: [2,3,1] → 3번째 획만."""
    idx = [i for i, j in enumerate(m) if j is not None]
    seq = [m[i] for i in idx]
    tails: list[int] = []
    tails_at: list[int] = []
    prev = [-1] * len(seq)
    for k, v in enumerate(seq):
        lo = int(np.searchsorted(tails, v))
        if lo == len(tails):
            tails.append(v)
            tails_at.append(k)
        else:
            tails[lo] = v
            tails_at[lo] = k
        prev[k] = tails_at[lo - 1] if lo > 0 else -1
    keep, k = set(), (tails_at[-1] if tails_at else -1)
    while k != -1:
        keep.add(k)
        k = prev[k]
    return {idx[k]: (k in keep) for k in range(len(idx))}


# ---------------- 쓰기 방식 변형 ----------------
# 자모마다 허용하는 다른 쓰는 방법 (획 번호는 자모 안에서 0부터). 뜻과 고르는 기준: docs/stroke_check.md
#   horizontal_tick: n = n번 꼭지를 가로로   merge_strokes: (a, b) = a·b번 획을 한 번에
WRITING_VARIANTS: dict[str, dict[str, Any]] = {
    "ㅈ": {"merge_strokes": (0, 1)},  # 0:ㅡ  1:왼다리  2:오른다리
    "ㅊ": {"horizontal_tick": 0, "merge_strokes": (1, 2)},  # 0:꼭지  1:ㅡ  2:왼다리  3:오른다리
    "ㅎ": {"horizontal_tick": 0},  # 0:꼭지  1:ㅡ  2:ㅇ
}


def horizontal_line(points):
    """획의 중심·길이(시작~끝 거리)를 그대로 둔 왼→오 가로선"""
    p = np.asarray(points, dtype=float)
    (x0, y0), (x1, y1) = p.min(0), p.max(0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    half = float(np.linalg.norm(p[-1] - p[0])) / 2
    return [[cx - half, cy], [cx + half, cy]]


def apply_writing(strokes, ops):
    """부품 하나의 획들(점 목록들)에 쓰기 방식 변형을 적용"""
    strokes = list(strokes)
    if "horizontal_tick" in ops:
        n = ops["horizontal_tick"]
        strokes[n] = horizontal_line(strokes[n])
    if "merge_strokes" in ops:
        a, b = ops["merge_strokes"]
        strokes[a] = list(strokes[a]) + [strokes[b][-1]]  # a번 획 끝 → b번 획 끝 직선 ("7"자)
        del strokes[b]
    return strokes


def _piece_options(base):
    """부품 하나에서 고를 수 있는 변형 조합: 표준({}) + 방법들을 켠 조합 전부"""
    ops = WRITING_VARIANTS.get(base, {})
    return [{k: ops[k] for k in keys} for r in range(len(ops) + 1) for keys in combinations(ops, r)]


def writing_variants(ref):
    """정답 획 → 정답 후보 목록 (첫 번째 = 표준 모양). 획은 {"order", "jamo", "role", "points"}"""
    ref = sorted(ref, key=lambda s: s["order"])
    groups: list[tuple[str, str, list[Any]]] = []  # (role, jamo, 획 점들) 쓰는 순서대로
    for s in ref:
        if groups and groups[-1][:2] == (s["role"], s["jamo"]):
            groups[-1][2].append(s["points"])
        else:
            groups.append((s["role"], s["jamo"], [s["points"]]))

    slots = []  # (role, jamo, 부품 기본 자모, 부품 획 점들, 선택지)
    for role, jamo, pts in groups:
        bases = PIECES.get(jamo, [jamo])
        sizes = [STROKE_COUNT.get(b, 0) for b in bases]
        if sum(sizes) != len(pts):  # 템플릿과 획 수가 다르면 변형 없이 그대로
            bases, sizes = [jamo], [len(pts)]
        start = 0
        for base, size in zip(bases, sizes, strict=True):
            piece = pts[start : start + size]
            start += size
            options = _piece_options(base) if size == STROKE_COUNT.get(base) else [{}]
            slots.append((role, jamo, piece, options))

    out = []
    for choice in product(*(opts for *_, opts in slots)):
        strokes = []
        for (role, jamo, piece, _), ops in zip(slots, choice, strict=True):
            for points in apply_writing(piece, ops):
                strokes.append({"jamo": jamo, "role": role, "points": np.round(points, 4).tolist()})
        out.append([{"order": k + 1, **st} for k, st in enumerate(strokes)])
    return out


# ---------------- 진입점 ----------------
def judge(req, ref=None):
    """req: 입력 JSON(dict). ref: 정답 획 [{"order", "jamo", "role", "points"}] (없으면 정답 획 사전에서)
    쓰기 방식 변형(WRITING_VARIANTS)마다 판정해서 오류가 가장 적은 것(같으면 더 비슷한 것)을 고른다.
    고른 정답 획은 결과의 "reference"에 담는다 (균형 판정이 같은 정답을 쓰도록)."""
    if ref is None:
        ref = _reference(req["target"])
    U = [resample(normalize(s, req["canvas"])) for s in req["strokes"]]
    best = None
    for cand in writing_variants(ref):
        errors, stroke_map, cost = _judge_one(U, cand)
        if best is None or (len(errors), cost) < (len(best[0]), best[2]):
            best = (errors, stroke_map, cost, cand)
    assert best is not None
    errors, stroke_map, _, chosen = best

    ts = [p[2] for s in req["strokes"] for p in s["points"] if len(p) > 2]
    return {
        "target": req["target"],
        "engineVersion": ENGINE_VERSION,
        "pass": not errors,
        "errors": errors,
        "strokeMap": stroke_map,
        "durationMs": round(max(ts) - min(ts), 1) if ts else None,
        "reference": chosen,
    }


def _judge_one(U, ref):
    """정답 후보 하나로 판정 → (오류, 획 짝, 짝 비용 합). U: 리샘플한 학습자 획"""
    # 정답 획마다 자모 안에서 몇 번째 획인지 (strokeNo)
    seen: dict[tuple[str, str], int] = {}
    info: list[dict[str, Any]] = []
    for s in ref:
        key = (s["role"], s["jamo"])
        seen[key] = seen.get(key, 0) + 1
        info.append({"jamo": s["jamo"], "role": s["role"], "strokeNo": seen[key]})

    R = [resample(s["points"]) for s in ref]
    m, reversed_, cost = match(U, R)
    ok = order_ok(m)

    # 쓴 순서(actual): 짝이 있는 획만 세서 1부터
    actual, n = {}, 0
    for i, j in enumerate(m):
        if j is not None:
            n += 1
            actual[i] = n

    errors, stroke_map = [], []
    for i, j in enumerate(m):
        if j is None:
            errors.append({"type": "EXTRA", "strokeIndex": i})
            stroke_map.append({"userIndex": i, "jamo": None, "role": None, "strokeNo": None})
            continue
        a = info[j]
        stroke_map.append({"userIndex": i, **a})
        if not ok[i]:
            errors.append(
                {
                    "type": "ORDER",
                    "jamo": a["jamo"],
                    "role": a["role"],
                    "strokeIndex": i,
                    "expected": j + 1,
                    "actual": actual[i],
                }
            )
        if reversed_[i]:
            errors.append({"type": "DIRECTION", "jamo": a["jamo"], "role": a["role"], "strokeIndex": i})
    matched = {j for j in m if j is not None}
    for j, a in enumerate(info):
        if j not in matched:
            errors.append({"type": "MISSING", **a})

    return errors, stroke_map, cost


# =====================================================================
# 진입점 (pipeline → 여기)
# =====================================================================
def check_strokes(target: str, canvas: Canvas, strokes: list[Stroke]) -> StrokeCheckResult:
    """학습자 획을 target의 정답 획과 비교한다 (획순 + 균형)."""
    from app.services import stroke_balance  # stroke_balance가 이 모듈의 normalize를 쓰므로 여기서 불러옴

    ref = _reference(target)
    req = {
        "target": target,
        "canvas": {"w": canvas.w, "h": canvas.h},
        "strokes": [{"points": [list(p) for p in s.points]} for s in strokes],
    }
    order = judge(req, ref=ref)
    balance = stroke_balance.check(req, order["reference"], order["strokeMap"])
    errors = [CellError.model_validate(e) for e in order["errors"] + balance]
    return StrokeCheckResult(
        passed=not errors,
        errors=errors,
        stroke_map=[StrokeMapItem.model_validate(m) for m in order["strokeMap"]],
        duration_ms=order["durationMs"],
    )


def _reference(target: str) -> list[dict[str, Any]]:
    """정답 획 사전(core/reference.py)에서 꺼낸 정답 획 → judge()·stroke_balance가 쓰는 dict 형식"""
    return [s.model_dump(mode="json") for s in get_reference(target)]
