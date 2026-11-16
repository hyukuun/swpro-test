"""[정진] D-04 획 수·획순·방향 판정 (글자가 맞은 칸만).

입출력 (정진님 교정 엔진 명세 1·2번과 같은 내용)
- 입력: 정답 글자(target), 칸 크기(canvas), 학습자 획(strokes, 쓴 순서대로, 칸 기준 픽셀 좌표)
- 출력: StrokeCheckResult
    passed      : 명세의 pass. errors가 비었으면 True
    errors      : ORDER / DIRECTION / MISSING / EXTRA / BALANCE (schemas.CellError 형식)
    stroke_map  : 학습자 획 ↔ 정답 획 짝, 학습자 획마다 하나 (schemas.StrokeMapItem 형식)
    duration_ms : 첫 점 ~ 마지막 점 시간(ms)
- role은 cho / jung / jong 으로 쓴다 (명세의 '초성/중성/종성' 대신, schemas.Role).

부르는 조건 (pipeline이 지킨다)
- recognizer가 정답 글자를 맞게 썼다고 인정한 칸만
- target이 한글 음절 또는 자모 단독일 때만 (문장부호·빈 칸은 부르지 않음)

구성
- check_strokes() : pipeline이 부르는 진입점. judge() + stroke_balance.check()를 schemas 형식으로 바꿔 돌려준다
- judge()         : 획순 판정 (SCF + 헝가리안). 글자 완성 후 1회 판정. dict 입출력
                    (scripts/hand_writing_confirm.py 필기 테스트도 이걸 직접 부른다)
- 균형(BALANCE)   : services/stroke_balance.py

획순 판정 참고: Nguyen et al. (2019), Pattern Recognition Letters 121, 140-149.

judge() 입력:
    {"target": "가", "canvas": {"w": 300, "h": 300},
     "strokes": [{"points": [[x, y, t_ms, pressure], ...]}, ...]}
정답: core/reference.py의 정답 획 사전 (compose.py --all로 만든 composed_all.json)
    → [{"order", "jamo", "role", "points": [[x, y], ...]}]  (0~1)

judge() 출력: 획순 관련 필드만. role은 '초성/중성/종성' (필기 테스트 화면 형식)
    errors 종류: MISSING, EXTRA, ORDER, DIRECTION

번호 규칙 (10/31 초안 그대로):
    strokeIndex, userIndex : 학습자 획 순번, 0부터
    strokeNo               : 해당 자모 안에서 몇 번째 획, 1부터
    expected, actual       : 글자 전체 기준 몇 번째로 써야 했나 / 실제로 썼나, 1부터
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from app.config import ENGINE_VERSION
from app.core.reference import get_reference
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

ROLE_KO = {"cho": "초성", "jung": "중성", "jong": "종성"}
ROLE_EN = {v: k for k, v in ROLE_KO.items()}


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
    """전체 그림 기준 비용 행렬 → 헝가리안. m[i] = 정답 획 번호(0부터) 또는 None."""
    cloud_u, cloud_r = np.concatenate(user), np.concatenate(ref)
    C = np.empty((len(user), len(ref)))
    rev = np.zeros_like(C, dtype=bool)
    for i, u in enumerate(user):
        for j, r in enumerate(ref):
            C[i, j], rev[i, j] = pair_cost(u, r, cloud_u, cloud_r)
    m: list[int | None] = [None] * len(user)
    reversed_ = [False] * len(user)
    for i, j in zip(*linear_sum_assignment(C), strict=False):
        if C[i, j] <= REJECT:
            m[i], reversed_[i] = int(j), bool(rev[i, j])
    return m, reversed_


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


# ---------------- 진입점 ----------------
def judge(req, ref=None):
    """req: 입력 JSON(dict). ref: 정답 획 [{"order", "jamo", "role", "points"}] (없으면 정답 획 사전에서)"""
    if ref is None:
        ref = _reference(req["target"])
    ref = sorted(ref, key=lambda s: s["order"])

    # 정답 획마다 자모 안에서 몇 번째 획인지 (strokeNo)
    seen: dict[tuple[str, str], int] = {}
    info: list[dict[str, Any]] = []
    for s in ref:
        key = (s["role"], s["jamo"])
        seen[key] = seen.get(key, 0) + 1
        info.append({"jamo": s["jamo"], "role": ROLE_KO.get(s["role"], s["role"]), "strokeNo": seen[key]})

    R = [resample(s["points"]) for s in ref]
    U = [resample(normalize(s, req["canvas"])) for s in req["strokes"]]
    m, reversed_ = match(U, R)
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

    ts = [p[2] for s in req["strokes"] for p in s["points"] if len(p) > 2]
    return {
        "target": req["target"],
        "engineVersion": ENGINE_VERSION,
        "pass": not errors,
        "errors": errors,
        "strokeMap": stroke_map,
        "durationMs": round(max(ts) - min(ts), 1) if ts else None,
    }


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
    balance = stroke_balance.check(req, ref, order["strokeMap"])
    errors = [CellError.model_validate(_role_en(e)) for e in order["errors"] + balance]
    return StrokeCheckResult(
        passed=not errors,
        errors=errors,
        stroke_map=[StrokeMapItem.model_validate(_role_en(m)) for m in order["strokeMap"]],
        duration_ms=order["durationMs"],
    )


def _reference(target: str) -> list[dict[str, Any]]:
    """정답 획 사전(core/reference.py)에서 꺼낸 정답 획 → judge()·stroke_balance가 쓰는 dict 형식"""
    return [s.model_dump(mode="json") for s in get_reference(target)]


def _role_en(item: dict[str, Any]) -> dict[str, Any]:
    """judge()·stroke_balance의 role '초성' → schemas.Role 'cho'"""
    role = item.get("role")
    return {**item, "role": ROLE_EN.get(role, role)} if role is not None else item
