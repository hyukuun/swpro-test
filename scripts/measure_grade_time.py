"""/grade 판정 시간 재기. 백엔드에 알려 줄 제한 시간(지금은 가정 5초)을 정하는 데 쓴다.

실행 (프로젝트 루트에서)
  python -m scripts.measure_grade_time                       # 엔진을 이 프로세스 안에서 바로 불러 잼 (판정 시간만)
  python -m scripts.measure_grade_time --url http://127.0.0.1:8000   # 띄워 둔 서버에 요청 (네트워크 포함)
    Windows에서 'localhost'로 부르면 IPv6(::1)를 먼저 시도하다 요청마다 약 2초가 더 걸린다. 127.0.0.1이나 IP로 부를 것
  --repeat 20   요청 종류마다 몇 번 잴지
  --points 64   '가장 큰 요청'에서 획 하나에 찍을 점 개수 (Apple Pencil은 획 하나에 수십~수백 개)

재는 요청
- beginner / intermediate / advanced : 피그마 예시 요청 (tests/fixtures/)
- largest : 가장 큰 요청. 고수, 정답 19칸, 원고지 30칸, 모든 글자를 정답 획대로 써서 모든 칸이 획 판정을 거침

첫 요청은 정답 획 사전(약 68MB)을 읽느라 느리다. 그래서 '첫 요청'을 따로 보여 주고, 나머지로 중앙값·p95·최대를 낸다.
정답 획 사전이 없으면 획 판정을 건너뛰므로 실제보다 빠르게 나온다 (경고를 띄운다).
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"
CANVAS = 96  # 원고지 칸 하나 크기(px), 피그마 예시와 같음
LARGEST_TARGET = "닭볶음탕 먹고 싶었어 정말 맛있겠다"  # 19칸, 획이 많은 글자 위주
LARGEST_CELLS = 30


def fixture_request(stage: str) -> dict:
    return json.loads((FIXTURES / f"grade_request_{stage}.json").read_text(encoding="utf-8"))


def _resample(points: list[tuple[float, float]], n: int) -> list[tuple[float, float]]:
    """획 중심선을 점 n개로 고르게 다시 찍는다 (정답 획은 32개라 실제 펜보다 적음)."""
    out = []
    for k in range(n):
        pos = k * (len(points) - 1) / (n - 1)
        i = min(int(pos), len(points) - 2)
        f = pos - i
        (x0, y0), (x1, y1) = points[i], points[i + 1]
        out.append((x0 + (x1 - x0) * f, y0 + (y1 - y0) * f))
    return out


def largest_request(points_per_stroke: int) -> dict:
    """가장 큰 요청: 모든 글자를 정답 획대로 쓴 고수 원고지 30칸."""
    from app.core.reference import get_reference

    cells = []
    t = 0.0
    for i in range(LARGEST_CELLS):
        ch = LARGEST_TARGET[i] if i < len(LARGEST_TARGET) else " "
        strokes = []
        if ch != " ":
            for s in get_reference(ch):
                pts = []
                for x, y in _resample(list(s.points), points_per_stroke):
                    pts.append([x * CANVAS, y * CANVAS, t, 0.5])
                    t += 5
                strokes.append({"points": pts})
                t += 200  # 획 사이 쉬는 시간
        cells.append({"index": i, "strokes": strokes})
    return {
        "sessionId": "measure-largest",
        "stage": "advanced",
        "target": LARGEST_TARGET,
        "canvas": {"w": CANVAS, "h": CANVAS},
        "cells": cells,
    }


def in_process_sender() -> Callable[[dict], int]:
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    return lambda body: client.post("/grade", json=body).status_code


def http_sender(base_url: str) -> Callable[[dict], int]:
    url = base_url.rstrip("/") + "/grade"

    def send(body: dict) -> int:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as res:
            res.read()
            return int(res.status)

    return send


def timed(send: Callable[[dict], int], body: dict) -> float:
    start = time.perf_counter()
    status = send(body)
    elapsed = (time.perf_counter() - start) * 1000
    if status != 200:
        raise SystemExit(f"/grade가 {status}을 돌려줌 (요청 {body.get('sessionId')})")
    return elapsed


def p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]


def main() -> None:
    parser = argparse.ArgumentParser(description="/grade 판정 시간 재기")
    parser.add_argument("--url", help="띄워 둔 엔진 주소 (예: http://localhost:8000). 없으면 프로세스 안에서 바로 부름")
    parser.add_argument("--repeat", type=int, default=20, help="요청 종류마다 잴 횟수 (기본 20)")
    parser.add_argument("--points", type=int, default=64, help="가장 큰 요청의 획 하나당 점 개수 (기본 64)")
    args = parser.parse_args()

    from app.pipeline import reference_available

    if not reference_available():
        raise SystemExit(
            "정답 획 사전이 없어 획 판정을 건너뛰므로 시간을 잴 수 없어요.\n"
            "  먼저 실행: python -m app.core.stroke_vectorizer.extract\n"
            "  그다음:    python -m app.core.stroke_vectorizer.compose --all"
        )

    send = http_sender(args.url) if args.url else in_process_sender()
    where = args.url or "프로세스 안 (네트워크 제외)"
    requests = {stage: fixture_request(stage) for stage in ("beginner", "intermediate", "advanced")}
    # 첫 요청: 정답 획 사전 읽기 포함. largest_request가 사전을 읽기 전에 잰다
    # (--url이면 서버를 띄운 뒤 처음 보내는 요청이어야 의미가 있음)
    first = timed(send, requests["beginner"])
    requests["largest"] = largest_request(args.points)

    print(f"엔진: {where}, 종류마다 {args.repeat}번")
    print(f"첫 요청 (정답 획 사전 읽기 포함): {first:,.0f} ms\n")
    print(f"{'요청':<14}{'칸':>4}{'획':>5}{'중앙값':>10}{'p95':>10}{'최대':>10}  (ms)")
    for name, body in requests.items():
        times = [timed(send, body) for _ in range(args.repeat)]
        n_cells = len(body["cells"])
        n_strokes = sum(len(c["strokes"]) for c in body["cells"])
        print(
            f"{name:<14}{n_cells:>4}{n_strokes:>5}"
            f"{statistics.median(times):>10.1f}{p95(times):>10.1f}{max(times):>10.1f}"
        )


if __name__ == "__main__":
    main()
