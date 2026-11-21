"""Atelier 8 — mise à l'échelle manuelle puis auto-scaling HPA de b6g-echo-app (T08.4).

    .venv/bin/python ateliers/a08/run_a08.py

Prérequis : make up-k8s, puis kubectl apply -k platform/k8s/apps/echo-app. Réalisme : ÉMULÉ (k3s réel dans Docker).
1. Mise à l'échelle manuelle : 1 -> 3 -> 1 répliques (kubectl scale), délai jusqu'à disponibilité.
2. HPA : charge croissante sur /work (paliers de clients concurrents), puis arrêt de la charge ;
   toutes les 5 s : répliques, CPU (HPA), débit de requêtes servi et latence p50 / p95 vue par le client.
Produit results/scaling_manual.csv, results/hpa.csv et figures/hpa.png.
"""
from __future__ import annotations

import csv
import json
import os
import statistics
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
KUBECTL = str(Path.home() / "b6g-ext" / "bin" / "kubectl")
NS, DEPLOY = "b6g-cloud", "b6g-echo-app"
STEPS = [(0, 30), (1, 90), (2, 90), (4, 90), (8, 90), (0, 180)]   # (clients concurrents, durée en s)
THINK_S = 0.2   # pause de chaque client entre deux requêtes (≈ 0,17 cœur par client)
WORK_MS = 40


def kubectl(*args: str) -> str:
    return subprocess.run([KUBECTL, *args], capture_output=True, text=True, check=True).stdout


def node_url() -> str:
    ip = subprocess.run(["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
                         "k3d-b6g-agent-2"], capture_output=True, text=True, check=True).stdout.strip()
    return f"http://{ip}:30080"


def ready_replicas() -> tuple[int, int]:
    d = json.loads(kubectl("-n", NS, "get", "deploy", DEPLOY, "-o", "json"))
    return d["spec"].get("replicas", 0), d["status"].get("readyReplicas", 0)


def manual_scaling() -> list[dict]:
    rows = []
    for target in (3, 1):
        t0 = time.time()
        kubectl("-n", NS, "scale", "deploy", DEPLOY, f"--replicas={target}")
        while True:
            want, ready = ready_replicas()
            pods = [p for p in kubectl("-n", NS, "get", "pods", "-l", f"app={DEPLOY}", "--no-headers").splitlines()
                    if "Terminating" not in p]
            if ready == target and len(pods) == target:
                break
            time.sleep(0.5)
        rows.append({"action": f"kubectl scale --replicas={target}", "repliques": target,
                     "delai_disponibilite_s": round(time.time() - t0, 2)})
        print(rows[-1], flush=True)
        time.sleep(5)
    return rows


class Load:
    """Clients HTTP concurrents en boucle sur /work ; latences et nombre de réponses par intervalle."""

    def __init__(self, url: str):
        self.url, self.clients, self.lock = f"{url}/work?ms={WORK_MS}", 0, threading.Lock()
        self.lat: list[float] = []
        self.errors = 0
        self.stop = False

    def worker(self, idx: int) -> None:
        while not self.stop:
            if idx >= self.clients:
                time.sleep(0.2)
                continue
            t0 = time.perf_counter()
            try:
                urllib.request.urlopen(self.url, timeout=10).read()
                with self.lock:
                    self.lat.append((time.perf_counter() - t0) * 1000)
                time.sleep(THINK_S)
            except OSError:
                with self.lock:
                    self.errors += 1

    def take(self) -> tuple[list[float], int]:
        with self.lock:
            lat, err, self.lat, self.errors = self.lat, self.errors, [], 0
        return lat, err


def hpa_run(url: str) -> list[dict]:
    load = Load(url)
    threads = [threading.Thread(target=load.worker, args=(i,), daemon=True) for i in range(max(c for c, _ in STEPS))]
    for t in threads:
        t.start()
    rows, t_start = [], time.time()
    for clients, duration in STEPS:
        load.clients = clients
        end = time.time() + duration
        while time.time() < end:
            time.sleep(5)
            lat, err = load.take()
            hpa = json.loads(kubectl("-n", NS, "get", "hpa", DEPLOY, "-o", "json"))
            cpu = next((m["resource"]["current"].get("averageUtilization") for m in hpa["status"].get("currentMetrics") or []
                        if m.get("type") == "Resource"), None)
            want, ready = ready_replicas()
            q = statistics.quantiles(lat, n=100, method="inclusive") if len(lat) > 1 else None
            rows.append({"t_s": round(time.time() - t_start), "clients": clients, "repliques_voulues": want,
                         "repliques_pretes": ready, "cpu_hpa_pct": cpu, "requetes_par_s": round(len(lat) / 5, 1),
                         "latence_p50_ms": round(q[49], 1) if q else None, "latence_p95_ms": round(q[94], 1) if q else None,
                         "erreurs": err})
            print(rows[-1], flush=True)
    load.stop = True
    return rows


def write(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def figure(rows: list[dict]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = [r["t_s"] for r in rows]
    fig, ax = plt.subplots(3, 1, figsize=(9, 7), sharex=True)
    ax[0].plot(t, [r["clients"] for r in rows], label="clients concurrents")
    ax[0].plot(t, [r["repliques_pretes"] for r in rows], label="répliques prêtes")
    ax[0].plot(t, [r["repliques_voulues"] for r in rows], ":", label="répliques demandées (HPA)")
    ax[1].plot(t, [r["cpu_hpa_pct"] for r in rows], label="CPU moyen / requête (%)")
    ax[1].axhline(50, color="red", lw=1, label="cible HPA 50 %")
    ax[2].plot(t, [r["latence_p95_ms"] for r in rows], label="latence p95 (ms)")
    ax[2].plot(t, [r["requetes_par_s"] for r in rows], label="requêtes servies / s")
    ax[2].set_xlabel("temps (s)")
    for a in ax:
        a.grid(alpha=0.3)
        a.legend(fontsize=8)
    ax[0].set_title("Auto-scaling HPA de b6g-echo-app (k3d, niveau Cloud) — ÉMULÉ")
    fig.tight_layout()
    (HERE / "figures").mkdir(exist_ok=True)
    fig.savefig(HERE / "figures" / "hpa.png", dpi=120)
    plt.close(fig)


def main() -> None:
    os.environ["PATH"] = f"{Path.home() / 'b6g-ext' / 'bin'}:{os.environ['PATH']}"
    url = node_url()
    write(manual_scaling(), HERE / "results" / "scaling_manual.csv")
    rows = hpa_run(url)
    write(rows, HERE / "results" / "hpa.csv")
    figure(rows)


if __name__ == "__main__":
    main()
