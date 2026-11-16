"""
자모 51개(자음 19 + 모음 21 + 겹받침 11) 단독 글리프로 템플릿 검사
→ outputs/jamo_check.png (다른 폰트면 outputs/jamo_check_<id>.png)

사용법:
  python -m scripts.jamo_check
  python -m scripts.jamo_check --font DONGGUK-UNIVERSITY
"""

import argparse

import matplotlib.pyplot as plt

from app.core.stroke_vectorizer import compose as C
from app.core.stroke_vectorizer.extract import SearchLimit, add_font_args, assign, extract_segments, load_font
from app.core.stroke_vectorizer.jamo_templates import JAMO_TEMPLATES, jamo_entries
from scripts.drawing import draw_strokes, print_segments, use_plot_font

ap = argparse.ArgumentParser()
add_font_args(ap)
args = ap.parse_args()
use_plot_font(load_font(args)[1]["file"])
OUT = C.OUTPUTS_DIR / (
    "jamo_check.png" if C.font_id(args.font) == C.font_id() else f"jamo_check_{C.font_id(args.font)}.png"
)

JAMOS = list(JAMO_TEMPLATES)
COLS = 10
rows = (len(JAMOS) + COLS - 1) // COLS
fig, axes = plt.subplots(rows, COLS, figsize=(2.2 * COLS, 2.4 * rows))
fails = []

for ax, j in zip(axes.flat, JAMOS, strict=False):
    img, segs = extract_segments(j)
    entries = jamo_entries(j, "cho")
    try:
        strokes = assign(entries, segs)
    except SearchLimit:
        strokes = None
    draw_strokes(ax, img, strokes, j, fontsize=7)
    if not strokes:
        fails.append(j)
        print(f"[실패] {j}: 템플릿 {len(entries)}획, 선분 {len(segs)}개")
        print_segments(segs)

for ax in axes.flat[len(JAMOS) :]:
    ax.axis("off")
plt.tight_layout()
OUT.parent.mkdir(parents=True, exist_ok=True)
plt.savefig(OUT, dpi=110)
print(f"→ {C.relative_to_root(OUT)}  성공 {len(JAMOS) - len(fails)}/{len(JAMOS)}, 실패: {''.join(fails) or '없음'}")
