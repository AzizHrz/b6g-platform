"""Atelier 3 — tableau de référence par slice (T03.2) : débit, RTT moyen et p95, perte, temps d'attachement.

    .venv/bin/python ateliers/a03/run_a03.py [--reps 3]

Prérequis : make up-core up-obs up-actuator. Aucune autre charge pendant la mesure. Réalisme : ÉMULÉ.
Pour chaque répétition : redémarrage des 3 conteneurs d'UEs (30 attachements), puis, par slice et à vide,
débit TCP descendant et montant d'un UE (10 s), 50 ping vers la passerelle de l'UPF.
Produit results/baseline.csv (measure.v1) et results/baseline_summary.csv.
"""
from __future__ import annotations

import argparse
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from b6g_common import scenario as scn

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "platform" / "trafficgen"))
import load  # noqa: E402

import report  # noqa: E402

LOG = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3})\] \[(\d{15})\|nas\] \[\w+\] (.*)$")


def ts(s: str) -> float:
    return datetime.strptime(s, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc).timestamp()


def restart_and_attach(container: str, n: int, since: str, timeout: float = 90) -> dict[str, float]:
    """Redémarre le conteneur d'UEs et renvoie {imsi: temps d'attachement en ms} d'après les journaux UERANSIM :
    dernière « Sending Initial Registration » -> « PDU Session establishment is successful »."""
    subprocess.run(["docker", "restart", container], capture_output=True, check=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        out = subprocess.run(["docker", "exec", container, "sh", "-c", "ip -o -4 addr show | grep -c uesimtun"],
                             capture_output=True, text=True).stdout.strip()
        if out.isdigit() and int(out) >= n:
            break
        time.sleep(1)
    time.sleep(2)
    logs = subprocess.run(["docker", "logs", "--since", since, container], capture_output=True, text=True)
    start: dict[str, float] = {}
    attach: dict[str, float] = {}
    for line in (logs.stdout + logs.stderr).splitlines():
        m = LOG.match(line)
        if not m:
            continue
        t, imsi, msg = ts(m.group(1)), m.group(2), m.group(3)
        if msg.startswith("Sending Initial Registration"):
            start[imsi] = t
        elif msg.startswith("PDU Session establishment is successful") and imsi in start and imsi not in attach:
            attach[imsi] = (t - start[imsi]) * 1000
    return attach


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--duration", type=int, default=10)
    ap.add_argument("--pings", type=int, default=50)
    args = ap.parse_args()
    sc = scn.load()
    n = sc["ues"]["count_per_slice"]
    rows: list[dict] = []
    run_id = time.strftime("a03-%Y%m%dT%H%M%S")
    for rep in range(1, args.reps + 1):
        scen = f"reference-rep{rep}"
        since = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() - 1)) + "Z"
        for s in sc["slices"]:
            att = restart_and_attach(f"ue-{s['id']}", n, since)
            for imsi, ms in sorted(att.items()):
                k = int(imsi) - int(sc["ues"]["imsi_base"]) - scn.slice_ids(sc).index(s["id"]) * n
                rows.append({"ts": load.now_iso(), "run_id": run_id, "scenario": scen, "slice": s["id"],
                             "ue_id": sc["ues"]["id_pattern"].format(slice=s["id"], nn=k + 1), "profile": "attachement",
                             "tool": "ueransim-log", "metric": "attach_time_ms", "value": round(ms, 1), "unit": "ms"})
            print(f"rep {rep} {s['id']}: {len(att)}/{n} attachements, médiane "
                  f"{statistics.median(att.values()):.0f} ms" if att else f"rep {rep} {s['id']}: aucun attachement", flush=True)
        time.sleep(5)
        ues = load.list_ues(sc)
        for s in sc["slices"]:
            ue = next(u for u in ues if u.slice == s["id"])
            base = {"run_id": run_id, "scenario": scen, "slice": s["id"], "ue_id": ue.ue_id}
            for direction in ("dl", "ul"):
                r = load.iperf(ue, "tcp", direction, 0, args.duration)
                if "error" not in r:
                    rows.append({**base, "ts": load.now_iso(), "profile": f"reference-tcp-{direction}", "tool": "iperf3",
                                 "metric": "throughput_mbps", "value": round(r["throughput_mbps"], 3), "unit": "Mbit/s"})
                time.sleep(2)
            out = subprocess.run(["docker", "exec", ue.container, "ping", "-I", ue.iface, "-n", "-c", str(args.pings),
                                  "-i", "0.2", "-W", "1", load.gateway(sc, s["id"])], capture_output=True, text=True)
            rtts = [float(x) for x in load.RTT.findall(out.stdout)]
            for v in rtts:
                rows.append({**base, "ts": load.now_iso(), "profile": "reference-ping", "tool": "ping", "metric": "rtt_ms",
                             "value": v, "unit": "ms"})
            rows.append({**base, "ts": load.now_iso(), "profile": "reference-ping", "tool": "ping", "metric": "loss_ratio",
                         "value": round(1 - len(rtts) / args.pings, 4), "unit": "ratio"})
            print(f"rep {rep} {s['id']}: débit et RTT mesurés", flush=True)
    report.write_measures(rows, HERE / "results" / "baseline.csv")

    summary = []
    for s in scn.slice_ids(sc):
        def vals(metric: str, profile: str | None = None, sid: str = s) -> list[float]:
            return [r["value"] for r in rows if r["slice"] == sid and r["metric"] == metric
                    and (profile is None or r["profile"] == profile)]
        dl, ul = vals("throughput_mbps", "reference-tcp-dl"), vals("throughput_mbps", "reference-tcp-ul")
        rtt, att, loss = vals("rtt_ms"), vals("attach_time_ms"), vals("loss_ratio")
        q = lambda v, p: statistics.quantiles(v, n=100, method="inclusive")[p - 1] if len(v) > 1 else (v[0] if v else None)  # noqa: E731
        bw = next(x["bandwidth"] for x in sc["slices"] if x["id"] == s)
        summary.append({
            "slice": s, "repetitions": args.reps, "ceil_mbps": bw["ceil_mbps"],
            "debit_dl_moyen_mbps": round(statistics.mean(dl), 2), "debit_dl_ecart_type": round(statistics.pstdev(dl), 2),
            "debit_ul_moyen_mbps": round(statistics.mean(ul), 2), "debit_ul_ecart_type": round(statistics.pstdev(ul), 2),
            "rtt_moyen_ms": round(statistics.mean(rtt), 3), "rtt_p95_ms": round(q(rtt, 95), 3),
            "perte_moyenne": round(statistics.mean(loss), 4),
            "attachement_median_ms": round(statistics.median(att), 1) if att else None,
            "attachement_p95_ms": round(q(att, 95), 1) if att else None, "attachements": len(att),
        })
    report.write_csv(summary, HERE / "results" / "baseline_summary.csv")
    for r in summary:
        print(r)


if __name__ == "__main__":
    main()
