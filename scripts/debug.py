"""
실패 글자 디버그: 선분 번호를 그림에 표시하고, 템플릿·선분 목록을 출력
사용법:
  python -m scripts.debug 거 어 오 호
  python -m scripts.debug ㄴ ㅏ ㅘ          # 자모 단독 글리프도 됨
  python -m scripts.debug --font DONGGUK-UNIVERSITY 거 어
→ outputs/debug.png (다른 폰트면 outputs/debug_<id>.png, 위: 선분 번호, 아래: 배정 결과)
"""

import argparse

import matplotlib.pyplot as plt

from app.core.stroke_vectorizer import compose as C
from app.core.stroke_vectorizer.extract import SearchLimit, add_font_args, assign, extract_segments, load_font
from app.core.stroke_vectorizer.jamo_templates import JAMO_TEMPLATES, decompose, jamo_entries, syllable_template
from scripts.drawing import draw_strokes, print_segments, use_plot_font

ap = argparse.ArgumentParser()
ap.add_argument("chars", nargs="*")
add_font_args(ap)
args = ap.parse_args()
use_plot_font(load_font(args)[1]["file"])
OUT = C.OUTPUTS_DIR / ("debug.png" if C.font_id(args.font) == C.font_id() else f"debug_{C.font_id(args.font)}.png")
chars = [c for a in args.chars for c in a] or ["거", "어", "오", "호"]
fig, axes = plt.subplots(2, len(chars), figsize=(3.2 * len(chars), 6.4), squeeze=False)
colors = plt.get_cmap("tab20").colors  # type: ignore[attr-defined]  # ListedColormap

for col, syl in enumerate(chars):
    img, segs = extract_segments(syl)
    is_jamo = syl in JAMO_TEMPLATES  # 자모 단독 (ㄴ, ㅘ …)
    entries = jamo_entries(syl, "cho") if is_jamo else syllable_template(syl)

    # 위: 선분마다 색 + 번호
    ax = axes[0][col]
    ax.imshow(img, cmap="Greys", alpha=0.25)
    ax.set_title(f"{syl} 선분 {len(segs)}개")
    ax.axis("off")
    for n, s in enumerate(segs):
        a = s["arr"]
        c = colors[n % len(colors)]
        ax.plot(a[:, 0], a[:, 1], color=c, lw=1 if s["minor"] else 2, ls="--" if s["loop"] else "-")
        mid = a[len(a) // 2]
        ax.text(
            mid[0],
            mid[1],
            str(n),
            fontsize=7,
            color="black",
            bbox=dict(boxstyle="round,pad=0.1", fc="white", ec=c, alpha=0.8),
        )

    # 아래: 배정 결과
    try:
        strokes = assign(entries, segs)
        reason = "" if strokes else " (배정 실패)"
    except SearchLimit:
        strokes, reason = None, " (탐색 초과)"
    draw_strokes(axes[1][col], img, strokes, syl + reason)

    # 콘솔 출력
    parts = syl if is_jamo else "+".join(j for _, j in decompose(syl))
    print(f"\n=== {syl} ({parts}){reason or ' 성공'}")
    print("  템플릿:")
    for k, e in enumerate(entries):
        print(f"    {k + 1}획  {e['jamo']}({e['unit']})  {e['dirs']}")
    print("  선분:")
    print_segments(segs)

plt.tight_layout()
OUT.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(OUT, dpi=110)
print(f"\nsaved {C.relative_to_root(OUT)}")
