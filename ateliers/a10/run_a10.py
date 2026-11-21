"""Atelier 10 — Edge, Fog et Cloud : latence applicative selon l'emplacement du calcul (T10.2, T10.3).

    .venv/bin/python ateliers/a10/run_a10.py [--requests 1000]

Prérequis : make up-core up-obs up-actuator up-k8s ; b6g-echo-app déployée (kubectl apply -k platform/k8s/apps/echo-app) ;
UPF reliées au réseau k3d (make k8s-connect) ; délais des niveaux appliqués par l'Actionneur (link.netem tier-*).
Pour chaque niveau (cloud, fog, edge) : déplacement de b6g-echo-app par l'Actionneur (deployment.placement), attente
du pod prêt sur le nœud du niveau, puis `--requests` requêtes HTTP séquentielles depuis un UE embb (interface
uesimtun0 : UE -> gNB -> UPF -> nœud du niveau -> pod). Réalisme : ÉMULÉ (délais de niveau ajoutés par netem).
Produit results/latency_cloud.csv, results/latency_tiers.csv, results/latency_samples.csv, figures/latency_tiers.png.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import time
import urllib.request
from pathlib import Path

from b6g_common import now_iso
from b6g_common import scenario as scn

HERE = Path(__file__).resolve().parent
KUBECTL = str(Path.home() / "b6g-ext" / "bin" / "kubectl")
ACT, NS, DEPLOY, UE = "http://127.0.0.1:8081", "b6g-cloud", "b6g-echo-app", "ue-embb"


def act(body: dict) -> dict:
    req = urllib.request.Request(f"{ACT}/v1/actions", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-B6G-Caller": "atelier-a10"})
    res = json.load(urllib.request.urlopen(req, timeout=60))
    if res.get("status") != "applied":
        raise RuntimeError(res)
    return res


def node_ip(node: str) -> str:
    return subprocess.run(["docker", "inspect", "-f", '{{(index .NetworkSettings.Networks "k3d-b6g").IPAddress}}', node],
                          capture_output=True, text=True, check=True).stdout.strip()


def wait_on_node(node: str, timeout: float = 120) -> float:
    t0 = time.time()
    while time.time() - t0 < timeout:
        pods = json.loads(subprocess.run([KUBECTL, "-n", NS, "get", "pods", "-l", f"app={DEPLOY}", "-o", "json"],
                                         capture_output=True, text=True, check=True).stdout)["items"]
        live = [p for p in pods if not p["metadata"].get("deletionTimestamp")]
        if live and all(p["spec"].get("nodeName") == node and any(c["type"] == "Ready" and c["status"] == "True"
                                                                  for c in p["status"].get("conditions", []))
                        for p in live):
            return time.time() - t0
        time.sleep(0.5)
    raise RuntimeError(f"pod non prêt sur {node}")


def measure(url: str, n: int) -> list[float]:
    script = (f"for i in $(seq {n}); do curl -s -o /dev/null -m 2 -w '%{{time_total}}\\n' --interface uesimtun0 "
              f"{url}/echo; done")
    out = subprocess.run(["docker", "exec", UE, "sh", "-c", script], capture_output=True, text=True, timeout=n * 3).stdout
    return [float(x) * 1000 for x in out.split() if float(x) > 0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--requests", type=int, default=1000)
    args = ap.parse_args()
    sc = scn.load()
    rows, samples = [], []
    for tier in ("cloud", "fog", "edge"):
        t = sc["tiers"][tier]
        res = act({"type": "deployment.placement", "target": DEPLOY, "params": {"tier": tier},
                   "reason": f"atelier 10 : traitement déplacé vers le niveau {tier}"})
        move_s = wait_on_node(t["k8s_node"])
        time.sleep(3)
        lat = measure(f"http://{node_ip(t['k8s_node'])}:30080", args.requests)
        q = statistics.quantiles(lat, n=100, method="inclusive")
        rows.append({"ts": now_iso(), "niveau": tier, "noeud": t["k8s_node"], "delai_ajoute_ms": t["added_rtt_ms"],
                     "cpu_millicores_niveau": t["cpu_millicores"], "requetes": len(lat), "echecs": args.requests - len(lat),
                     "rtt_p50_ms": round(q[49], 2), "rtt_p95_ms": round(q[94], 2), "rtt_moyen_ms": round(statistics.mean(lat), 2),
                     "deplacement_s": round(move_s, 1), "action": res["action_id"]})
        samples += [{"niveau": tier, "rtt_ms": round(x, 3)} for x in lat]
        print(rows[-1], flush=True)
    act({"type": "deployment.placement", "target": DEPLOY, "params": {"tier": "cloud"},
         "reason": "atelier 10 : retour au niveau Cloud"})
    res_dir = HERE / "results"
    res_dir.mkdir(parents=True, exist_ok=True)
    for name, data in (("latency_cloud.csv", [r for r in rows if r["niveau"] == "cloud"]),
                       ("latency_tiers.csv", rows), ("latency_samples.csv", samples)):
        with (res_dir / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(data)
    figure(samples)


def figure(samples: list[dict]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    tiers = ["edge", "fog", "cloud"]
    data = [[s["rtt_ms"] for s in samples if s["niveau"] == t] for t in tiers]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.boxplot(data, tick_labels=tiers, showfliers=False)
    ax.set_ylabel("RTT applicatif depuis un UE (ms)")
    ax.set_title("b6g-echo-app selon le niveau d'exécution (1 000 requêtes) — ÉMULÉ", fontsize=10)
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    (HERE / "figures").mkdir(exist_ok=True)
    fig.savefig(HERE / "figures" / "latency_tiers.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
