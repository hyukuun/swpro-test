"""
검수 스크립트 공용: 그림 그리기·선분 출력 (debug.py, jamo_check.py가 씀)
"""

import matplotlib.pyplot as plt
import numpy as np
from matplotlib import font_manager

from app.core.stroke_vectorizer.extract import N_POINTS, chain_points, poly_len, resample, seg_angle


def use_plot_font(path):
    """그래프 제목 한글 깨짐 방지"""
    path = str(path)
    font_manager.fontManager.addfont(path)
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=path).get_name()


def draw_strokes(ax, img, strokes, title, fontsize=8):
    """획별 색 + 시작점 번호 + 끝 화살표"""
    colors = plt.get_cmap("tab10").colors  # type: ignore[attr-defined]  # ListedColormap
    ax.imshow(img, cmap="Greys", alpha=0.25)
    ax.set_title(title if strokes else f"{title} (실패)", color="black" if strokes else "red")
    ax.axis("off")
    if not strokes:
        return
    for k, c in enumerate(strokes):
        p = resample(chain_points(c), N_POINTS)
        col = colors[k % len(colors)]
        ax.plot(p[:, 0], p[:, 1], color=col, lw=2)
        ax.annotate("", xy=p[-1], xytext=p[-3], arrowprops=dict(arrowstyle="-|>", color=col, lw=1.5))
        v = p[1] - p[0]
        v = v / (np.hypot(*v) + 1e-9)
        ax.text(
            *(p[0] - v * 10),
            str(k + 1),
            color="white",
            fontsize=fontsize,
            ha="center",
            va="center",
            bbox=dict(boxstyle="circle,pad=0.2", fc=col, ec="none"),
        )


def print_segments(segs):
    for n, s in enumerate(segs):
        a = s["arr"]
        tag = "고리" if s["loop"] else f"각도 {seg_angle(a):6.1f}"
        minor = " (짧음)" if s["minor"] else ""
        print(f"    #{n:<2} 덩어리{s['comp']}  {a[0].round()} → {a[-1].round()}  {tag}  길이 {poly_len(a):.0f}{minor}")
