"""b6g-edge-infer, version de remplacement (MAQUETTE) conforme au contrat I-10 (contracts/openapi/edge-infer.yaml).

Sert à valider le chemin de déploiement et CT-09 en attendant l'image du modèle de l'équipe 2 (M20) : la « prédiction »
est une règle à seuils, pas un modèle appris. Réalisme : MAQUETTE.

    GET  /v1/health     {"status": "ok", ...}
    POST /v1/infer      {"request_id", "features": {throughput_mbps, latency_ms_p95, loss_ratio, cpu_ratio}}
                        -> {"request_id", "prediction": congested|normal, "score", "model_version", "server_latency_ms"}
    GET  /metrics       b6g_app_request_latency_ms{app="b6g-edge-infer", tier, quantile}
"""
from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP, TIER, MODEL = "b6g-edge-infer", os.environ.get("B6G_TIER", "local"), "stub-seuils-0.1.0"
REQUIRED = ("throughput_mbps", "latency_ms_p95", "loss_ratio", "cpu_ratio")
_samples: deque[tuple[float, float]] = deque()
_lock = threading.Lock()


def score(f: dict) -> float:
    """Score de congestion dans [0, 1] : moyenne de quatre indicateurs bornés (règle de démonstration)."""
    parts = [min(f["latency_ms_p95"] / 100, 1), min(f["loss_ratio"] / 0.05, 1), min(f["cpu_ratio"], 1),
             min(f["throughput_mbps"] / 100, 1)]
    return round(sum(parts) / len(parts), 4)


def problem(status: int, title: str, detail: str) -> bytes:
    return json.dumps({"type": f"https://b6g.local/problems/{status}", "title": title, "status": status,
                       "detail": detail}).encode()


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in ("/v1/health", "/health"):   # /health : sonde de disponibilité du gabarit I-11
            self._send(200, json.dumps({"status": "ok", "app": APP, "tier": TIER, "model_version": MODEL}).encode())
        elif self.path == "/metrics":
            now = time.monotonic()
            with _lock:
                while _samples and now - _samples[0][0] > 30:
                    _samples.popleft()
                vals = sorted(v for _, v in _samples)
            lines = ["# TYPE b6g_app_request_latency_ms summary"]
            for q in (0.5, 0.95, 0.99):
                if vals:
                    lines.append(f'b6g_app_request_latency_ms{{app="{APP}",tier="{TIER}",quantile="{q}"}} '
                                 f'{vals[min(len(vals) - 1, int(q * len(vals)))]:.3f}')
            self._send(200, ("\n".join(lines) + "\n").encode(), "text/plain; version=0.0.4")
        else:
            self._send(404, problem(404, "Ressource inconnue", self.path), "application/problem+json")

    def do_POST(self) -> None:  # noqa: N802
        t0 = time.perf_counter()
        if self.path != "/v1/infer":
            self._send(404, problem(404, "Ressource inconnue", self.path), "application/problem+json")
            return
        if not self.headers.get("X-B6G-Caller"):
            self._send(400, problem(400, "En-tête X-B6G-Caller manquant", "obligatoire"), "application/problem+json")
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            f = body["features"]
            missing = [k for k in REQUIRED if not isinstance(f.get(k), (int, float))]
            if not isinstance(body.get("request_id"), str) or missing:
                raise ValueError(f"champs manquants ou invalides : {missing or ['request_id']}")
        except (ValueError, KeyError, TypeError) as e:
            self._send(400, problem(400, "Requête invalide", str(e)), "application/problem+json")
            return
        s = score(f)
        ms = (time.perf_counter() - t0) * 1000
        with _lock:
            _samples.append((time.monotonic(), ms))
        self._send(200, json.dumps({"request_id": body["request_id"], "prediction": "congested" if s >= 0.5 else "normal",
                                    "score": s, "model_version": MODEL, "server_latency_ms": round(ms, 3)}).encode())

    def log_message(self, *args) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
