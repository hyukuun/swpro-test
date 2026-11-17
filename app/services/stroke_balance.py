"""[정진] 글자 균형 판정 (BALANCE). 넉넉한 기준, 상자(bbox)만 봄.

단계      항목   재는 법                                 기준 (시작값)
글자 전체  크기   전체 상자 높이 ÷ 칸 높이                 0.5 미만 / 1.0 초과
          위치   전체 상자 중심 ↔ 칸 중심 거리            칸 크기의 0.2 이상
자모별    위치   자모 상자가 (정답 상자 + 여유) 밖으로 나감 여유 = 칸 크기의 0.15
          크기   자모 상자 대각선 ÷ 정답 상자 대각선       0.6 미만 / 1.5 초과

글자 전체에서 걸리면 자모별은 건너뜀 (전체가 치우치면 자모가 전부 벗어나서 피드백이 쏟아짐).
좌표는 전부 0~1 (칸 = 캔버스 전체).

획순 판정(stroke_checker.judge) 결과의 strokeMap으로 학습자 획을 자모별로 묶음 → 획순 코드는 건드리지 않음.
stroke_checker.check_strokes()가 부른다.
오류마다 "message" = 학습자에게 보여줄 피드백 ("글자를 조금 더 크게 써보세요", "ㅏ를 조금 더 위에 쓰세요" 등).
"""

from typing import Any

import numpy as np

from app.services.stroke_checker import ROLE_KO, normalize  # 픽셀 → 0~1 (획순 판정과 같은 변환)

GLYPH_SIZE = (0.5, 1.0)
GLYPH_OFFSET = 0.2
JAMO_MARGIN = 0.15
JAMO_SIZE = (0.6, 1.5)


def bbox(pts):
    p = np.concatenate([np.asarray(s)[:, :2] for s in pts])
    return np.array([*p.min(0), *p.max(0)])  # x0, y0, x1, y1


def diag(b):
    return float(np.hypot(b[2] - b[0], b[3] - b[1]))


def r3(v):
    return round(float(v), 3)


# ---- 피드백 문구 ----
VOWELS = set("ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ")
MOVE = {"left": "오른쪽", "right": "왼쪽", "top": "아래", "bottom": "위"}  # 벗어난 쪽 → 옮길 쪽


def josa(jamo, pair):
    """자모 이름 받침 기준 조사. 자음 이름(기역·니은…)은 받침 있음, 모음(아·애…)은 없음.
    pair = ("이", "가") / ("을", "를")"""
    return jamo + (pair[1] if jamo in VOWELS else pair[0])


def ro(word):
    """'왼쪽' → '왼쪽으로', '위' → '위로'"""
    return word + ("으로" if word.endswith("쪽") else "로")


def direction(dx, dy, eps=0.05):
    """중심 차이 → '왼쪽 위' 같은 방향 (0~1, y 아래로 증가)"""
    d = []
    if abs(dx) >= eps:
        d.append("오른쪽" if dx > 0 else "왼쪽")
    if abs(dy) >= eps:
        d.append("아래" if dy > 0 else "위")
    return " ".join(d)


def feedback(e):
    m, j = e["metric"], e["jamo"]
    if m == "glyph_size":
        return "글자를 조금 더 " + ("크게" if e["value"] < e["range"][0] else "작게") + " 써보세요"
    if m == "glyph_offset":
        return f"글자가 {ro(direction(e['dx'], e['dy']) or '한쪽')} 치우쳤어요"
    if m == "jamo_position":
        moves = [MOVE[k] for k in e["exceed"]]
        if ("왼쪽" in moves and "오른쪽" in moves) or ("위" in moves and "아래" in moves):
            return f"{josa(j, ('을', '를'))} 조금 더 작게 쓰세요"  # 양쪽으로 다 벗어남 = 너무 큼
        order = ["왼쪽", "오른쪽", "위", "아래"]
        return f"{josa(j, ('을', '를'))} 조금 더 {' '.join(sorted(moves, key=order.index))}에 쓰세요"
    if m == "jamo_size":
        return f"{josa(j, ('이', '가'))} 너무 " + ("작아요" if e["value"] < e["range"][0] else "커요")
    return m


def with_messages(errors):
    for e in errors:
        e["message"] = feedback(e)
    return errors


def check(req, ref, stroke_map):
    """req: 입력 JSON, ref: compose 정답 획, stroke_map: 획순 엔진 출력의 strokeMap.
    반환: BALANCE 오류 목록."""
    errors: list[dict[str, Any]] = []
    user = [normalize(s, req["canvas"]) for s in req["strokes"]]
    if not user:
        return errors

    # ---- 글자 전체 ----
    g = bbox(user)
    size = g[3] - g[1]
    if not GLYPH_SIZE[0] <= size <= GLYPH_SIZE[1]:
        errors.append(
            {
                "type": "BALANCE",
                "jamo": None,
                "role": None,
                "metric": "glyph_size",
                "value": r3(size),
                "range": list(GLYPH_SIZE),
            }
        )
    dx, dy = (g[0] + g[2]) / 2 - 0.5, (g[1] + g[3]) / 2 - 0.5
    off = np.hypot(dx, dy)
    if off >= GLYPH_OFFSET:
        errors.append(
            {
                "type": "BALANCE",
                "jamo": None,
                "role": None,
                "metric": "glyph_offset",
                "value": r3(off),
                "range": [0, GLYPH_OFFSET],
                "dx": r3(dx),
                "dy": r3(dy),
            }
        )
    if errors:
        return with_messages(errors)

    # ---- 자모별 ----
    groups: dict[tuple[str, str], tuple[list[Any], list[Any]]] = {}  # (role, jamo) → (학습자 획들, 정답 획들)
    for s in ref:
        key = (ROLE_KO.get(s["role"], s["role"]), s["jamo"])
        groups.setdefault(key, ([], []))[1].append(np.asarray(s["points"]))
    for m in stroke_map:
        if m["jamo"] is not None:  # EXTRA 획은 제외
            groups[(m["role"], m["jamo"])][0].append(user[m["userIndex"]])

    for (role, jamo), (us, rs) in groups.items():
        if not us:  # 짝지은 획 없음 → MISSING에서 처리
            continue
        ub, rb = bbox(us), bbox(rs)

        # 위치: 정답 상자를 여유만큼 넓힌 범위 밖으로 나간 만큼
        exceed = {
            "left": rb[0] - JAMO_MARGIN - ub[0],
            "top": rb[1] - JAMO_MARGIN - ub[1],
            "right": ub[2] - (rb[2] + JAMO_MARGIN),
            "bottom": ub[3] - (rb[3] + JAMO_MARGIN),
        }
        exceed = {k: r3(v) for k, v in exceed.items() if v > 0}
        if exceed:
            errors.append(
                {
                    "type": "BALANCE",
                    "jamo": jamo,
                    "role": role,
                    "metric": "jamo_position",
                    "value": max(exceed.values()),
                    "range": [0, 0],
                    "exceed": exceed,
                }
            )

        # 크기: 대각선 비율 (ㅣ처럼 폭이 거의 0인 자모도 안정적)
        ratio = diag(ub) / max(diag(rb), 1e-6)
        if not JAMO_SIZE[0] <= ratio <= JAMO_SIZE[1]:
            errors.append(
                {
                    "type": "BALANCE",
                    "jamo": jamo,
                    "role": role,
                    "metric": "jamo_size",
                    "value": r3(ratio),
                    "range": list(JAMO_SIZE),
                }
            )
    return with_messages(errors)
