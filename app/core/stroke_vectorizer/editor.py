"""
③ 수동 조정 편집기 (로컬 웹 UI)

  python -m app.core.stroke_vectorizer.editor [--font <폰트>] [--port 8765]   → 브라우저에서 http://localhost:8765

화면에서 획을 고르고 점을 끌어 옮긴 뒤 저장하면 data/extracted/<폰트>/tweaks.json에 이동량이 저장된다.
범위: "이 글자만" 또는 "같은 자리 전체"(예: 받침 있는 ㅝ 전부). 반영 방식: docs/extracted_data.md
다 고친 뒤 python -m app.core.stroke_vectorizer.compose --all 로 정답 획 사전을 다시 만들어야 서버에 반영된다.
"""

import argparse
import json
import random
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.core.stroke_vectorizer.compose import (
    Profile,
    compose,
    deltas_for,
    get_profile,
    set_delta,
    sub_base,
    tweak_summary,
)
from app.core.stroke_vectorizer.jamo_templates import all_syllables, decompose, ksx1001

HERE = Path(__file__).parent
KSX = set(ksx1001())


def slot_of(syl):
    """글자의 자리 id 목록 (초·중·종)"""
    parts = decompose(syl)
    jung, has_jong = parts[1][1], len(parts) == 3
    return [sub_base(r, j, jung, has_jong) for r, j in parts]


def syl_view(prof, syl):
    """편집용: 획마다 base(①② 결과) + 자리 조정 + 글자 조정"""
    strokes = compose(syl, prof.id, meta=True, use_tweaks=False)
    for s in strokes:
        s["slot_d"], s["syl_d"] = deltas_for(prof.tweaks, s["slot"], s["idx"], syl, s["order"])
        del s["points"]
    return {"syl": syl, "strokes": strokes}


def same_slot(slot, n, exclude):
    """같은 자리를 쓰는 글자 (완성형 먼저)"""
    hits = [c for c in all_syllables() if c != exclude and slot in slot_of(c)]
    hits.sort(key=lambda c: c not in KSX)
    ksx = [c for c in hits if c in KSX]
    pick = random.Random(slot).sample(ksx, min(n, len(ksx)))
    if len(pick) < n:
        pick += [c for c in hits if c not in KSX][: n - len(pick)]
    return pick, len(hits)


class Handler(BaseHTTPRequestHandler):
    prof: Profile  # 실행할 때 main에서 정함

    def log_message(self, *a):
        pass

    def send(self, body, ctype="application/json; charset=utf-8", code=200):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        p = self.prof
        try:
            if u.path == "/":
                self.send((HERE / "editor.html").read_bytes(), "text/html; charset=utf-8")
            elif u.path == "/font":
                self.send(Path(p.meta["file"]).read_bytes(), "font/ttf")
            elif u.path == "/api/meta":
                self.send(
                    {
                        "font": p.id,
                        "name": p.meta.get("name", p.id),
                        "upm": p.meta["upm"],
                        "em_top": p.meta["em_top"],
                    }
                )
            elif u.path == "/api/syl":
                self.send(syl_view(p, q["c"]))
            elif u.path == "/api/many":
                self.send([syl_view(p, c) for c in q["c"] if 0xAC00 <= ord(c) <= 0xD7A3])
            elif u.path == "/api/slot_chars":
                chars, total = same_slot(q["slot"], int(q.get("n", 12)), q.get("exclude"))
                self.send({"chars": "".join(chars), "total": total})
            elif u.path == "/api/tweaks":
                self.send(tweak_summary(p.tweaks))
            else:
                self.send({"error": "not found"}, code=404)
        except Exception as e:  # noqa: BLE001
            self.send({"error": f"{type(e).__name__}: {e}"}, code=400)

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n) or b"{}")
        p = self.prof
        try:
            if u.path == "/api/save":
                # body: {"syl", "edits": [{"order", "slot_d": [[dx,dy]×32] | null, "syl_d": ... }]}
                syl = body["syl"]
                meta = {s["order"]: s for s in compose(syl, p.id, meta=True, use_tweaks=False)}
                for e in body["edits"]:
                    s = meta[e["order"]]
                    if "slot_d" in e:
                        set_delta(p.tweaks, "slot", s["slot"], s["idx"], e["slot_d"] or [[0, 0]])
                    if "syl_d" in e:
                        set_delta(p.tweaks, "syllable", syl, s["order"], e["syl_d"] or [[0, 0]])
                p.save_tweaks()
                self.send(syl_view(p, syl))
            else:
                self.send({"error": "not found"}, code=404)
        except Exception as e:  # noqa: BLE001
            self.send({"error": f"{type(e).__name__}: {e}"}, code=400)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--font", help="폰트 (data/fonts/ 안의 파일 이름 또는 경로, 기본 NotoSansKR-Light)")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    Handler.prof = get_profile(args.font)
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as e:
        raise SystemExit(
            f"포트 {args.port}을 이미 다른 프로세스가 쓰는 중입니다.\n"
            f"  확인: ss -ltnp | grep :{args.port}\n"
            f"  다른 포트로: python -m app.core.stroke_vectorizer.editor --port {args.port + 1}"
        ) from e
    print(f"편집기: http://localhost:{args.port}  (폰트 {Handler.prof.id}, 저장 → {Handler.prof.dir / 'tweaks.json'})")
    print("끝내려면 Ctrl+C")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
