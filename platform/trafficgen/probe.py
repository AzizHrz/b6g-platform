"""Sondes trafficgen (M02, T03.2) : latence et perte par slice, publiées dans la Pushgateway (I-02).

Toutes les `--period` secondes, pour chaque slice : `ping` depuis le premier UE de la slice (interface
uesimtun0 du conteneur ue-<slice>) vers la passerelle de son UPF (première adresse du sous-réseau).
Publie b6g_slice_latency_ms{slice, quantile="0.5"|"0.95"} et b6g_slice_loss_ratio{slice}.

    .venv/bin/python platform/trafficgen/probe.py [--once] [--count 20] [--period 5]

Réalisme : ÉMULÉ (paquets réels à travers gNB, GTP-U et UPF ; pas de couche radio).
"""
from __future__ import annotations

import argparse
import ipaddress
import re
import statistics
import subprocess
import time

import httpx
from b6g_common import scenario as scn

RTT = re.compile(r"time=([\d.]+) ms")


def ping(container: str, dest: str, count: int, interval: float = 0.2) -> tuple[list[float], int]:
    """RTT (ms) des réponses reçues et nombre de requêtes envoyées."""
    res = subprocess.run(["docker", "exec", container, "ping", "-I", "uesimtun0", "-n", "-c", str(count),
                          "-i", str(interval), "-W", "1", dest], capture_output=True, text=True,
                         timeout=count * interval + 10)
    return [float(x) for x in RTT.findall(res.stdout)], count


def quantile(values: list[float], q: float) -> float:
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=100, method="inclusive")[int(q * 100) - 1]


def measure(sc: dict, count: int) -> dict[str, dict]:
    out = {}
    for s in sc["slices"]:
        gw = str(ipaddress.ip_network(s["subnet"])[1])
        rtts, sent = ping(f"ue-{s['id']}", gw, count)
        out[s["id"]] = {
            "p50": quantile(rtts, 0.5) if rtts else None,
            "p95": quantile(rtts, 0.95) if rtts else None,
            "loss": 1 - len(rtts) / sent,
        }
    return out


def exposition(m: dict[str, dict]) -> str:
    lines = ["# TYPE b6g_slice_latency_ms gauge", "# TYPE b6g_slice_loss_ratio gauge"]
    for sid, v in m.items():
        for q, key in (("0.5", "p50"), ("0.95", "p95")):
            if v[key] is not None:
                lines.append(f'b6g_slice_latency_ms{{slice="{sid}",quantile="{q}"}} {v[key]:.3f}')
        lines.append(f'b6g_slice_loss_ratio{{slice="{sid}"}} {v["loss"]:.4f}')
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pushgateway", default="http://127.0.0.1:9091")
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--period", type=float, default=5)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    sc = scn.load()
    url = f"{args.pushgateway.rstrip('/')}/metrics/job/trafficgen"
    while True:
        t0 = time.monotonic()
        m = measure(sc, args.count)
        httpx.put(url, content=exposition(m), timeout=5).raise_for_status()
        print(time.strftime("%H:%M:%S"), {k: {kk: round(vv, 3) if vv is not None else None for kk, vv in v.items()}
                                          for k, v in m.items()}, flush=True)
        if args.once:
            return
        time.sleep(max(0.0, args.period - (time.monotonic() - t0)))


if __name__ == "__main__":
    main()
