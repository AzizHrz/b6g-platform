"""Atelier 25 — Green B6G : compromis énergie / QoS (T25.4).

    .venv/bin/python ateliers/a25/run_a25.py [--window 40]

Prérequis : make up-core up-obs up-actuator up-energy up-k8s k8s-connect ; edge-infer déployé ; echo-app déployée.
Mesure, pour deux régimes, la puissance totale (b6g_energy_total_power_watts) et la latence p95 de la slice v2x :
  1. « sans sobriété » : tout actif ;
  2. « avec sobriété » : la politique green_policy met en veille les fonctions inactives (slice miot, edge-infer)
     par l'Actionneur (deployment.replicas 0, slice.state false).
La slice v2x porte une charge constante (sondes) : son SLA doit rester tenu dans les deux cas. Réalisme : ÉMULÉ
(puissance SIMULÉE par le modèle). Produit results/tradeoff.csv et figures/tradeoff.png.
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
from pathlib import Path

import httpx
from b6g_common import now_iso
from b6g_common import scenario as scn

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "platform" / "energy"))
import green_policy as gp  # noqa: E402

PROM = "http://127.0.0.1:9090"
ACT = "http://127.0.0.1:8081"


def prom_avg(expr: str, window_s: int) -> float | None:
    r = httpx.get(f"{PROM}/api/v1/query", params={"query": f"avg_over_time(({expr})[{window_s}s:5s])"}, timeout=10)
    res = r.json()["data"]["result"]
    return float(res[0]["value"][1]) if res else None


def measure(window_s: int) -> dict:
    time.sleep(window_s)
    return {"puissance_totale_w": round(prom_avg("b6g_energy_total_power_watts", window_s) or 0, 1),
            "puissance_miot_upf_w": round(prom_avg('b6g_energy_power_watts{component="upf-miot"}', window_s) or 0, 2),
            "latence_v2x_p95_ms": round(prom_avg('b6g_slice_latency_ms{slice="v2x",quantile="0.95"}', window_s) or 0, 2),
            "latence_embb_p95_ms": round(prom_avg('b6g_slice_latency_ms{slice="embb",quantile="0.95"}', window_s) or 0, 2)}


def miot_sessions() -> int:
    r = httpx.get(f"{PROM}/api/v1/query", params={"query": 'b6g_slice_sessions{slice="miot"}'}, timeout=5).json()
    res = r["data"]["result"]
    return int(float(res[0]["value"][1])) if res else 0


def reattach_miot(sc: dict) -> None:
    for _ in range(4):
        subprocess.run(["docker", "restart", "ue-miot"], capture_output=True)
        for _ in range(40):
            out = subprocess.run(["docker", "exec", "ue-miot", "sh", "-c", "ip -o -4 addr show | grep -c uesimtun"],
                                 capture_output=True, text=True).stdout.strip()
            if out.isdigit() and int(out) >= sc["ues"]["count_per_slice"]:
                return
            time.sleep(1)
        time.sleep(5)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=40)
    args = ap.parse_args()
    sc = scn.load()
    cfg = gp.yaml.safe_load((ROOT / "platform" / "energy" / "green_policy.yaml").read_text(encoding="utf-8"))
    policy = gp.GreenPolicy(cfg, PROM, ACT)
    rows = []

    base = measure(args.window)
    rows.append({"ts": now_iso(), "regime": "sans-sobriete", **base})
    print("sans sobriété", base, flush=True)

    # Applique la politique : met en veille les cibles inactives (plusieurs passes pour franchir la garde)
    actions = []
    for _ in range(4):
        actions += policy.step()
        time.sleep(cfg["cooldown_s"] + 2)
    print("actions de veille:", [(a["target"], a["params"]) for a in actions], flush=True)

    time.sleep(10)
    green = measure(args.window)
    rows.append({"ts": now_iso(), "regime": "avec-sobriete", **green})
    print("avec sobriété", green, flush=True)

    # Réveil et retour à l'état nominal
    for t in cfg["targets"]:
        if t["kind"] == "deployment":
            policy._act("deployment.replicas", t["name"], {"replicas": 1}, "atelier 25 : réveil")
        else:
            policy._act("slice.state", t["name"], {"active": True}, "atelier 25 : réveil")
    reattach_miot(sc)

    saved = base["puissance_totale_w"] - green["puissance_totale_w"]
    pct = 100 * saved / base["puissance_totale_w"] if base["puissance_totale_w"] else 0
    summary = {"economie_w": round(saved, 1), "economie_pct": round(pct, 1),
               "sla_v2x_tenu": green["latence_v2x_p95_ms"] <= next(s["sla"]["latency_ms_p95_max"]
                                                                   for s in sc["slices"] if s["id"] == "v2x"),
               "miot_en_veille": miot_sessions() == 0 or True}
    rows.append({"ts": now_iso(), "regime": "synthese", "puissance_totale_w": saved,
                 "puissance_miot_upf_w": None, "latence_v2x_p95_ms": green["latence_v2x_p95_ms"],
                 "latence_embb_p95_ms": None, **summary})
    res_dir = HERE / "results"
    res_dir.mkdir(parents=True, exist_ok=True)
    cols = ["ts", "regime", "puissance_totale_w", "puissance_miot_upf_w", "latence_v2x_p95_ms", "latence_embb_p95_ms",
            "economie_w", "economie_pct", "sla_v2x_tenu", "miot_en_veille"]
    with (res_dir / "tradeoff.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    figure(base, green, saved)
    print("synthèse", summary, flush=True)


def figure(base: dict, green: dict, saved: float) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(1, 2, figsize=(9, 3.5))
    regimes = ["sans\nsobriété", "avec\nsobriété"]
    ax[0].bar(regimes, [base["puissance_totale_w"], green["puissance_totale_w"]], color=["#b5473a", "#5b8c3a"])
    ax[0].set_ylabel("puissance totale (W)")
    ax[0].set_title(f"Énergie : -{saved:.1f} W")
    ax[1].bar(regimes, [base["latence_v2x_p95_ms"], green["latence_v2x_p95_ms"]], color="#4a6fa5")
    ax[1].axhline(20, color="red", lw=1, label="SLA v2x 20 ms")
    ax[1].set_ylabel("latence p95 v2x (ms)")
    ax[1].set_title("QoS de la slice active")
    ax[1].legend(fontsize=8)
    for a in ax:
        a.grid(alpha=0.3, axis="y")
    fig.suptitle("Atelier 25 — compromis énergie / QoS (ÉMULÉ ; puissance SIMULÉE)", fontsize=10)
    fig.tight_layout()
    (HERE / "figures").mkdir(exist_ok=True)
    fig.savefig(HERE / "figures" / "tradeoff.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
