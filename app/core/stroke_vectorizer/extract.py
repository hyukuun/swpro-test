"""
폰트 → 조립 재료 (자모 모양 + 자모가 놓일 자리). 폰트는 data/fonts/ 안의 파일, 결과는 data/extracted/<폰트 id>/
전체 순서·파일 형식: docs/extracted_data.md

  python -m app.core.stroke_vectorizer.extract                                # 기본 폰트 NotoSansKR-Light.ttf
  python -m app.core.stroke_vectorizer.extract --font DONGGUK-UNIVERSITY      # data/fonts/DONGGUK-UNIVERSITY.ttf
  python -m app.core.stroke_vectorizer.extract --font path/to/font.ttf        # 다른 곳의 폰트 파일
  python -m app.core.stroke_vectorizer.extract --steps table,mode             # 일부 단계만
  python -m app.core.stroke_vectorizer.extract --sample 300                   # 음절 300자만 빠른 확인 (저장 안 함)

단계: jamo → syllables → table → mode
끝나면 python -m app.core.stroke_vectorizer.compose --all 로 정답 획 사전을 다시 만들어야 서버에 반영된다.
"""

import argparse
import math
import os
import random
import time
from collections import Counter, defaultdict
from multiprocessing import Pool
from typing import Any

import numpy as np
from fontTools.pens.recordingPen import RecordingPen
from fontTools.ttLib import TTFont
from matplotlib.path import Path
from scipy import ndimage as ndi
from skimage.draw import polygon as fill_polygon
from skimage.measure import label, regionprops
from skimage.morphology import skeletonize

from app.core.stroke_vectorizer import compose as C
from app.core.stroke_vectorizer.jamo_templates import (
    JAMO_TEMPLATES,
    decompose,
    jamo_entries,
    ksx1001,
    piece_sizes,
    syllable_template,
    vowel_dir,
)

# ═════════ 설정 ═════════
SIZE = 256  # 이미지 크기 (px)
SPUR_LEN = 8  # 이보다 짧은 잔가지는 제거 (px)
RDP_EPS = 2.0  # 꺾임 감지 민감도 (px, 작을수록 민감)
MIN_SEG = 4  # 이보다 짧은 선분은 무시 (px)
JOIN_DIST = 6  # 선분 끝끼리 이 거리 안이면 이어진 것으로 봄 (px)
ANGLE_TOL = 35  # 방향 허용 오차 (도)
N_POINTS = 32  # 획당 점 개수
HOOK_LEN = 10  # 이보다 짧은 선분은 획 끝 장식 (남아도 허용, px)
MAX_TURN = 45  # 한 방향 단계 안에서 허용하는 선분 간 꺾임 (도)
ROW_GAP = 12  # 시작점 y 차이가 이 안이면 같은 줄 → 왼쪽 우선 (px)
COL_GAP = 24  # 겹자모: 시작점 x 차이가 이 안이면 같은 열 → 위쪽 우선 (px)
TAIL_LEN = 20  # 이보다 짧고 매끄럽게 이어지는 선분은 방향 무관하게 같은 획 (끝이 눕는 곡선)
# ㅇ 판정: 구멍이 bbox를 채우는 비율(타원 ≈ 0.785, 사각형 ≈ 1.0)과 볼록함
ROUND_EXTENT = (0.70, 0.86)
ROUND_SOLIDITY = 0.96
MIN_HOLE_AREA = 30
JAMO_FLAT = 10  # 자모 bbox 한 변이 이보다 작으면 그 축은 0.5 (px) — ㅡ·ㅣ의 1~2px 흔들림을 늘리지 않게
MARGIN = 0.05  # 박스 방식 선택: 더 촘촘한 방식이 5% 이상 나아야 채택 (획 박스는 추출 획순 오류에 약해서)
STEPS = ("jamo", "syllables", "table", "mode")

# 이미지 좌표 기준 각도 (y가 아래로 증가하므로 S = 90도)
DIR_ANGLE = {"E": 0, "SE": 45, "S": 90, "SW": 135, "W": 180, "NW": -135, "N": -90, "NE": -45}


# ═════════ 폰트 ═════════
# set_font()이 채운다 (multiprocessing 작업 프로세스마다 initializer로도 부름)
FONT: str | None = None
EM_TOP: float | None = None
font: Any = None
cmap: Any = None
gs: Any = None
UPM: Any = None


def set_font(path, em_top):
    """추출에 쓸 폰트 (모듈 전역 → rasterize가 씀)"""
    global FONT, EM_TOP, font, cmap, gs, UPM
    FONT, EM_TOP = str(path), em_top
    font = TTFont(FONT)
    cmap, gs = font.getBestCmap(), font.getGlyphSet()
    UPM = font["head"].unitsPerEm


def has_glyph(ch):
    return ord(ch) in cmap


def add_font_args(ap):
    ap.add_argument("--font", help="폰트 (data/fonts/ 안의 파일 이름 또는 경로, 기본 NotoSansKR-Light)")
    ap.add_argument("--em-top", type=float, help="글자 상자 위 y (기본: 폰트에서 자동 추정)")


def load_font(args):
    """--font/--em-top → 폰트 적용, (결과 폴더, 폰트 정보)"""
    meta = dict(C.font_info(args.font))
    if args.em_top is not None:
        meta["em_top"] = args.em_top
    set_font(meta["file"], meta["em_top"])
    return C.font_dir(args.font), meta


# ═════════ 글리프 → 뼈대 → 선분 ═════════
# ───────── 글자 → 이미지 ─────────
def glyph_paths(ch):
    pen = RecordingPen()
    gs[cmap[ord(ch)]].draw(pen)
    paths, v, c = [], [], []
    for op, args in pen.value:
        if op == "moveTo":
            v, c = [args[0]], [Path.MOVETO]
        elif op == "lineTo":
            v.append(args[0])
            c.append(Path.LINETO)
        elif op == "qCurveTo":
            *offs, end = args
            for a, b in zip(offs, offs[1:], strict=False):
                mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                v += [a, mid]
                c += [Path.CURVE3, Path.CURVE3]
            v += [offs[-1], end]
            c += [Path.CURVE3, Path.CURVE3]
        elif op == "curveTo":
            v += list(args)
            c += [Path.CURVE4] * 3
        elif op in ("closePath", "endPath"):
            v.append(v[0])
            c.append(Path.CLOSEPOLY)
            paths.append(Path(v, c))
    return paths


def rasterize(ch):
    wind = np.zeros((SIZE, SIZE), int)
    for p in glyph_paths(ch):
        for poly in p.to_polygons(closed_only=False):
            x, y = poly[:, 0], poly[:, 1]
            area = 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)
            rr, cc = fill_polygon((EM_TOP - y) / UPM * SIZE, x / UPM * SIZE, wind.shape)
            wind[rr, cc] += int(np.sign(area))
    return wind != 0


# ───────── 잔가지 제거 ─────────
OFFS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def nbrs(p, pix):
    """주변 8칸 중 뼈대 픽셀"""
    r, c = p
    return [(r + dr, c + dc) for dr, dc in OFFS if (r + dr, c + dc) in pix]


def prune_spurs(skel):
    """끝점에서 출발해 SPUR_LEN 안에 갈림점을 만나면 그 가지를 지운다"""
    pix = set(zip(*np.nonzero(skel), strict=False))
    for _ in range(3):
        removed = False
        for e in [p for p in pix if len(nbrs(p, pix)) == 1]:
            if e not in pix:
                continue
            path, cur, hit = [e], e, False
            while len(path) <= SPUR_LEN:
                nxt = [q for q in nbrs(cur, pix) if q not in path]
                if any(len(nbrs(q, pix)) >= 3 for q in nxt):
                    hit = True
                    break
                if len(nxt) != 1:
                    break
                cur = nxt[0]
                path.append(cur)
            if hit:
                pix -= set(path)
                removed = True
        if not removed:
            break
    return pix


# ───────── 뼈대 → 선분 ─────────
def trace_paths(pix):
    """끝점·갈림점 사이를 따라가며 픽셀 경로로 만든다"""
    nodes = {p for p in pix if len(nbrs(p, pix)) != 2}
    used, paths = set(), []

    def walk(start, first):
        path, prev, cur = [start], start, first
        while True:
            path.append(cur)
            if cur in nodes or cur == start:
                return path
            used.add(cur)
            a, b = nbrs(cur, pix)
            prev, cur = cur, (b if a == prev else a)

    for n in nodes:
        for nb in nbrs(n, pix):
            if nb not in nodes and nb not in used:
                paths.append(walk(n, nb))
    for p in pix - nodes - used:  # 끝점이 없는 고리 (ㅁ, ㅇ)
        if p not in used:
            used.add(p)
            paths.append(walk(p, nbrs(p, pix)[0]))
    return [np.array([(c, r) for r, c in path], float) for path in paths]  # (x, y)


def rdp(pts, eps):
    """꺾이는 점만 남기는 단순화 (Ramer–Douglas–Peucker). 남길 점의 인덱스 반환"""
    if len(pts) < 3:
        return [0, len(pts) - 1]
    a, b = pts[0], pts[-1]
    ab = b - a
    L = np.hypot(*ab)
    if L == 0:
        d = np.hypot(*(pts - a).T)
    else:
        d = np.abs(ab[0] * (pts[:, 1] - a[1]) - ab[1] * (pts[:, 0] - a[0])) / L
    i = int(np.argmax(d))
    if d[i] > eps:
        left, right = rdp(pts[: i + 1], eps), rdp(pts[i:], eps)
        return left[:-1] + [i + j for j in right]
    return [0, len(pts) - 1]


def poly_len(pts):
    return float(np.sum(np.hypot(*np.diff(pts, axis=0).T)))


def seg_angle(arr):
    d = arr[-1] - arr[0]
    return math.degrees(math.atan2(d[1], d[0]))


def resample(pts, n):
    d = np.r_[0, np.cumsum(np.hypot(*np.diff(pts, axis=0).T))]
    t = np.linspace(0, d[-1], n)
    return np.c_[np.interp(t, d, pts[:, 0]), np.interp(t, d, pts[:, 1])]


# ═════════ 선분 → 획 배정 (획순 템플릿) ═════════
# ───────── 글자 → 선분 ─────────
def extract_segments(ch):
    """래스터화 → 골격 → 잔가지 제거 → (ㅇ 고리 분리) → 선분 (+ 이어진 덩어리 번호)"""
    img = rasterize(ch)
    pix = prune_spurs(skeletonize(img))
    skel = np.zeros((SIZE, SIZE), bool)
    for r, c in pix:
        skel[r, c] = True
    comp = label(skel, connectivity=2)

    loops = []
    for pts, ring_pix in find_round_loops(img, pix):
        r, c = next(iter(ring_pix))
        loops.append({"arr": pts, "loop": True, "minor": False, "comp": int(comp[r, c])})
        pix = pix - ring_pix  # 고리 픽셀은 빼고 나머지만 선분으로
    return img, loops + to_segments(trace_paths(pix), comp)


def find_round_loops(img, pix):
    """
    글자의 둥근 구멍(= ㅇ) 둘레의 뼈대 픽셀을 고리 하나로 묶는다.
    다른 획이 몇 군데 닿아 고리가 여러 조각으로 갈라져도 하나로 복원된다.
    반환: [(닫힌 폴리라인 (x, y), 고리 픽셀 집합)]
    """
    holes = label(~img, connectivity=1)
    border = set(np.unique(np.r_[holes[0], holes[-1], holes[:, 0], holes[:, -1]]))
    dist_in = ndi.distance_transform_edt(img)
    width = 2 * float(np.median([dist_in[p] for p in pix])) if pix else 4.0

    out = []
    for rp in regionprops(holes):
        if rp.label in border or rp.area < MIN_HOLE_AREA:
            continue
        if not (ROUND_EXTENT[0] <= rp.extent <= ROUND_EXTENT[1] and rp.solidity >= ROUND_SOLIDITY):
            continue  # 각진 구멍(ㅁ·ㅂ)이나 우연한 틈
        mask = holes == rp.label
        d_hole = ndi.distance_transform_edt(~mask)
        ring_pix = {p for p in pix if 0 < d_hole[p] <= 0.8 * width + 1.5}
        if len(ring_pix) < 12:
            continue
        cy, cx = rp.centroid
        pts = sorted(((c, r) for r, c in ring_pix), key=lambda q: np.arctan2(q[1] - cy, q[0] - cx))
        arr = np.array(pts, float)
        out.append((np.vstack([arr, arr[:1]]), ring_pix))
    return out


def to_segments(paths, comp):
    segs = []
    for pts in paths:
        cid = int(comp[int(pts[0][1]), int(pts[0][0])])
        idx = rdp(pts, RDP_EPS)
        # 갈림점이 붙은 고리는 시작·끝이 몇 px 어긋나므로 JOIN_DIST까지 닫힌 것으로 봄
        closed = len(pts) > 8 and np.hypot(*(pts[0] - pts[-1])) <= JOIN_DIST
        if closed and len(idx) > 7:  # 둥근 고리 = ㅇ
            segs.append({"arr": pts, "loop": True, "minor": False, "comp": cid})
            continue
        for i, j in zip(idx, idx[1:], strict=False):  # 각진 고리(ㅁ)는 선분으로
            s = pts[i : j + 1]
            if poly_len(s) >= MIN_SEG:
                segs.append({"arr": s, "loop": False, "minor": poly_len(s) < HOOK_LEN, "comp": cid})
    return segs


def orient_loop(pts):
    """화면 기준 반시계, 맨 위 점에서 시작"""
    p = pts[:-1] if np.allclose(pts[0], pts[-1]) else pts
    x, y = p[:, 0], p[:, 1]
    area = 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)
    if area > 0:  # y축이 아래 방향이라 양수 = 화면상 시계방향
        p = p[::-1]
    k = int(np.argmin(p[:, 1] * 1000 + p[:, 0]))
    p = np.roll(p, -k, axis=0)
    return np.vstack([p, p[:1]])


# ───────── 획 후보 ─────────
def ang_ok(arr, d):
    a = seg_angle(arr)
    return any(abs((a - DIR_ANGLE[x] + 180) % 360 - 180) <= ANGLE_TOL for x in d.rstrip("!").split("|"))


def turn(a, b):
    return abs((b - a + 180) % 360 - 180)


def last_major_angle(chain, segs):
    for i, arr in reversed(chain):
        if not segs[i]["minor"]:
            return seg_angle(arr)
    return seg_angle(chain[-1][1])


def is_maximal(chain, dirs, segs, free):
    """앞뒤로 같은 방향 선분이 매끄럽게 이어지는데 안 붙였으면 False"""
    used = {i for i, _ in chain}
    others = [i for i in free if i not in used and not segs[i]["loop"] and not segs[i]["minor"]]
    start, end = chain[0][1][0], chain[-1][1][-1]
    first_ang = seg_angle(chain[0][1])
    last_ang = last_major_angle(chain, segs)
    for i in others:
        for arr in (segs[i]["arr"], segs[i]["arr"][::-1]):
            a = seg_angle(arr)
            # 뒤로 더 이어짐
            if (
                not dirs[-1].endswith("!")
                and np.hypot(*(arr[0] - end)) <= JOIN_DIST
                and (ang_ok(arr, dirs[-1]) or poly_len(arr) < TAIL_LEN)
                and turn(last_ang, a) <= MAX_TURN
            ):
                return False
            # 앞으로 더 이어짐
            if (
                not dirs[0].endswith("!")
                and np.hypot(*(arr[-1] - start)) <= JOIN_DIST
                and ang_ok(arr, dirs[0])
                and turn(a, first_ang) <= MAX_TURN
            ):
                return False
    return True


def stroke_candidates(dirs, segs, free, strict=False):
    if dirs == ["CCW"]:
        return [[(i, orient_loop(segs[i]["arr"]))] for i in free if segs[i]["loop"]]
    lines = [i for i in free if not segs[i]["loop"]]
    out = []

    def extend(chain, k, in_chain, last_ang):
        end = chain[-1][1][-1]
        if k == len(dirs) - 1:
            out.append(list(chain))
        for i in lines:
            if i in in_chain:
                continue
            for arr in (segs[i]["arr"], segs[i]["arr"][::-1]):
                if np.hypot(*(arr[0] - end)) > JOIN_DIST:
                    continue
                if segs[i]["minor"]:  # 갈고리: 방향 무관
                    chain.append((i, arr))
                    in_chain.add(i)
                    extend(chain, k, in_chain, last_ang)
                    chain.pop()
                    in_chain.discard(i)
                    continue
                a = seg_angle(arr)
                smooth = turn(last_ang, a) <= MAX_TURN
                # 같은 단계 계속: 부드럽게 이어지고, 방향이 맞거나 짧은 끝부분일 때 (곡선 O, 직각 X)
                # "!" 단계는 선분 하나만 허용
                if not dirs[k].endswith("!") and smooth and (ang_ok(arr, dirs[k]) or poly_len(arr) < TAIL_LEN):
                    chain.append((i, arr))
                    in_chain.add(i)
                    extend(chain, k, in_chain, a)
                    chain.pop()
                    in_chain.discard(i)
                # 다음 단계로 꺾기
                if k + 1 < len(dirs) and ang_ok(arr, dirs[k + 1]):
                    chain.append((i, arr))
                    in_chain.add(i)
                    extend(chain, k + 1, in_chain, a)
                    chain.pop()
                    in_chain.discard(i)

    for i in lines:
        if segs[i]["minor"]:  # 갈고리에서 획을 시작하지 않음
            continue
        for arr in (segs[i]["arr"], segs[i]["arr"][::-1]):
            if ang_ok(arr, dirs[0]):
                extend([(i, arr)], 0, {i}, seg_angle(arr))
    if strict:
        out = [ch for ch in out if is_maximal(ch, dirs, segs, free)]
    return out


# ───────── 배정 ─────────
class SearchLimit(Exception):
    pass


def assign(entries, segs, max_calls=20000, time_limit=3.0, meta=None):
    """
    1차: 끝까지 이어 붙인 후보만 (빠름)
    2차: 1차 실패 시 모든 후보 (맞닿은 획을 끊어야 하는 드문 경우 — 틀릴 가능성 높음)
    각 단계는 time_limit의 절반까지만 탐색 (넘으면 SearchLimit)
    meta에 dict를 넘기면 meta["pass"] = 1 또는 2 기록
    """
    hit_limit = False
    for n_pass, strict in ((1, True), (2, False)):
        try:
            deadline = time.time() + time_limit / 2
            res = _assign(entries, segs, strict, max_calls, deadline)
        except SearchLimit:
            hit_limit = True
            continue
        if res is not None:
            if meta is not None:
                meta["pass"] = n_pass
            return res
    if hit_limit:
        raise SearchLimit
    return None


def _assign(entries, segs, strict, max_calls, deadline):
    """
    부품의 첫 획: 다른 부품이 안 쓴 덩어리 → (겹자모면 왼쪽 우선 / 아니면 위쪽 줄 → 왼쪽)
    부품의 다음 획: 같은 덩어리 → 앞 획과 가까운 것 → 긴 것 → 위·왼쪽
    겹자모: 뒤 부품의 중심이 앞 부품보다 오른쪽이어야 함
    선분이 남으면 실패 → 되돌아가 다른 후보
    한 번 실패한 (획 번호, 남은 선분) 상태는 기억해서 다시 풀지 않음
    부품이 끝날 때마다 남은 선분을 남은 획들이 덮을 수 있는지 확인 (못 덮으면 바로 되돌아감)
    """
    calls = 0
    failed = set()
    cand_cache = {}
    last_of_unit = {e["unit"]: i for i, e in enumerate(entries)}

    def cands_of(dirs, free):
        key = (tuple(dirs), frozenset(free))
        if key not in cand_cache:
            cand_cache[key] = stroke_candidates(dirs, segs, free, strict)
        return cand_cache[key]

    def coverable(si, free):
        """남은 선분 각각이 남은 획 중 하나의 후보에라도 들어갈 수 있는가"""
        need = {i for i in free if not segs[i]["minor"]}
        for e in entries[si:]:
            if time.time() > deadline:
                raise SearchLimit
            for ch in cands_of(e["dirs"], free):
                need.difference_update(i for i, _ in ch)
                if not need:
                    return True
        return not need

    def unit_cx(done, unit):
        return np.vstack([a for u, c in done if u == unit for _, a in c])[:, 0].mean()

    def order_ok(si, done):
        e = entries[si]
        if e["piece"] == 0 or last_of_unit[e["unit"]] != si:
            return True
        prev_unit = f"{e['role']}{e['piece'] - 1}"
        return unit_cx(done, e["unit"]) > unit_cx(done, prev_unit)

    def solve(si, free, done):
        nonlocal calls
        calls += 1
        if calls > max_calls or time.time() > deadline:
            raise SearchLimit
        if si == len(entries):
            return [] if all(segs[i]["minor"] for i in free) else None
        state = (si, frozenset(free))
        if state in failed:
            return None
        unit = entries[si]["unit"]
        # 부품 경계: 남은 선분을 다 덮을 수 없으면 더 볼 필요 없음
        if si > 0 and entries[si - 1]["unit"] != unit and not coverable(si, free):
            failed.add(state)
            return None
        cands = cands_of(entries[si]["dirs"], free)
        if not cands:
            failed.add(state)
            return None

        def comp_of(ch):
            return segs[ch[0][0]]["comp"]

        mine = [c for u, c in done if u == unit]
        role = entries[si]["role"]
        # 다른 자모(초·중·종이 다른 것)가 쓴 덩어리. 같은 겹자모 부품끼리 붙은 건 정상이라 제외
        role_of_unit = {e["unit"]: e["role"] for e in entries}
        other_comps = {segs[i]["comp"] for u, c in done if role_of_unit[u] != role for i, _ in c}
        dirs = entries[si]["dirs"]

        def mid_start(ch):
            """시작점 뒤로 같은 방향 선분이 매끄럽게 이어짐 = 선 중간에서 시작 (2차 탐색만 해당)"""
            if dirs == ["CCW"]:
                return False
            used = {i for i, _ in ch}
            st, a0 = ch[0][1][0], seg_angle(ch[0][1])
            for i in free - used:
                if segs[i]["loop"] or segs[i]["minor"]:
                    continue
                for arr in (segs[i]["arr"], segs[i]["arr"][::-1]):
                    if (
                        np.hypot(*(arr[-1] - st)) <= JOIN_DIST
                        and ang_ok(arr, dirs[0])
                        and turn(seg_angle(arr), a0) <= MAX_TURN
                    ):
                        return True
            return False

        def rows_of(group):
            """시작점 y를 위에서부터 묶어 줄 번호 (줄 첫 점과 ROW_GAP 이내면 같은 줄)"""
            row, top, n = {}, None, -1
            for y in sorted({ch[0][1][0][1] for ch in group}):
                if top is None or y - top > ROW_GAP:
                    top, n = y, n + 1
                row[y] = n
            return lambda ch: row.get(ch[0][1][0][1], n + 1)

        row_all = rows_of(cands)

        if mine:
            my_comps = {segs[i]["comp"] for c in mine for i, _ in c}
            ref = np.vstack([a for c in mine for _, a in c])

            def key(ch):  # 같은 덩어리 → 앞 획과 가까움 → 위쪽 줄 → 왼쪽 → 긴 것
                st = ch[0][1][0]
                return (
                    mid_start(ch),
                    comp_of(ch) not in my_comps,
                    round(np.min(np.hypot(*(ref - st).T)) / JOIN_DIST),
                    row_all(ch),
                    st[0],
                    -len(ch),
                )
        else:
            pref = [ch for ch in cands if comp_of(ch) not in other_comps] or cands
            xmin = min(ch[0][1][0][0] for ch in pref)
            row = row_all
            if entries[si]["multi"]:  # 겹자모 부품: (나란히) → 왼쪽 열 → 위쪽 줄 → 왼쪽
                # 뒤 부품은 앞 부품 옆에 나란히 놓임 → 세로 범위가 앞 부품과 겹치는 획 우선
                # (쩝: 둘째 ㅈ 가로획 자리에 아래 ㅂ 가로획이 가던 문제)
                prev = f"{role}{entries[si]['piece'] - 1}"
                prev_pts = [a for u, c in done if u == prev for _, a in c]
                if prev_pts:
                    pys = np.vstack(prev_pts)[:, 1]
                    plo, phi = pys.min() - ROW_GAP, pys.max() + ROW_GAP

                def beside(ch):
                    if not prev_pts:
                        return True
                    ys = np.vstack([a for _, a in ch])[:, 1]
                    return ys.max() >= plo and ys.min() <= phi

                def key(ch):
                    st = ch[0][1][0]
                    return (
                        mid_start(ch),
                        comp_of(ch) in other_comps,
                        not beside(ch),
                        int((st[0] - xmin) // COL_GAP),
                        row(ch),
                        st[0],
                        -len(ch),
                    )
            else:  # 일반: 위쪽 줄 → 왼쪽

                def key(ch):
                    st = ch[0][1][0]
                    return (mid_start(ch), comp_of(ch) in other_comps, row(ch), st[0], -len(ch))

        for ch in sorted(cands, key=key):
            new_done = done + [(unit, ch)]
            if not order_ok(si, new_done):
                continue
            rest = solve(si + 1, free - {i for i, _ in ch}, new_done)
            if rest is not None:
                return [ch] + rest
        failed.add(state)
        return None

    return solve(0, set(range(len(segs))), [])


def chain_points(chain):
    return np.vstack([chain[0][1]] + [arr[1:] for _, arr in chain[1:]])


# ═════════ 단계 jamo: 자모 51개 → jamo_strokes.json ═════════
def normalize(strokes):
    """획 점 목록들 → 자모 전체 bbox 기준 0~1"""
    allp = np.vstack(strokes)
    lo, hi = allp.min(0), allp.max(0)
    span = hi - lo
    out = []
    for p in strokes:
        q = np.empty_like(p)
        for ax in (0, 1):
            q[:, ax] = 0.5 if span[ax] < JAMO_FLAT else (p[:, ax] - lo[ax]) / span[ax]
        out.append(q)
    return out


def step_jamo(fdir):
    """형식: {"ㄷ": [{"order", "unit": "p0"|"p1", "dirs", "points"}]}. 하나라도 실패하면 중단"""
    missing = [j for j in JAMO_TEMPLATES if not has_glyph(j)]
    if missing:
        raise SystemExit(f"폰트에 자모 글리프 없음: {''.join(missing)}")
    data, fails = {}, []
    for j in JAMO_TEMPLATES:
        _, segs = extract_segments(j)
        entries = jamo_entries(j, "cho")
        try:
            chains = assign(entries, segs)
        except SearchLimit:
            chains = None
        if not chains:
            fails.append(j)
            continue
        pts = normalize([resample(chain_points(c), N_POINTS) for c in chains])
        data[j] = [
            {"order": k + 1, "unit": f"p{e['piece']}", "dirs": e["dirs"], "points": p.round(4).tolist()}
            for k, (e, p) in enumerate(zip(entries, pts, strict=False))
        ]
    if fails:
        raise SystemExit(f"자모 추출 실패 {len(fails)}/{len(JAMO_TEMPLATES)}: {''.join(fails)}")
    out = fdir / "jamo_strokes.json"
    C.write_json(out, data)
    print(f"[jamo] 자모 {len(data)}개, 획 {sum(len(v) for v in data.values())}개 → {out}")


# ═════════ 단계 syllables: 음절 2,350자 → strokes_ksx1001.json ═════════
def process(syl):
    """글자 하나 → (글자, 획 데이터 또는 None, 실패 이유, 걸린 시간)"""
    t = time.time()
    entries = syllable_template(syl)
    meta: dict[str, Any] = {}
    try:
        _, segs = extract_segments(syl)
        strokes = assign(entries, segs, meta=meta)
        reason = None if strokes else "배정 실패"
    except SearchLimit:
        strokes, reason = None, "탐색 초과"
    except Exception as e:  # noqa: BLE001
        strokes, reason = None, f"오류: {type(e).__name__} {e}"
    data = None
    if strokes:
        data = {
            "pass": meta.get("pass", 1),  # 2 = 느슨한 탐색으로 찾음 (검수 우선)
            "strokes": [
                {
                    "order": k + 1,
                    "jamo": e["jamo"],
                    "role": e["role"],
                    "points": (resample(chain_points(c), N_POINTS) / SIZE).round(4).tolist(),
                }
                for k, (e, c) in enumerate(zip(entries, strokes, strict=False))
            ],
        }
    return syl, data, reason, time.time() - t


def step_syllables(fdir, meta, sample=0, workers=None, seed=0):
    """→ 추출 결과 {글자: {"pass", "strokes"}}. 전체 실행이면 strokes_ksx1001.json으로 저장 (sample은 저장 안 함)"""
    chars = ksx1001()
    no_glyph = [c for c in chars if not has_glyph(c)]
    if no_glyph:
        print(
            f"폰트에 글리프 없는 글자 {len(no_glyph)}자 건너뜀: {''.join(no_glyph[:30])}"
            + (" …" if len(no_glyph) > 30 else "")
        )
        chars = [c for c in chars if has_glyph(c)]
    if sample:
        chars = random.Random(seed).sample(chars, min(sample, len(chars)))
    workers = workers or os.cpu_count()

    data, fails, times = {}, [], []
    t0 = time.time()
    print(f"[syllables] {len(chars)}자, 프로세스 {workers}개")
    with Pool(workers, initializer=set_font, initargs=(meta["file"], meta["em_top"])) as pool:
        for n, (syl, d, reason, dt) in enumerate(pool.imap_unordered(process, chars, chunksize=8), 1):
            times.append((dt, syl, reason))
            if d:
                data[syl] = d
            else:
                fails.append({"syl": syl, "parts": [j for _, j in decompose(syl)], "reason": reason})
            if n % 200 == 0:
                print(f"  {n}/{len(chars)}  성공 {len(data)}  ({time.time() - t0:.0f}s)")

    order = {c: i for i, c in enumerate(ksx1001())}
    data = dict(sorted(data.items(), key=lambda kv: order[kv[0]]))
    fails.sort(key=lambda f: order[f["syl"]])
    out = "저장 안 함 (sample)"
    if not sample:
        C.write_json(fdir / "strokes_ksx1001.json", data)
        out = C.relative_to_root(fdir / "strokes_ksx1001.json")

    n_pass2 = sum(1 for d in data.values() if d["pass"] == 2)
    print(
        f"  성공 {len(data)}/{len(chars)} ({len(data) / max(len(chars), 1):.1%}), "
        f"{time.time() - t0:.0f}s  (그중 2차 탐색 {n_pass2}자 — 틀릴 가능성 높음) → {out}"
    )
    if fails:
        print("  실패 이유:", Counter(f["reason"].split(":")[0] for f in fails).most_common())
        print("  실패한 글자 (compose 결과에는 들어 있음):", "".join(f["syl"] for f in fails))
        print("  실패에 많이 등장한 자모:", Counter(j for f in fails for j in f["parts"]).most_common(15))
    times.sort(reverse=True)
    print("  느린 글자 상위 10:", ", ".join(f"{s}({dt:.1f}s{'·' + r if r else ''})" for dt, s, r in times[:10]))
    return data


# ═════════ 단계 table: 추출 음절 → 배치표 (slots.json, detail.json) ═════════
# 자리별로 추출 음절의 자모 bbox를 모아 중앙값. 키 형식은 compose.py 설명 참고
#   - pass 1 글자만 (2차 탐색 결과는 틀린 게 섞임)
#   - 배치 원칙을 어기는 글자 제외 (plausible) — 실제로 추출이 틀린 글자들
def bbox(strokes):
    pts = np.vstack([s["points"] for s in strokes])
    return [*pts.min(0), *pts.max(0)]


def load_extracted(path):
    raw = C.read_json(C.project_path(path))
    # 새 형식 {"pass", "strokes"} / 예전 형식 [획...] 둘 다 지원
    return {k: (v if isinstance(v, dict) else {"pass": 1, "strokes": v}) for k, v in raw.items()}


def plausible(bx, jung):
    """자모 배치 원칙에 맞는가 (추출이 틀린 글자가 중앙값을 오염시키지 않게)"""
    c = {r: ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for r, b in bx.items()}
    d = vowel_dir(jung)
    if d in ("V", "C") and not c["cho"][0] < c["jung"][0]:  # 초성은 세로·복합모음 왼쪽
        return False
    if d in ("H", "C") and not c["cho"][1] < c["jung"][1]:  # 초성은 가로·복합모음 위
        return False
    if d == "V":  # 세로모음: 초성과 모음 획이 뒤섞이지 않음
        if bx["cho"][2] > bx["jung"][2] - 0.05:  #   초성 오른끝이 모음 기둥까지 가면 X
            return False
        if bx["jung"][0] < bx["cho"][0] + 0.05:  #   모음 왼끝이 초성 왼끝까지 오면 X
            return False
    if "jong" in bx:
        if bx["jong"][1] < bx["cho"][3] - 0.02:  # 종성 위끝 ≥ 초성 아래끝
            return False
        if not c["jong"][1] > c["jung"][1]:  # 종성 중심은 중성보다 아래
            return False
        if d == "H" and bx["jong"][1] < bx["jung"][3] - 0.02:  # 가로모음: 종성은 모음 아래끝보다 아래
            return False
    return True


def trusted(data):
    """pass 1 + 배치 원칙 통과 → {글자: (parts, 추출 획)}"""
    out = {}
    for syl, d in data.items():
        if d["pass"] != 1:
            continue
        parts = dict(decompose(syl))
        bx = {r: bbox([s for s in d["strokes"] if s["role"] == r]) for r in parts}
        if plausible(bx, parts["jung"]):
            out[syl] = (parts, d["strokes"])
    return out


def median_table(boxes):
    return {k: {"box": np.median(v, axis=0).round(4).tolist(), "n": len(v)} for k, v in sorted(boxes.items())}


def build_tables(data, dropped=None):
    """→ (slots, detail)"""
    sl, de = defaultdict(list), defaultdict(list)
    jong_samples = []  # (모음방향, 받침, 박스, [부품 박스]) → 받침별 차이
    for syl, d in data.items():
        if d["pass"] != 1:
            continue
        parts = dict(decompose(syl))
        jung, has_jong = parts["jung"], "jong" in parts
        bx = {r: bbox([s for s in d["strokes"] if s["role"] == r]) for r in parts}
        if not plausible(bx, jung):
            if dropped is not None:
                dropped.append(syl)
            continue
        for role, jamo in parts.items():
            exact, fb = C.keys_of(role, jamo, jung, has_jong)
            sl[exact].append(bx[role])  # ① 자모 박스
            sl[fb].append(bx[role])
            mine = [s for s in d["strokes"] if s["role"] == role]
            sub = C.sub_base(role, jamo, jung, has_jong)
            for si, st in enumerate(mine):  # ② 획 박스
                de[f"{sub}|s{si}"].append(bbox([st]))
            sizes = piece_sizes(jamo)
            pboxes = []
            if len(sizes) > 1:  # ② 부품 박스
                pboxes = [bbox(mine[a:b]) for a, b in zip(np.cumsum([0] + sizes), np.cumsum(sizes), strict=False)]
                for pi, pb in enumerate(pboxes):
                    de[f"{sub}|p{pi}"].append(pb)
            if role == "jong":
                jong_samples.append((vowel_dir(jung), jamo, bx[role], pboxes))
    slots = median_table(sl)

    # 받침별 차이 = 박스 − 같은 모음방향 일반 박스 (자모 → ①, 부품 → ②)
    sd, dd = defaultdict(list), defaultdict(list)
    for d, jamo, box, pboxes in jong_samples:
        gen = np.array(slots[f"jong|{d}|*"]["box"])
        sd[C.delta_key(jamo)].append(np.array(box) - gen)
        for pi, pb in enumerate(pboxes):
            dd[f"{C.delta_key(jamo)}|p{pi}"].append(np.array(pb) - gen)
    slots.update(median_table(sd))
    detail = median_table(de)
    detail.update(median_table(dd))
    return dict(sorted(slots.items())), dict(sorted(detail.items()))


def step_table(fdir, data):
    dropped: list[str] = []
    slots, detail = build_tables(data, dropped)
    C.write_json(fdir / "slots.json", slots, indent=1)
    C.write_json(fdir / "detail.json", detail, indent=1)

    used = sum(1 for d in data.values() if d["pass"] == 1)
    nfb = sum(1 for k in slots if C.is_fallback(k))
    ndelta = sum(1 for k in slots if k.startswith("jong|+|"))
    few = [f"{k}({v['n']})" for k, v in slots.items() if v["n"] < C.MIN_N and not k.startswith("jong|+|")]
    print(
        f"[table] 배치 원칙 위반으로 제외 {len(dropped)}자: {''.join(dropped[:60])}{'…' if len(dropped) > 60 else ''}"
    )
    print(f"  측정 {used - len(dropped)}자 (pass 1 {used}자 중)")
    print(f"  ① slots.json  키 {len(slots)}개 (일반 {nfb}, 받침 차이 {ndelta})")
    print(
        f"  ② detail.json 키 {len(detail)}개 (부품 {sum('|p' in k for k in detail)}, "
        f"획 {sum('|s' in k for k in detail)})"
    )
    print(f"  표본 < {C.MIN_N} 정밀 키 {len(few)}개 (종성은 일반 박스 + 받침 차이로 대체):", " ".join(few) or "없음")


# ═════════ 단계 mode: 자모마다 박스 방식 → box_mode.json ═════════
def chamfer(a, b):
    """점 집합끼리 가장 가까운 점 거리 평균 (양방향, 순서 무관)"""
    d = np.hypot(*(a[:, None, :] - b[None, :, :]).transpose(2, 0, 1))
    return float((d.min(1).mean() + d.min(0).mean()) / 2)


def role_shapes(parts, ext, comp):
    """자리(초·중·종)마다 추출 vs 조합 모양 거리"""
    out = {}
    for r in parts:
        a = np.vstack([s["points"] for s in ext if s["role"] == r])
        b = np.vstack([s["points"] for s in comp if s["role"] == r])
        out[r] = chamfer(a, b)
    return out


def choose_modes(data, font_id):
    """2겹 교차 검증: 글자를 반으로 나눠 한쪽으로 배치표, 다른 쪽으로 평가.
    측정한 글자로 평가하면 촘촘한 방식(stroke)이 무조건 유리해서 나눠서 본다"""
    good = trusted(data)
    chars = sorted(good)
    folds = [set(chars[0::2]), set(chars[1::2])]
    res: dict[str, defaultdict[str, list[float]]] = {m: defaultdict(list) for m in C.MODES}
    for k in (0, 1):
        slots, detail = build_tables({c: d for c, d in data.items() if c not in folds[k]})
        for syl in folds[k]:
            parts, ext = good[syl]
            for m in C.MODES:
                comp = C.compose(syl, font_id, mode=m, use_tweaks=False, slots=slots, detail=detail)
                for r, v in role_shapes(parts, ext, comp).items():
                    res[m][parts[r]].append(v)
    mode_of = {}
    print("  자모    n    jamo   piece  stroke  → 선택")
    for j in sorted(res["jamo"], key=lambda j: -np.median(res["jamo"][j])):
        med = {m: float(np.median(res[m][j])) for m in C.MODES}
        best = "jamo"
        for m in C.MODES[1:]:
            if med[m] < med[best] * (1 - MARGIN):
                best = m
        mode_of[j] = best
        print(f"  {j}   {len(res['jamo'][j]):5}  {med['jamo']:.3f}  {med['piece']:.3f}  {med['stroke']:.3f}  {best}")
    return mode_of


def step_mode(fdir, data):
    print("[mode]")
    mode_of = choose_modes(data, fdir.name)
    C.write_json(fdir / "box_mode.json", mode_of, indent=1)
    cnt = {m: "".join(j for j, v in mode_of.items() if v == m) for m in C.MODES}
    print("  선택 →", "  ".join(f"{m}: {cnt[m] or '-'}" for m in C.MODES), f"→ {fdir / 'box_mode.json'}")


# ═════════ 실행 ═════════
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="폰트 → 획 데이터 전체 과정")
    add_font_args(ap)
    ap.add_argument("--steps", help=f"쉼표로 구분, 기본 전부: {','.join(STEPS)}")
    ap.add_argument("--data", help="table·mode 단계 재료 (기본: 결과 폴더의 strokes_ksx1001.json)")
    ap.add_argument("--sample", type=int, default=0, help="음절 추출만 무작위 N자 (빠른 확인용)")
    ap.add_argument("--workers", type=int, default=os.cpu_count(), help="음절 추출 프로세스 수")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    if args.steps:
        steps = [s.strip() for s in args.steps.split(",") if s.strip()]
        bad = [s for s in steps if s not in STEPS]
        if bad:
            ap.error(f"모르는 단계: {', '.join(bad)} (가능: {', '.join(STEPS)})")
        if args.sample and steps != ["syllables"]:
            ap.error("--sample은 음절 추출 확인용이라 --steps syllables 와만 씁니다")
    else:
        steps = ["syllables"] if args.sample else list(STEPS)
    steps = [s for s in STEPS if s in steps]  # 순서 고정

    fdir, meta = load_font(args)
    t0 = time.time()
    data = None
    for step in steps:
        if step == "jamo":
            step_jamo(fdir)
        elif step == "syllables":
            data = step_syllables(fdir, meta, args.sample, args.workers, args.seed)
        else:
            if data is None:
                src = args.data or fdir / "strokes_ksx1001.json"
                if not C.project_path(src).exists():
                    raise SystemExit(f"음절 추출 결과 없음 ({src}) → --steps syllables 먼저")
                data = load_extracted(src)
            C._profiles.clear()  # 앞 단계에서 바뀐 파일 다시 읽기
            if step == "table":
                step_table(fdir, data)
            else:
                step_mode(fdir, data)
    print(f"끝 ({time.time() - t0:.0f}s): {', '.join(steps)} → {fdir}")
