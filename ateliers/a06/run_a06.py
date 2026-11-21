"""Atelier 6 — Network Slicing dynamique : plafonds par slice, charge différenciée, statique contre dynamique.

    .venv/bin/python ateliers/a06/run_a06.py [--load-duration 60] [--overload-duration 90]

Prérequis : make up-core up-obs up-actuator up-probes (le slice-autoscaler est lancé et arrêté par ce script).
Réalisme : ÉMULÉ. Produit :
    results/slicing.csv          T06.2 : débit mesuré de chaque slice contre son plafond (± 10 %)
    results/load.csv             T06.3 : séries par slice (débit, latence p95, perte, limite) sous trafics différenciés
    results/compare.csv          T06.5 : synthèse statique / dynamique (latence p95 v2x sous surcharge)
    results/compare_series.csv   T06.5 : séries temporelles des deux modes
    results/autoscaler.log       décisions du slice-autoscaler pendant le mode dynamique
    figures/*.png
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from b6g_common import scenario as scn

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "platform" / "trafficgen"))
import load  # noqa: E402

import report  # noqa: E402

PROM = "http://127.0.0.1:9090"
ACT = "http://127.0.0.1:8081"
H = {"X-B6G-Caller": "atelier-a06"}
OVERLOAD = {"proto": "udp", "direction": "dl", "per_ue_mbps": 6.0, "size": 1200}


def act(target: str, rate: float, ceil: float, reason: str) -> dict:
    res = httpx.post(f"{ACT}/v1/actions", json={"type": "slice.bandwidth", "target": target,
                                               "params": {"rate_mbps": rate, "ceil_mbps": ceil}, "reason": reason},
                     headers=H, timeout=10).json()
    if res.get("status") != "applied":
        raise RuntimeError(res)
    return res


def reset(sc: dict) -> None:
    for s in sc["slices"]:
        act(s["id"], s["bandwidth"]["rate_mbps"], s["bandwidth"]["ceil_mbps"], "atelier 6 : valeurs du scénario")


def saturate(sc: dict, ues: list, slice_id: str, duration: int) -> float:
    """Débit descendant total (Mbit/s) de tous les UEs de la slice en TCP sans limite."""
    prof = {"slice": slice_id, "proto": "tcp", "direction": "dl", "rate_mbps": 0}
    rows = load.run(sc, "a06-slicing", "saturation", duration, {slice_id: ("saturation", prof, 1.0)}, ues=ues)
    return sum(r["value"] for r in rows if r["metric"] == "throughput_mbps" and r["value"] is not None)


def udp_probe(sc: dict, ues: list, slice_id: str, ceil: float, duration: int) -> float:
    """Débit descendant UDP reçu par un UE qui envoie 1,5 × le plafond : mesure directe de ce que laisse passer HTB."""
    ue = next(u for u in ues if u.slice == slice_id)
    r = load.iperf(ue, "udp", "dl", ceil * 1.5 * 1e6, duration, size=1200)
    if "error" in r:
        raise RuntimeError(r["error"])
    return r["throughput_mbps"]


def t062_slicing(sc: dict, ues: list, duration: int) -> list[dict]:
    """Méthode de référence : UDP à 1,5 × ceil (1 UE). Colonne complémentaire : TCP, 10 UEs sans limite (goodput)."""
    out = []
    for s in sc["slices"]:
        sid, bw = s["id"], s["bandwidth"]
        for label, rate, ceil in (("scenario", bw["rate_mbps"], bw["ceil_mbps"]),
                                  ("consigne/2", bw["rate_mbps"] / 2, bw["ceil_mbps"] / 2)):
            act(sid, rate, ceil, f"atelier 6 : vérification du plafond ({label})")
            time.sleep(2)
            udp = udp_probe(sc, ues, sid, ceil, duration)
            time.sleep(2)
            tcp = saturate(sc, ues, sid, duration)
            ecart = (udp - ceil) / ceil
            out.append({"slice": sid, "reglage": label, "rate_mbps": rate, "ceil_mbps": ceil,
                        "debit_udp_mbps": round(udp, 3), "ecart_relatif_udp": round(ecart, 4),
                        "conforme_10pct": abs(ecart) <= 0.10,
                        "goodput_tcp_10ues_mbps": round(tcp, 3), "ecart_relatif_tcp": round((tcp - ceil) / ceil, 4)})
            print("T06.2", out[-1], flush=True)
        act(sid, bw["rate_mbps"], bw["ceil_mbps"], "atelier 6 : retour aux valeurs du scénario")
    return out


def series(t0: float, t1: float, label: str) -> list[dict]:
    exprs = {"debit_mbps": "sum by (slice) (b6g_slice_throughput_mbps)",
             "latence_p95_ms": 'b6g_slice_latency_ms{quantile="0.95"}',
             "perte": "b6g_slice_loss_ratio",
             "rate_mbps": "b6g_slice_bw_limit_mbps"}
    table: dict[tuple, dict] = {}
    for col, expr in exprs.items():
        for s in report.prom_range(PROM, expr, t0, t1, step=5):
            for t, v in s["points"]:
                key = (round(t - t0), s["labels"]["slice"])
                table.setdefault(key, {"mode": label, "t_s": key[0], "slice": key[1]})[col] = round(v, 4)
    return [table[k] for k in sorted(table)]


def t063_load(sc: dict, ues: list, duration: int) -> list[dict]:
    plan = {p["slice"]: (name, p, 1.0) for name, p in sc["profiles"].items()}
    t0 = time.time()
    load.run(sc, "a06-load", "charge-differenciee", duration, plan, ues=ues)
    time.sleep(10)
    return series(t0, time.time(), "charge-differenciee")


def overload(sc: dict, ues: list, duration: int, mode: str) -> tuple[list[dict], float]:
    """Surcharge descendante de la slice v2x ; séries à partir de 10 s avant le début (t_s = 10 : début)."""
    prof = {"slice": "v2x", "proto": OVERLOAD["proto"], "direction": OVERLOAD["direction"],
            "rate_mbps": OVERLOAD["per_ue_mbps"]}
    t0 = time.time()
    load.run(sc, f"a06-{mode}", f"surcharge-v2x-{mode}", duration, {"v2x": ("surcharge-v2x", prof, 1.0)}, ues=ues)
    time.sleep(10)
    return series(t0 - 10, time.time(), mode), t0


def summarize(sc: dict, ser: list[dict], mode: str, t_load: float, duration: int, actions: list[dict]) -> dict:
    sla = next(s["sla"] for s in sc["slices"] if s["id"] == "v2x")
    v = [r for r in ser if r["slice"] == "v2x" and 10 + 10 <= r["t_s"] <= 10 + duration]  # régime établi
    lat = [r["latence_p95_ms"] for r in v if r.get("latence_p95_ms") is not None]
    thr = [r["debit_mbps"] for r in v if r.get("debit_mbps") is not None]
    loss = [r["perte"] for r in v if r.get("perte") is not None]
    first_violation = next((r["t_s"] for r in ser if r["slice"] == "v2x" and r["t_s"] >= 10
                            and (r.get("latence_p95_ms") or 0) > sla["latency_ms_p95_max"]), None)
    first_action = None
    if actions:
        ts = datetime.strptime(actions[0]["ts"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()
        first_action = round(ts - (t_load - 10), 1)
    return {
        "mode": mode,
        "charge_offerte_mbps": OVERLOAD["per_ue_mbps"] * sc["ues"]["count_per_slice"],
        "latence_p95_mediane_ms": round(statistics.median(lat), 2) if lat else None,
        "latence_p95_max_ms": round(max(lat), 2) if lat else None,
        "part_echantillons_sla_respecte": round(sum(x <= sla["latency_ms_p95_max"] for x in lat) / len(lat), 3) if lat else None,
        "debit_moyen_mbps": round(statistics.mean(thr), 2) if thr else None,
        "perte_sonde_moyenne": round(statistics.mean(loss), 4) if loss else None,
        "actions": len(actions),
        "premier_depassement_s": first_violation,
        "premiere_action_s": first_action,
        "delai_reaction_s": (round(first_action - first_violation, 1)
                             if first_action is not None and first_violation is not None else None),
    }


def figures(compare_series: list[dict], load_series: list[dict]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig_dir = HERE / "figures"
    fig_dir.mkdir(exist_ok=True)
    fig, axes = plt.subplots(2, 1, figsize=(9, 6), sharex=True)
    for mode, style in (("statique", "-"), ("dynamique", "--")):
        v = [r for r in compare_series if r["mode"] == mode and r["slice"] == "v2x"]
        axes[0].plot([r["t_s"] - 10 for r in v], [r.get("latence_p95_ms") for r in v], style, label=mode)
        axes[1].plot([r["t_s"] - 10 for r in v], [r.get("debit_mbps") for r in v], style, label=f"débit {mode}")
        axes[1].plot([r["t_s"] - 10 for r in v], [r.get("rate_mbps") for r in v], ":", label=f"rate {mode}")
    axes[0].axhline(20, color="red", linewidth=1, label="SLA v2x 20 ms")
    axes[0].set_ylabel("latence p95 (ms)")
    axes[0].set_yscale("log")
    axes[1].set_ylabel("Mbit/s")
    axes[1].set_xlabel("temps depuis le début de la surcharge (s)")
    axes[0].set_title("Slice v2x en surcharge (60 Mbit/s offerts) : statique contre dynamique — ÉMULÉ")
    for ax in axes:
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(fig_dir / "statique_vs_dynamique_v2x.png", dpi=120)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4))
    for sid in ("embb", "v2x", "miot"):
        v = [r for r in load_series if r["slice"] == sid]
        ax.plot([r["t_s"] for r in v], [r.get("debit_mbps") for r in v], label=sid)
    ax.set_title("Charge différenciée par slice (profils nominaux) — ÉMULÉ")
    ax.set_ylabel("débit (Mbit/s)")
    ax.set_xlabel("temps (s)")
    ax.set_yscale("symlog", linthresh=0.01)
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(fig_dir / "charge_par_slice.png", dpi=120)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slicing-duration", type=int, default=10)
    ap.add_argument("--load-duration", type=int, default=60)
    ap.add_argument("--overload-duration", type=int, default=90)
    ap.add_argument("--only", choices=["slicing"], help="ne lancer que la vérification des plafonds (T06.2)")
    args = ap.parse_args()
    sc = scn.load()
    ues = load.list_ues(sc)
    res_dir = HERE / "results"
    subprocess.run(["make", "--no-print-directory", "stop-autoscaler"], cwd=ROOT, check=False)
    reset(sc)

    report.write_csv(t062_slicing(sc, ues, args.slicing_duration), res_dir / "slicing.csv")
    if args.only == "slicing":
        return
    time.sleep(10)
    report.write_csv(t063_load(sc, ues, args.load_duration), res_dir / "load.csv")
    time.sleep(15)

    # T06.5 : statique (aucune adaptation), puis dynamique (slice-autoscaler actif)
    static_series, t_s0 = overload(sc, ues, args.overload_duration, "statique")
    summary = [summarize(sc, static_series, "statique", t_s0, args.overload_duration, [])]
    reset(sc)
    time.sleep(20)
    log = ROOT / ".run" / "autoscaler.log"
    subprocess.run(["make", "--no-print-directory", "up-autoscaler"], cwd=ROOT, check=True)
    try:
        dyn_series, t_d0 = overload(sc, ues, args.overload_duration, "dynamique")
        time.sleep(20)   # laisser le retour automatique aux valeurs du scénario se produire
    finally:
        subprocess.run(["make", "--no-print-directory", "stop-autoscaler"], cwd=ROOT, check=False)
    decisions = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.startswith("{")]
    (res_dir / "autoscaler.log").write_text(log.read_text(encoding="utf-8"), encoding="utf-8")
    ups = [d for d in decisions if d.get("slice") == "v2x" and "retour" not in d.get("reason", "")]
    summary.append(summarize(sc, dyn_series, "dynamique", t_d0, args.overload_duration, ups))
    reset(sc)
    report.write_csv(summary, res_dir / "compare.csv")
    report.write_csv(static_series + dyn_series, res_dir / "compare_series.csv")
    with (res_dir / "load.csv").open(encoding="utf-8") as f:
        load_series = [{**r, "t_s": int(r["t_s"]), "debit_mbps": float(r["debit_mbps"]) if r.get("debit_mbps") else None}
                       for r in csv.DictReader(f)]
    figures(static_series + dyn_series, load_series)
    for row in summary:
        print("T06.5", row, flush=True)


if __name__ == "__main__":
    main()
