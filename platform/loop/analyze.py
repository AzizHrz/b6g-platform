"""Boucle autonome MAPE-K — Analyze (M10, T26.2) : détection des violations de SLA.

Compare l'instantané (I-03) aux SLA du scénario (latence p95, débit minimal, taux de perte). Ne décide rien.
"""
from __future__ import annotations


def sla_violations(snap: dict, sc: dict) -> list[dict]:
    """Liste des manquements : un élément par (slice, indicateur) hors SLA."""
    out = []
    slas = {s["id"]: s["sla"] for s in sc["slices"]}
    for sid, m in snap["slices"].items():
        sla = slas.get(sid)
        if not sla:
            continue
        p95 = m.get("latency_ms_p95")
        if p95 is not None and p95 > sla["latency_ms_p95_max"]:
            out.append({"slice": sid, "metric": "latency_ms_p95", "value": p95, "sla": sla["latency_ms_p95_max"]})
        loss = m.get("loss_ratio")
        if loss is not None and loss > sla["loss_ratio_max"]:
            out.append({"slice": sid, "metric": "loss_ratio", "value": loss, "sla": sla["loss_ratio_max"]})
        thr = m.get("throughput_mbps")
        if thr is not None and m.get("sessions") and thr < sla["throughput_mbps_min"] and p95 and p95 > sla["latency_ms_p95_max"]:
            out.append({"slice": sid, "metric": "throughput_mbps", "value": thr, "sla": sla["throughput_mbps_min"]})
    return out


def sla_ok(snap: dict, sc: dict) -> bool:
    return not sla_violations(snap, sc)
