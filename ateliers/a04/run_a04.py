"""Atelier 4 — plusieurs UEs et services : trafics simultanés, mesures, congestion, adaptation (T04.2 à T04.4).

    .venv/bin/python ateliers/a04/run_a04.py [--duration 20]

Prérequis : make up-core up-obs up-actuator up-probes. Réalisme : ÉMULÉ.
Produit :
    results/measures.csv   measure.v1, 30 UEs × 3 niveaux de charge (T04.2)
    results/summary.csv    synthèse par slice et par niveau (débit offert / servi, RTT, perte, CPU des NF)
    results/adapt.csv      avant / après l'action slice.bandwidth sur la slice congestionnée (T04.4)
    figures/*.png          débit, latence et CPU pendant l'expérience (T04.3)
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
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
LEVELS = {"faible": 0.5, "nominale": 1.0, "forte": 2.0}


def plan(sc: dict, scale: float) -> dict:
    return {p["slice"]: (name, p, scale) for name, p in sc["profiles"].items()}


def offered_mbps(sc: dict, slice_id: str, scale: float) -> float:
    name, prof, _ = plan(sc, scale)[slice_id]
    _proto, _dir, rate, _size = load.profile_params(prof, scale)
    return rate * sc["ues"]["count_per_slice"] / 1e6


def summarize(sc: dict, rows: list[dict], level: str, scale: float, t0: float, t1: float, bw: dict) -> list[dict]:
    out = []
    cpu = {r["labels"]["nf"]: r["value"] for r in
           report.prom_instant(PROM, f"avg_over_time(b6g_nf_cpu_ratio[{int(t1 - t0)}s])", at=t1)}
    for s in scn.slice_ids(sc):
        sr = [r for r in rows if r["slice"] == s and r["value"] is not None]
        thr = [r["value"] for r in sr if r["metric"] == "throughput_mbps"]
        rtt = [r["value"] for r in sr if r["metric"] == "rtt_ms"]
        loss = [r["value"] for r in sr if r["metric"] == "loss_ratio"]
        out.append({
            "niveau": level, "echelle": scale, "slice": s,
            "debit_offert_mbps": round(offered_mbps(sc, s, scale), 3),
            "debit_servi_mbps": round(sum(thr), 3),
            "ues_mesures": len(thr),
            "rtt_median_ms": round(statistics.median(rtt), 3) if rtt else None,
            "rtt_max_ue_ms": round(max(rtt), 3) if rtt else None,
            "perte_moyenne": round(statistics.mean(loss), 5) if loss else None,
            "rate_mbps": bw[s]["rate_mbps"], "ceil_mbps": bw[s]["ceil_mbps"],
            "cpu_upf": round(cpu.get(f"upf-{s}", float("nan")), 4),
            "cpu_gnb": round(cpu.get("gnb", float("nan")), 4),
        })
    return out


def act(params: dict, target: str, reason: str) -> dict:
    r = httpx.post(f"{ACT}/v1/actions", json={"type": "slice.bandwidth", "target": target, "params": params,
                                             "reason": reason}, headers={"X-B6G-Caller": "atelier-a04"}, timeout=10)
    res = r.json()
    if res.get("status") != "applied":
        raise RuntimeError(res)
    return res


def figures(t0: float, t1: float, marks: list[tuple[float, str]]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig_dir = HERE / "figures"
    fig_dir.mkdir(exist_ok=True)
    panels = [
        ("sum by (slice) (b6g_slice_throughput_mbps)", "Débit par slice (Mbit/s)", "debit_par_slice.png", "{slice}"),
        ('b6g_slice_latency_ms{quantile="0.95"}', "Latence p95 UE → UPF (ms)", "latence_p95_par_slice.png", "{slice}"),
        ('b6g_nf_cpu_ratio{nf=~"gnb|upf-.+|amf"}', "CPU par fonction (fraction d'un cœur)", "cpu_nf.png", "{nf}"),
    ]
    for expr, title, fname, legend in panels:
        fig, ax = plt.subplots(figsize=(9, 4))
        for s in report.prom_range(PROM, expr, t0, t1, step=5):
            xs = [p[0] - t0 for p in s["points"]]
            ax.plot(xs, [p[1] for p in s["points"]], label=legend.format(**s["labels"]))
        for t, label in marks:
            ax.axvline(t - t0, color="grey", linestyle=":", linewidth=1)
            ax.text(t - t0, ax.get_ylim()[1], label, fontsize=7, rotation=90, va="top", ha="right")
        ax.set_title(f"{title} — atelier 4 (ÉMULÉ)")
        ax.set_xlabel("temps depuis le début de l'expérience (s)")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(fig_dir / fname, dpi=120)
        plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--duration", type=int, default=20)
    ap.add_argument("--pause", type=int, default=15)
    args = ap.parse_args()
    sc = scn.load()
    init = {s["id"]: dict(s["bandwidth"]) for s in sc["slices"]}
    ues = load.list_ues(sc)
    print(f"{len(ues)} UEs actifs")
    run_id = time.strftime("a04-%Y%m%dT%H%M%S")
    all_rows, summary, marks = [], [], []
    t_start = time.time()
    # T04.2 : trois niveaux de charge, les 30 UEs simultanément
    for level, scale in LEVELS.items():
        marks.append((time.time(), level))
        t0 = time.time()
        rows = load.run(sc, run_id, f"charge-{level}", args.duration, plan(sc, scale), ues=ues)
        t1 = time.time()
        all_rows += rows
        summary += summarize(sc, rows, level, scale, t0, t1, init)
        print(level, [(r["slice"], r["debit_offert_mbps"], r["debit_servi_mbps"], r["rtt_median_ms"])
                      for r in summary[-3:]], flush=True)
        time.sleep(args.pause)
    report.write_measures(all_rows, HERE / "results" / "measures.csv")
    report.write_csv(summary, HERE / "results" / "summary.csv")

    # T04.4 : slice la plus congestionnée au niveau fort (débit servi / offert le plus faible)
    forte = [r for r in summary if r["niveau"] == "forte"]
    worst = min(forte, key=lambda r: r["debit_servi_mbps"] / r["debit_offert_mbps"])
    target = worst["slice"]
    others = sum(v["rate_mbps"] for k, v in init.items() if k != target)
    new_rate = min(round(worst["debit_offert_mbps"]), sc["capacity"]["total_rate_mbps_max"] - others)
    # Plafond : 10 % au-dessus de la demande, sans dépasser la capacité totale de la plateforme
    new_ceil = min(max(new_rate, round(worst["debit_offert_mbps"] * 1.1)), sc["capacity"]["total_rate_mbps_max"])
    adapt = [{"phase": "avant", **{k: worst[k] for k in ("slice", "rate_mbps", "ceil_mbps", "debit_offert_mbps",
                                                          "debit_servi_mbps", "rtt_median_ms", "rtt_max_ue_ms",
                                                          "perte_moyenne", "cpu_upf")}}]
    time.sleep(args.pause)
    marks.append((time.time(), f"action {target}"))
    res = act({"rate_mbps": new_rate, "ceil_mbps": new_ceil}, target,
              f"atelier 4 : congestion {target} ({worst['debit_servi_mbps']} / {worst['debit_offert_mbps']} Mbit/s)")
    print("action", res["previous"], "->", res["current"])
    bw = {**init, target: {"rate_mbps": new_rate, "ceil_mbps": new_ceil}}
    try:
        t0 = time.time()
        rows = load.run(sc, run_id, "charge-forte-apres-adaptation", args.duration, plan(sc, LEVELS["forte"]), ues=ues)
        t1 = time.time()
        after = next(r for r in summarize(sc, rows, "forte", LEVELS["forte"], t0, t1, bw) if r["slice"] == target)
        adapt.append({"phase": "apres", **{k: after[k] for k in adapt[0] if k != "phase"}})
        all_rows += rows
    finally:
        act(init[target], target, "atelier 4 : retour aux valeurs du scénario")
        marks.append((time.time(), "retour"))
    report.write_measures(all_rows, HERE / "results" / "measures.csv")
    report.write_csv(adapt, HERE / "results" / "adapt.csv")
    time.sleep(10)
    figures(t_start, time.time(), marks)
    print("adaptation", adapt)


if __name__ == "__main__":
    main()
