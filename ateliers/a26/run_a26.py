"""Atelier 26 — boucle autonome MAPE-K : démonstration (T26.4).

    .venv/bin/python ateliers/a26/run_a26.py [--iterations 10]

Prérequis : make up-core up-obs up-actuator up-probes up-ledger up-mocks-ia (mock_decision :8090, mock_twin :8091).
Déroulement : dégradation contrôlée de la slice v2x (plafond abaissé + charge UDP qui le dépasse → latence hors SLA),
puis la boucle Monitor → Analyze → Decide (API Décision validée par le Jumeau) → Act → Learn s'exécute en continu.
L'action `slice.bandwidth` relève le plafond, la congestion se résorbe, le SLA est rétabli, et la boucle poursuit sans
intervention. Réalisme : ÉMULÉ. Produit results/loop.csv (issues des itérations) et datasets/raw/actions_log.csv (D8).
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from b6g_common import scenario as scn

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "platform" / "loop"))
from act_learn import MapeK  # noqa: E402

PROM, ACT = "http://127.0.0.1:9090", "http://127.0.0.1:8081"


def act(params: dict, target: str = "v2x", reason: str = "atelier 26") -> None:
    body = json.dumps({"type": "slice.bandwidth", "target": target, "params": params, "reason": reason}).encode()
    req = urllib.request.Request(f"{ACT}/v1/actions", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-B6G-Caller": "atelier-a26"})
    urllib.request.urlopen(req, timeout=10).read()


def v2x_load(start: bool) -> None:
    """Charge TCP descendante sur un UE v2x : sous le plafond abaissé, la file HTB se remplit et la latence monte
    (sans perte, car TCP s'adapte) ; une fois le plafond relevé, la file se vide et la latence redescend."""
    ue_ip = subprocess.run(["docker", "exec", "ue-v2x", "sh", "-c",
                            "ip -o -4 addr show uesimtun0 | awk '{print $4}' | cut -d/ -f1"],
                           capture_output=True, text=True).stdout.strip()
    subprocess.run(["docker", "exec", "ue-v2x", "pkill", "iperf3"], capture_output=True)
    if start:
        subprocess.Popen(["docker", "exec", "ue-v2x", "iperf3", "-c", "iperf", "-p", "5211", "-B", ue_ip,
                          "-R", "-t", "600"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--iterations", type=int, default=10)
    args = ap.parse_args()
    sc = scn.load()
    init = next(s["bandwidth"] for s in sc["slices"] if s["id"] == "v2x")
    d8 = ROOT / "datasets" / "raw" / "actions_log.csv"
    d8.unlink(missing_ok=True)
    loop = MapeK(PROM, ACT, "http://127.0.0.1:8090", "http://127.0.0.1:8091", "http://127.0.0.1:8082",
                "http://127.0.0.1:9091", sc, d8)
    try:
        # Dégradation : plafond v2x abaissé sous la charge offerte
        act({"rate_mbps": 4, "ceil_mbps": 4}, reason="atelier 26 : dégradation (plafond v2x abaissé)")
        v2x_load(True)
        time.sleep(20)   # laisser la latence monter et la chaîne de mesure la voir
        rows = loop.run(args.iterations)
    finally:
        v2x_load(False)
        act({"rate_mbps": init["rate_mbps"], "ceil_mbps": init["ceil_mbps"]}, reason="atelier 26 : retour au scénario")
    res_dir = HERE / "results"
    res_dir.mkdir(parents=True, exist_ok=True)
    cols = ["ts", "outcome", "violations", "actions", "decision_id", "rejected", "sla_ok_before", "sla_ok_after"]
    with (res_dir / "loop.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    resolved = sum(1 for r in rows if r.get("outcome") == "resolved")
    noact = sum(1 for r in rows if r.get("outcome") == "no_action")
    first = next((i for i, r in enumerate(rows) if r.get("sla_ok_after")), None)
    print(f"itérations : {len(rows)} ; compteurs {loop.counts} ; SLA rétabli dès l'itération {first} ; "
          f"{resolved} resolved, {noact} no_action", flush=True)


if __name__ == "__main__":
    main()
