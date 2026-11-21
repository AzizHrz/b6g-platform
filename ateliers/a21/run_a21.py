"""Atelier 21 — registre Hyperledger Fabric : 100 événements inscrits et vérifiés (T21.3), coûts à 1, 10 et 50 tx/s (T21.4).

    .venv/bin/python ateliers/a21/run_a21.py [--duration 30]

Prérequis : make up-ledger (Fabric 2.5.16, canal b6g, chaincode eventlog, passerelle I-07 sur :8082), make up-obs.
Les événements suivent b6g.event.v1 (b6g_common.events.make). Réalisme : ÉMULÉ (Fabric réel, deux organisations et un
ordonnanceur sur une seule machine).
Produit results/events_verified.csv, results/cost.csv (rate_tx_s, latency_ms_p50, latency_ms_p95, cpu_ratio,
memory_bytes, ...) et figures/cost.png.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import threading
import time
from pathlib import Path

import httpx
from b6g_common import events, now_iso

HERE = Path(__file__).resolve().parent
LEDGER = "http://127.0.0.1:8082"
PROM = "http://127.0.0.1:9090"
H = {"X-B6G-Caller": "atelier-a21", "Content-Type": "application/json"}
FABRIC = ["peer0.org1.example.com", "peer0.org2.example.com", "orderer.example.com"]
TYPES = [("slice.resized", lambda i: {"slice": ["embb", "v2x", "miot"][i % 3], "rate_mbps": 10.0 + i, "ceil_mbps": 40}),
         ("link.netem", lambda i: {"target": "n6-v2x", "delay_ms": i % 50}),
         ("alert.qos", lambda i: {"slice": "v2x", "latency_ms_p95": 20.5 + i / 10, "sla_ms": 20}),
         ("ue.isolated", lambda i: {"target": f"ue-miot-{i % 10 + 1:02d}", "duration_s": 30}),
         ("loop.iteration", lambda i: {"iteration": i, "outcome": "resolved"})]


def post(client: httpx.Client, evt: dict) -> tuple[float, dict]:
    t0 = time.perf_counter()
    r = client.post(f"{LEDGER}/v1/events", content=json.dumps(evt, ensure_ascii=False).encode(), headers=H, timeout=60)
    return (time.perf_counter() - t0) * 1000, (r.json() if r.status_code == 200 else {"status_code": r.status_code})


def t213_record_and_verify(n: int = 100) -> list[dict]:
    rows = []
    with httpx.Client() as c:
        for i in range(n):
            typ, payload = TYPES[i % len(TYPES)]
            evt = events.make("atelier-a21", typ, payload(i))
            ms, receipt = post(c, evt)
            v = c.get(f"{LEDGER}/v1/verify/{evt['event_id']}", timeout=30).json()
            rows.append({"event_id": evt["event_id"], "type": typ, "tx_id": receipt.get("tx_id"),
                         "block_number": receipt.get("block_number"), "commit_ms": round(ms, 1),
                         "hash_match": v.get("hash_match"), "endorsements": "+".join(v.get("endorsements", []))})
    return rows


def prom_avg(expr: str, t0: float, t1: float) -> float | None:
    r = httpx.get(f"{PROM}/api/v1/query", params={"query": f"avg_over_time(({expr})[{int(t1 - t0)}s:5s])", "time": t1},
                  timeout=10).json()["data"]["result"]
    return float(r[0]["value"][1]) if r else None


def load(rate: float, duration: int) -> dict:
    """Charge en boucle ouverte : un envoi toutes les 1/rate s (fils séparés), sans attendre les réponses."""
    lat: list[float] = []
    errors = 0
    lock = threading.Lock()
    client = httpx.Client(limits=httpx.Limits(max_connections=200))

    def one(i: int) -> None:
        nonlocal errors
        evt = events.make("atelier-a21", "loop.iteration", {"iteration": i, "rate_tx_s": rate})
        try:
            ms, receipt = post(client, evt)
            ok = receipt.get("status") == "committed"
        except httpx.HTTPError:
            ms, ok = 0.0, False
        with lock:
            if ok:
                lat.append(ms)
            else:
                errors += 1

    threads = []
    t0 = time.time()
    n = int(rate * duration)
    for i in range(n):
        target = t0 + i / rate
        time.sleep(max(0.0, target - time.time()))
        th = threading.Thread(target=one, args=(i,))
        th.start()
        threads.append(th)
    for th in threads:
        th.join()
    t1 = time.time()
    client.close()
    names = "|".join(FABRIC)
    cpu = prom_avg(f'sum(rate(container_cpu_usage_seconds_total{{job="cadvisor",name=~"{names}"}}[15s]))', t0, t1)
    mem = prom_avg(f'sum(container_memory_working_set_bytes{{job="cadvisor",name=~"{names}"}})', t0, t1)
    q = statistics.quantiles(lat, n=100, method="inclusive") if len(lat) > 1 else [lat[0]] * 99 if lat else None
    return {"ts": now_iso(), "rate_tx_s": rate, "envoyes": n, "valides": len(lat), "echecs": errors,
            "debit_valide_tx_s": round(len(lat) / (t1 - t0), 2), "duree_s": round(t1 - t0, 1),
            "latency_ms_p50": round(q[49], 1) if q else None, "latency_ms_p95": round(q[94], 1) if q else None,
            "cpu_ratio": round(cpu, 3) if cpu is not None else None, "memory_bytes": int(mem) if mem else None}


def write(rows: list[dict], name: str) -> None:
    p = HERE / "results" / name
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def figure(cost: list[dict]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = [str(int(r["rate_tx_s"])) for r in cost]
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.5))
    ax[0].bar(x, [r["latency_ms_p50"] for r in cost], label="p50", color="#4a6fa5")
    ax[0].plot(x, [r["latency_ms_p95"] for r in cost], "o-", color="#b5473a", label="p95")
    ax[0].set_ylabel("latence d'inscription (ms)")
    ax[0].legend()
    ax[1].bar(x, [r["cpu_ratio"] or 0 for r in cost], color="#c98a1b")
    ax[1].set_ylabel("CPU Fabric (cœurs)")
    for a in ax:
        a.set_xlabel("débit demandé (tx/s)")
        a.grid(alpha=0.3, axis="y")
    fig.suptitle("Atelier 21 — coût du registre Hyperledger Fabric (ÉMULÉ)", fontsize=10)
    fig.tight_layout()
    (HERE / "figures").mkdir(exist_ok=True)
    fig.savefig(HERE / "figures" / "cost.png", dpi=120)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=30)
    args = ap.parse_args()
    verified = t213_record_and_verify(100)
    write(verified, "events_verified.csv")
    ok = sum(1 for r in verified if r["hash_match"] and r["endorsements"] == "Org1MSP+Org2MSP")
    print(f"T21.3 : {ok}/100 événements inscrits, vérifiés et endossés par Org1 et Org2", flush=True)
    cost = []
    for rate in (1, 10, 50):
        time.sleep(10)
        cost.append(load(rate, args.duration))
        print("T21.4", cost[-1], flush=True)
    write(cost, "cost.csv")
    figure(cost)


if __name__ == "__main__":
    main()
