"""
필기 테스트 서버 (로컬 전용): 화면에 글자를 써서 획순·균형 판정을 확인
(app/services/stroke_checker.py, stroke_balance.py)

  python -m scripts.hand_writing_confirm [--port 5000]   → http://localhost:5000

정답은 서버와 같은 정답 획 사전(core/reference.py, composed_all.json)에서 꺼낸다.
editor로 고친 뒤에는 python -m app.core.stroke_vectorizer.compose --all 을 해야 여기에도 반영된다.

  GET  /           pad.html (필기 화면)
  GET  /ref/<글자>  정답 획 (정답 획 사전, 가이드 표시용)
  POST /judge      입력 JSON (+ "mode": "order" | "balance" | "both") → 판정 결과 JSON
                   order = 획순(stroke_checker.judge), balance = 균형(stroke_balance.py), both = 둘 다
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.core.reference import get_reference
from app.services import stroke_balance as balance
from app.services.stroke_checker import judge

HERE = Path(__file__).resolve().parent

MODES = ("order", "balance", "both")


def reference(char):
    """정답 획 사전에서 꺼낸 정답 → judge()·balance·pad.html이 쓰는 dict 형식"""
    return [s.model_dump(mode="json") for s in get_reference(char)]


def evaluate(req):
    """mode에 따라 획순·균형 판정. 균형은 획순 엔진의 짝짓기(strokeMap)로 자모를 묶으므로 항상 획순 엔진을 돌린다
    → {"target", "mode", "pass", "strokeMap", "order"?: 획순 결과, "balance"?: {"pass", "errors"}}"""
    mode = req.get("mode", "order")
    if mode not in MODES:
        raise ValueError(f"mode는 {MODES} 중 하나: {mode}")
    ref = reference(req["target"])
    o = judge(req, ref=ref)
    out = {"target": req["target"], "mode": mode, "strokeMap": o["strokeMap"], "durationMs": o["durationMs"]}
    ok = True
    if mode in ("order", "both"):
        out["order"] = o
        ok &= o["pass"]
    if mode in ("balance", "both"):
        b = balance.check(req, ref, o["strokeMap"])
        out["balance"] = {"pass": not b, "errors": b, "margin": balance.JAMO_MARGIN}
        ok &= not b
    out["pass"] = ok
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, ctype="application/json; charset=utf-8", code=200):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        try:
            if path == "/":
                self.send((HERE / "pad.html").read_bytes(), "text/html; charset=utf-8")
            elif path.startswith("/ref/"):
                self.send(reference(path[len("/ref/") :]))
            else:
                self.send({"error": "not found"}, code=404)
        except Exception as e:  # noqa: BLE001
            self.send({"error": f"{type(e).__name__}: {e}"}, code=400)

    def do_POST(self):
        if urlparse(self.path).path != "/judge":
            return self.send({"error": "not found"}, code=404)
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n) or b"{}")
            self.send(evaluate(req))
        except Exception as e:  # noqa: BLE001
            self.send({"error": f"{type(e).__name__}: {e}"}, code=400)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5000)
    args = ap.parse_args()
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError as e:
        raise SystemExit(f"포트 {args.port}을 이미 쓰는 중 → --port {args.port + 1}") from e
    print(f"필기 테스트: http://localhost:{args.port}  (정답: 정답 획 사전, 끝내려면 Ctrl+C)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
