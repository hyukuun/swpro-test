"""
정답 획 조립: extract.py가 만든 재료(+ editor.py 수동 조정)로 글자의 정답 획을 조립하고,
전체를 정답 획 사전 composed_all.json으로 저장한다 (서버는 이 사전만 읽음).
전체 순서·조립 방법·파일 형식: docs/extracted_data.md

사용법 (프로젝트 루트에서)
  python -m app.core.stroke_vectorizer.compose            # 확인용 그림, 무작위 50자 → outputs/compose.png
  python -m app.core.stroke_vectorizer.compose 뒁 깜 와    # 지정 글자만 그림
  python -m app.core.stroke_vectorizer.compose --all      # 정답 획 사전 다시 만들기 (서버 정답이 바뀜, 약 15초)
  --font <폰트>  --no-tweaks  --n  --seed  --full  --out   (자세한 뜻은 --help)
"""

import argparse
import json
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np

from app.core.stroke_vectorizer.jamo_templates import (
    CHO,
    JUNG,
    all_syllables,
    decompose,
    ksx1001,
    piece_sizes,
    vowel_dir,
)

# ═════════ 경로 ═════════
# 어느 폴더에서 실행해도 같은 곳을 보도록 프로젝트 루트 기준으로 잡는다
ROOT = Path(__file__).resolve().parents[3]  # app/core/stroke_vectorizer/compose.py → 프로젝트 루트
FONT_FILES_DIR = ROOT / "data" / "fonts"  # 폰트 파일 (.ttf/.otf)
FONTS_DIR = ROOT / "data" / "extracted"  # 폰트별 추출 결과
OUTPUTS_DIR = ROOT / "outputs"  # 검수용 그림 등 생성물 (git에 올리지 않음)
DEFAULT_FONT_FILE = FONT_FILES_DIR / "NotoSansKR-Light.ttf"  # 정답 획 기본 폰트
FONT_EXTS = (".ttf", ".otf")


def project_path(p):
    """프로젝트 루트 기준 상대 경로 → 실제 경로"""
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def relative_to_root(p):
    """화면에 보여 줄 경로: 프로젝트 안이면 루트 기준 상대 경로"""
    p = Path(p).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


# ═════════ 폰트 ═════════
def font_id(font=None):
    """폰트 → id (파일 이름에서 확장자 뺀 것). None = 기본 폰트.
    'NotoSansKR-Light', 'NotoSansKR-Light.ttf', 'data/fonts/NotoSansKR-Light.ttf' 모두 'NotoSansKR-Light'"""
    if font is None:
        return DEFAULT_FONT_FILE.stem
    p = Path(font)
    return p.stem if p.suffix.lower() in FONT_EXTS else p.name


def font_file(font=None):
    """폰트 → 폰트 파일 경로. 경로를 주면 그대로, 이름만 주면 data/fonts/에서 찾는다"""
    if font is not None and Path(font).suffix.lower() in FONT_EXTS:
        p = Path(font)
        if not p.is_absolute() and not p.exists():
            p = project_path(p)
        if p.exists():
            return p
    fid = font_id(font)
    for ext in FONT_EXTS:
        if (FONT_FILES_DIR / f"{fid}{ext}").exists():
            return FONT_FILES_DIR / f"{fid}{ext}"
    have = sorted(p.name for p in FONT_FILES_DIR.glob("*") if p.suffix.lower() in FONT_EXTS)
    raise SystemExit(f"폰트 파일 '{fid}' 없음. data/fonts/에 넣어 주세요. 있는 폰트: {', '.join(have) or '없음'}")


def font_dir(font=None):
    """폰트의 추출 결과 폴더 data/extracted/<폰트 id>/"""
    return FONTS_DIR / font_id(font)


def composed_path(font=None):
    """정답 획 사전 파일 (compose.py --all이 만들고 core/reference.py가 읽음)"""
    return font_dir(font) / "composed_all.json"


EM_SAMPLE = "가각간갈감강개거고과괴구국그기나다라마바사아자차카타파하한글뚫"


def guess_em_top(tt):
    """글자 상자 위 y. OS/2 typo 위·아래 합이 upm이면 그 값(Noto 880),
    아니면 한글 글리프들 세로 범위의 가운데 + upm/2"""
    from fontTools.pens.boundsPen import BoundsPen

    upm = tt["head"].unitsPerEm
    os2 = tt["OS/2"] if "OS/2" in tt else None
    if os2 is not None and os2.sTypoAscender - os2.sTypoDescender == upm:
        return os2.sTypoAscender
    cm, glyphs = tt.getBestCmap(), tt.getGlyphSet()
    ys = []
    for ch in EM_SAMPLE:
        if ord(ch) in cm:
            pen = BoundsPen(glyphs)
            glyphs[cm[ord(ch)]].draw(pen)
            if pen.bounds:
                ys += [pen.bounds[1], pen.bounds[3]]
    if not ys:
        raise SystemExit("한글 글리프가 없는 폰트")
    return round((min(ys) + max(ys)) / 2 + upm / 2)


@cache
def font_info(font=None):
    """폰트 파일에서 읽은 정보 {"name", "file", "upm", "em_top"} (그림·편집기·추출용)"""
    from fontTools.ttLib import TTFont

    path = font_file(font)
    tt = TTFont(str(path))
    return {
        "name": tt["name"].getDebugName(4) or path.stem,
        "file": str(path),
        "upm": tt["head"].unitsPerEm,
        "em_top": guess_em_top(tt),
    }


def read_json(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        if default is None:
            raise
        return default


def write_json(path, data, indent=None):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)


class Profile:
    """한 폰트의 조합 재료. 파일이 없으면 빈 값 (tweaks·box_mode·detail은 없어도 동작)"""

    def __init__(self, font=None):
        fid = font_id(font)
        d = font_dir(fid)
        if not (d / "jamo_strokes.json").exists():
            have = sorted(p.name for p in FONTS_DIR.glob("*") if (p / "jamo_strokes.json").exists())
            raise SystemExit(
                f"폰트 '{fid}'의 추출 결과 없음 ({relative_to_root(d)}/jamo_strokes.json).\n"
                f"  먼저 실행: python -m app.core.stroke_vectorizer.extract --font {fid}\n"
                f"  추출된 폰트: {', '.join(have) or '없음'}"
            )
        self.id, self.dir = fid, d
        self.jamo = read_json(d / "jamo_strokes.json")
        self.slots = read_json(d / "slots.json")
        self.detail = read_json(d / "detail.json", {})
        self.box_mode = read_json(d / "box_mode.json", {})
        self.tweaks = read_json(d / "tweaks.json", {"slot": {}, "syllable": {}})

    @property
    def meta(self):
        """폰트 정보 (폰트 파일이 있어야 함. 조합만 할 때는 필요 없음)"""
        return font_info(self.id)

    def save_tweaks(self):
        """획 하나(32점 이동량)를 한 줄로 — 사람이 열어 봐도 읽히게"""
        lines = ["{"]
        for si, scope in enumerate(("slot", "syllable")):
            table = self.tweaks.get(scope, {})
            lines.append(f' "{scope}": {{')
            for n, k in enumerate(table):
                strokes = sorted(table[k].items(), key=lambda x: int(x[0]))
                body = ",\n".join(f'   "{i}": {json.dumps(d)}' for i, d in strokes)
                lines.append(f'  "{k}": {{\n{body}\n  }}' + ("," if n < len(table) - 1 else ""))
            lines.append(" }" + ("," if si == 0 else ""))
        lines.append("}")
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "tweaks.json").write_text("\n".join(lines) + "\n", encoding="utf-8")


_profiles: dict[str, Profile] = {}


def get_profile(font=None):
    fid = font_id(font)
    if fid not in _profiles:
        _profiles[fid] = Profile(fid)
    return _profiles[fid]


# ═════════ ① 칸 배치 (slots.json) ═════════
# 음절 안 각 자리(초성·중성·종성)에 자모 하나가 들어갈 박스
# 자리(키):
#   초성 cho|<중성>|<받침 0/1>   중성 jung|<중성>|<받침 0/1>   종성 jong|<모음방향>|<종성>
#   모음방향: V 세로(ㅏㅐㅑㅒㅓㅔㅕㅖㅣ) / H 가로(ㅗㅛㅜㅠㅡ) / C 복합(ㅘㅙㅚㅝㅞㅟㅢ)
# 조회 순서:
#   정밀 키(표본 ≥ MIN_N)
#   → [종성] jong|<모음방향>|* + jong|+|<종성>  (일반 박스 + 받침별 차이, 덧셈 모델)
#       위치는 모음방향이, 크기는 받침 모양이 정한다. 방향 하나를 빼고 맞혀 보는 시험에서
#       박스 좌표 오차 0.009 (일반 박스만 0.021)
#   → fallback: cho|<모음방향>|<받침>, jung|<모음방향>|<받침>, jong|<모음방향>|*
# 값: {"box": [x0, y0, x1, y1] (0~1 글자 프레임), "n": 표본 수}
MIN_N = 3  # 정밀 키 최소 표본
DELTA_MIN_N = 1  # 받침별 차이는 표본 1개라도 사용 (드문 겹받침 ㄵ·ㅄ·ㄿ도 일반 박스보다 나음)


def keys_of(role, jamo, jung, has_jong):
    """(정밀 키, fallback 키)"""
    d, b = vowel_dir(jung), int(has_jong)
    if role == "jong":
        return f"jong|{d}|{jamo}", f"jong|{d}|*"
    return f"{role}|{jung}|{b}", f"{role}|{d}|{b}"


def delta_key(jamo):
    return f"jong|+|{jamo}"


def plus(gen_box, delta_box):
    return (np.array(gen_box) + np.array(delta_box)).round(4).tolist()


def lookup_slot(slots, role, jamo, jung, has_jong):
    """자모 박스 → (박스, 키 이름)"""
    exact, fb = keys_of(role, jamo, jung, has_jong)
    if exact in slots and slots[exact]["n"] >= MIN_N:
        return slots[exact]["box"], exact
    dk = delta_key(jamo)
    if role == "jong" and dk in slots and slots[dk]["n"] >= DELTA_MIN_N:
        return plus(slots[fb]["box"], slots[dk]["box"]), f"{fb}+{jamo}"
    return slots[fb]["box"], fb


def is_fallback(key):
    """일반 박스만 쓴 키인가 (정밀 키도, 받침 차이도 없음)"""
    parts = key.split("|")
    return key.endswith("|*") or (parts[0] != "jong" and parts[1] in ("V", "H", "C"))


# ═════════ ② 폰트별 세부 (detail.json, box_mode.json) ═════════
# 자모 박스 안에서 부품·획이 놓이는 위치 (그 폰트에서 측정)
# 같은 자리라도 폰트마다 자모 안 획 간격이 다르다.
#   예) Noto: 받침 있는 ㅝ(뒁)는 ㅓ 가로획이 ㅜ 가로획보다 0.09 아래
# 자모마다 방식(box_mode.json, extract.py mode 단계가 교차 검증으로 고름):
#   jamo   자모 박스 하나에 단독 자모 모양 그대로
#   piece  부품마다 측정된 박스 (ㅘ = ㅗ 박스 + ㅏ 박스)       키: <자리>|p<부품>
#   stroke 획마다 측정된 박스                                  키: <자리>|s<획>
#   초성 자리 키에는 자음이 없어서(cho|ㅏ|0 = 모든 초성) 부품·획 키에는 자음을 붙인다: cho|ㅏ|0|ㅂ|s2
# 그 자리에 측정값이 없으면(표본 < MIN_N) 자모 박스(① 칸 배치)로 돌아간다.
MODES = ("jamo", "piece", "stroke")
FLAT = 0.05  # 부품·획 점의 bbox 한 변이 자모 프레임에서 이보다 작으면 그 축은 0.5 (ㅡ·ㅣ 등)


def sub_base(role, jamo, jung, has_jong):
    """부품·획 키 앞부분 = 자모까지 정해진 자리 id (③ 자리 조정의 키이기도 함)"""
    exact = keys_of(role, jamo, jung, has_jong)[0]
    return f"{exact}|{jamo}" if role == "cho" else exact


def lookup_pieces(detail, slots, role, jamo, jung, has_jong):
    """부품별 박스 → (박스들, 키들) 또는 None
    정밀 자리 부품 → [종성] 일반 박스 + 받침 부품별 차이"""
    n = len(piece_sizes(jamo))
    if n < 2:
        return None
    sub = sub_base(role, jamo, jung, has_jong)
    ks = [f"{sub}|p{i}" for i in range(n)]
    if all(k in detail and detail[k]["n"] >= MIN_N for k in ks):
        return [detail[k]["box"] for k in ks], ks
    fb = keys_of(role, jamo, jung, has_jong)[1]
    dks = [f"{delta_key(jamo)}|p{i}" for i in range(n)]
    if role == "jong" and all(k in detail and detail[k]["n"] >= DELTA_MIN_N for k in dks):
        return ([plus(slots[fb]["box"], detail[k]["box"]) for k in dks], [f"{fb}+{jamo}|p{i}" for i in range(n)])
    return None


def lookup_strokes(detail, role, jamo, jung, has_jong, n_strokes):
    """획별 박스 → (박스들, 키들) 또는 None (모든 획 표본 ≥ MIN_N일 때만)"""
    sub = sub_base(role, jamo, jung, has_jong)
    ks = [f"{sub}|s{i}" for i in range(n_strokes)]
    if all(k in detail and detail[k]["n"] >= MIN_N for k in ks):
        return [detail[k]["box"] for k in ks], ks
    return None


# ═════════ ③ 수동 조정 (tweaks.json, editor.py로 편집) ═════════
# 측정값(①②) 위에 점마다 이동량(dx, dy)을 더한다. 측정을 다시 해도 조정은 그대로 남는다.
# 범위 두 가지:
#   slot      같은 자리 전체 — 자리 id(sub_base, 예: jung|ㅝ|1 = 받침 있는 ㅝ)의 자모 안 획 번호마다
#   syllable  그 글자만 — 글자의 획 순서(order)마다
# 형식:
#   {"slot":     {"jung|ㅝ|1": {"2": [[dx, dy] × 32]}},
#    "syllable": {"뒁": {"5": [[dx, dy] × 32]}}}
# 같은 획에 둘 다 있으면 둘 다 더한다 (자리 조정 + 글자 조정).
EPS = 1e-4  # 이보다 작은 이동은 0으로 보고 저장하지 않음


def deltas_for(tweaks, slot, idx, syl, order):
    """한 획에 더할 (자리 조정, 글자 조정) — 없으면 None"""
    a = tweaks.get("slot", {}).get(slot, {}).get(str(idx))
    b = tweaks.get("syllable", {}).get(syl, {}).get(str(order))
    return a, b


def apply_tweak(points, slot_d, syl_d):
    p = np.asarray(points, float)
    for d in (slot_d, syl_d):
        if d is not None:
            p = p + np.asarray(d, float)
    return p


def set_delta(tweaks, scope, key, idx, deltas):
    """scope = "slot"(key = 자리 id, idx = 자모 안 획 번호) / "syllable"(key = 글자, idx = order)
    이동이 전부 0이면 지운다"""
    table = tweaks.setdefault(scope, {})
    d = np.asarray(deltas, float).round(4)
    if np.abs(d).max(initial=0) < EPS:
        table.get(key, {}).pop(str(idx), None)
        if key in table and not table[key]:
            del table[key]
    else:
        table.setdefault(key, {})[str(idx)] = d.tolist()


def tweak_summary(tweaks):
    return {scope: {k: sorted(v, key=int) for k, v in tweaks.get(scope, {}).items()} for scope in ("slot", "syllable")}


# ═════════ 조합 ═════════
def to_box(pts_list, box, flat=None):
    """0~1 점들 → 박스. flat이 주어지면 점들의 bbox를 먼저 0~1로 다시 맞춤 (부품·획용)"""
    x0, y0, x1, y1 = box
    if flat is not None:
        allp = np.vstack(pts_list)
        lo, span = allp.min(0), np.ptp(allp, 0)
        pts_list = [np.where(span < flat, 0.5, (p - lo) / np.where(span < flat, 1, span)) for p in pts_list]
    return [np.c_[x0 + p[:, 0] * (x1 - x0), y0 + p[:, 1] * (y1 - y0)] for p in pts_list]


def place_jamo(prof, role, jamo, jung, has_jong, mode=None, slots=None, detail=None):
    """자모 하나를 자리에 놓기 (①②) → [(점들, 키)]"""
    slots = prof.slots if slots is None else slots
    detail = prof.detail if detail is None else detail
    strokes = prof.jamo[jamo]
    raw = [np.array(s["points"]) for s in strokes]
    m = mode or prof.box_mode.get(jamo, "jamo")

    if m == "stroke":  # ② 획마다
        sb = lookup_strokes(detail, role, jamo, jung, has_jong, len(strokes))
        if sb:
            return [(to_box([p], box, FLAT)[0], k) for p, box, k in zip(raw, *sb, strict=False)]
    if m == "piece":  # ② 부품마다
        pc = lookup_pieces(detail, slots, role, jamo, jung, has_jong)
        if pc:
            out = []
            for pi, (box, k) in enumerate(zip(*pc, strict=False)):
                mine = [p for p, s in zip(raw, strokes, strict=False) if s["unit"] == f"p{pi}"]
                out += [(q, k) for q in to_box(mine, box, FLAT)]
            return out
    box, k = lookup_slot(slots, role, jamo, jung, has_jong)  # ① 자모 박스
    return [(q, k) for q in to_box(raw, box)]


def compose(syl, font=None, mode=None, use_tweaks=True, meta=False, slots=None, detail=None):
    """음절 → [{"order", "jamo", "role", "points"}] (0~1 글자 프레임)
    mode: None = 자모마다 box_mode / "jamo"·"piece"·"stroke" 고정 (평가용)
    meta=True: 획마다 key(쓴 박스), slot(자리 id), idx(자모 안 획 번호), base(③ 전 점)도 넣음
    slots·detail: 다른 배치표로 시험할 때 (평가용)"""
    prof = get_profile(font)
    parts = decompose(syl)
    jung, has_jong = parts[1][1], len(parts) == 3
    out: list[dict[str, Any]] = []
    for role, jamo in parts:
        slot = sub_base(role, jamo, jung, has_jong)
        placed = place_jamo(prof, role, jamo, jung, has_jong, mode, slots, detail)
        for idx, (pts, key) in enumerate(placed):
            order = len(out) + 1
            final = pts
            if use_tweaks:  # ③ 수동 조정
                final = apply_tweak(pts, *deltas_for(prof.tweaks, slot, idx, syl, order))
            st = {"order": order, "jamo": jamo, "role": role, "points": np.round(final, 4).tolist()}
            if meta:
                st.update(key=key, slot=slot, idx=idx, base=np.round(pts, 4).tolist())
            out.append(st)
    return out


def jamo_role(jamo):
    """자모 단독 글자의 role: 자음 cho / 모음 jung / 겹받침(초성에 못 오는 것) jong"""
    return "cho" if jamo in CHO else "jung" if jamo in JUNG else "jong"


def jamo_box(jamo, font=None):
    """자모 단독 글리프가 글자 상자 안에서 차지하는 상자 [x0, y0, x1, y1] (0~1 글자 프레임, 폰트 윤곽 기준)"""
    from fontTools.pens.boundsPen import BoundsPen
    from fontTools.ttLib import TTFont

    info = font_info(font)
    tt = TTFont(info["file"])
    glyphs = tt.getGlyphSet()
    pen = BoundsPen(glyphs)
    glyphs[tt.getBestCmap()[ord(jamo)]].draw(pen)
    x0, y0, x1, y1 = pen.bounds
    upm, top = info["upm"], info["em_top"]
    return [x0 / upm, (top - y1) / upm, x1 / upm, (top - y0) / upm]


def compose_jamo(jamo, font=None, box=None):
    """자모 단독 글자 (초보 자모 연습: ㄱ, ㅏ …) → [{"order", "jamo", "role", "points"}] (0~1 글자 프레임)
    jamo_strokes 모양을 그 폰트의 자모 글리프 상자에 맞춰 놓는다"""
    prof = get_profile(font)
    box = jamo_box(jamo, font) if box is None else box
    pts = to_box([np.array(s["points"]) for s in prof.jamo[jamo]], box)
    role = jamo_role(jamo)
    return [{"order": i + 1, "jamo": jamo, "role": role, "points": np.round(p, 4).tolist()} for i, p in enumerate(pts)]


def compose_all(font=None, use_tweaks=True):
    """정답 획 사전: 현대 한글 11,172자 + 자모 단독 51개 → composed_all.json, 저장 경로 반환"""
    prof = get_profile(font)
    table = {c: compose(c, font, use_tweaks=use_tweaks) for c in all_syllables()}
    table.update({j: compose_jamo(j, font) for j in prof.jamo})
    path = composed_path(font)
    write_json(path, table)
    return path, len(table)


# ═════════ 그림 ═════════
def glyph_patch(syl, prof, size):
    """원래 폰트 글자 (배경용)"""
    from matplotlib.font_manager import FontProperties
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MPath
    from matplotlib.textpath import TextPath

    f, upm, top = prof.meta["file"], prof.meta["upm"], prof.meta["em_top"]
    tp = TextPath((0, 0), syl, size=upm, prop=FontProperties(fname=f))
    v = tp.vertices.copy()
    v[:, 0] = v[:, 0] / upm * size
    v[:, 1] = (top - v[:, 1]) / upm * size
    return PathPatch(MPath(v, tp.codes), fc="0.85", ec="none")


def draw(chars, out=OUTPUTS_DIR / "compose.png", cols=10, font=None, use_tweaks=True):
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    prof = get_profile(font)
    f = prof.meta["file"]  # 제목 한글 표시
    font_manager.fontManager.addfont(f)
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=f).get_name()
    size = 256
    Path(out).parent.mkdir(parents=True, exist_ok=True)

    rows = (len(chars) + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(1.9 * cols, 2.0 * rows), squeeze=False)
    colors = plt.get_cmap("tab10").colors  # type: ignore[attr-defined]  # ListedColormap
    for ax, syl in zip(axes.flat, chars, strict=False):
        ax.set_xlim(0, size)
        ax.set_ylim(size, 0)
        ax.set_aspect("equal")
        g = glyph_patch(syl, prof, size)
        if g is not None:
            ax.add_patch(g)
        strokes = compose(syl, font, use_tweaks=use_tweaks, meta=True)
        fb = any(is_fallback(s["key"]) for s in strokes)
        tw = use_tweaks and any(s["points"] != s["base"] for s in strokes)
        ax.set_title(
            syl + (" (fb)" if fb else "") + (" (조정)" if tw else ""), fontsize=11, color="tab:blue" if fb else "black"
        )
        ax.axis("off")
        for s in strokes:
            p = np.array(s["points"]) * size
            col = colors[(s["order"] - 1) % len(colors)]
            ax.plot(p[:, 0], p[:, 1], color=col, lw=1.5)
            ax.annotate("", xy=p[-1], xytext=p[-3], arrowprops=dict(arrowstyle="-|>", color=col, lw=1))
            v = p[1] - p[0]
            v = v / (np.hypot(*v) + 1e-9)
            ax.text(
                *(p[0] - v * 12),
                str(s["order"]),
                color="white",
                fontsize=6,
                ha="center",
                va="center",
                bbox=dict(boxstyle="circle,pad=0.15", fc=col, ec="none"),
            )
    for ax in axes.flat[len(chars) :]:
        ax.axis("off")
    plt.tight_layout()
    plt.savefig(out, dpi=100)
    plt.close(fig)
    print(f"{len(chars)}자 → {relative_to_root(out)}  (제목 (fb) = 일반 박스 사용, (조정) = 수동 조정 있음)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("chars", nargs="*")
    ap.add_argument("--font", help="폰트 (data/fonts/ 안의 파일 이름 또는 경로, 기본 NotoSansKR-Light)")
    ap.add_argument("--all", action="store_true", help="정답 획 사전 만들기 (11,172자 + 자모 51개) → composed_all.json")
    ap.add_argument("--full", action="store_true", help="무작위 그림을 11,172자 중에서 (기본 완성형 2,350자)")
    ap.add_argument("--n", type=int, default=50, help="글자 안 주면 무작위 N자")
    ap.add_argument("--seed", type=int, default=None, help="무작위 시드 (안 주면 매번 다름)")
    ap.add_argument("--no-tweaks", action="store_true", help="③ 수동 조정 빼고")
    ap.add_argument("--cols", type=int, default=10)
    ap.add_argument("--out", default=str(OUTPUTS_DIR / "compose.png"))
    args = ap.parse_args()
    tw = not args.no_tweaks

    if args.all:
        path, n = compose_all(args.font, use_tweaks=tw)
        print(f"{n}자 → {relative_to_root(path)}")
    else:
        chars = [c for a in args.chars for c in a]  # "뒁 깜" / "뒁깜" 둘 다
        if not chars:
            import random

            pool = all_syllables() if args.full else ksx1001()
            chars = random.Random(args.seed).sample(pool, min(args.n, len(pool)))
        draw(chars, args.out, args.cols, args.font, tw)
