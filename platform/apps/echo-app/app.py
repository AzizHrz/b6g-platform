"""b6g-echo-app (M07, T09.1) : application de test des ateliers 8, 9 et 10.

    GET /echo?size=N     renvoie N octets (défaut 64)
    GET /work?ms=M       consomme M ms de calcul (charge CPU pour l'auto-scaling)
    GET /health          {"status": "ok", "tier": ...}
    GET /metrics         b6g_app_request_latency_ms{app, tier, quantile} (I-02, résumé sur les 30 dernières secondes)

Variables : B6G_TIER (edge | fog | cloud, défaut « local »), PORT (défaut 8080).
Bibliothèque standard uniquement (image minimale).
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

APP = "b6g-echo-app"
TIER = os.environ.get("B6G_TIER", "local")
WINDOW_S = 30
_samples: deque[tuple[float, float]] = deque()
_lock = threading.Lock()
_count = 0


def record(ms: float) -> None:
    global _count
    now = time.monotonic()
    with _lock:
        _samples.append((now, ms))
        _count += 1
        while _samples and now - _samples[0][0] > WINDOW_S:
            _samples.popleft()


def quantiles() -> dict[str, float]:
    with _lock:
        vals = sorted(v for _, v in _samples)
    if not vals:
        return {}
    pick = lambda q: vals[min(len(vals) - 1, int(q * len(vals)))]  # noqa: E731
    return {"0.5": pick(0.5), "0.95": pick(0.95), "0.99": pick(0.99)}


def burn(ms: float) -> None:
    end = time.perf_counter() + ms / 1000
    x = 0
    while time.perf_counter() < end:
        x += 1


class Handler(BaseHTTPRequestHandler):
    server_version = "b6g-echo-app/0.1"

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - API de http.server
        t0 = time.perf_counter()
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/echo":
            size = min(int(q.get("size", ["64"])[0]), 10_000_000)
            self._send(200, b"x" * size, "application/octet-stream")
        elif url.path == "/work":
            burn(min(float(q.get("ms", ["10"])[0]), 5000))
            self._send(200, json.dumps({"tier": TIER, "host": os.uname().nodename}).encode())
        elif url.path == "/health":
            self._send(200, json.dumps({"status": "ok", "app": APP, "tier": TIER}).encode())
            return
        elif url.path == "/metrics":
            lines = ["# TYPE b6g_app_request_latency_ms summary"]
            for qq, v in quantiles().items():
                lines.append(f'b6g_app_request_latency_ms{{app="{APP}",tier="{TIER}",quantile="{qq}"}} {v:.3f}')
            lines.append(f'b6g_app_request_latency_ms_count{{app="{APP}",tier="{TIER}"}} {_count}')
            self._send(200, ("\n".join(lines) + "\n").encode(), "text/plain; version=0.0.4")
            return
        else:
            self._send(404, b'{"error": "not found"}')
            return
        record((time.perf_counter() - t0) * 1000)

    def log_message(self, *args) -> None:  # journal silencieux
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
