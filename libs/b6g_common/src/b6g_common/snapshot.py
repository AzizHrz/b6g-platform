"""I-03 : construction du MetricSnapshot à partir des métriques Prometheus b6g_* (I-02).

Règles : les 3 slices et les 3 niveaux sont toujours présents ; une valeur absente vaut None (null),
jamais 0 ; les valeurs sont des moyennes sur window_s (avg_over_time).
"""
from __future__ import annotations

from collections import defaultdict

import httpx

from . import scenario as scn
from .schemas import validate
from .timeutil import now_iso

METRICS = [
    "b6g_slice_throughput_mbps", "b6g_slice_latency_ms", "b6g_slice_loss_ratio", "b6g_slice_bw_limit_mbps",
    "b6g_slice_sessions", "b6g_nf_cpu_ratio", "b6g_nf_memory_bytes", "b6g_link_delay_ms", "b6g_k8s_replicas",
    "b6g_energy_power_watts",
]


def _query(client: httpx.Client, prom_url: str, metric: str, window_s: int, ts: str | None) -> list[dict]:
    params = {"query": f"avg_over_time({metric}[{window_s}s])"}
    if ts:
        params["time"] = ts
    r = client.get(f"{prom_url.rstrip('/')}/api/v1/query", params=params, timeout=5)
    r.raise_for_status()
    body = r.json()
    if body.get("status") != "success":
        return []
    out = []
    for item in body["data"]["result"]:
        try:
            out.append({"labels": item["metric"], "value": float(item["value"][1])})
        except (KeyError, ValueError, IndexError):
            continue
    return out


def empty(sc: dict, ts: str | None = None, window_s: int = 30) -> dict:
    """Instantané vide : toutes les valeurs à None."""
    return {
        "schema": "b6g.snapshot.v1",
        "ts": ts or now_iso(),
        "window_s": window_s,
        "slices": {s: {"throughput_mbps": None, "latency_ms_p50": None, "latency_ms_p95": None,
                       "loss_ratio": None, "bw_limit_mbps": None, "sessions": None} for s in scn.slice_ids(sc)},
        "nfs": {},
        "tiers": {t: {"cpu_ratio": None, "replicas": {d: None for d in sc.get("deployments", [])}}
                  for t in scn.tier_ids(sc)},
        "links": {lk: {"delay_ms": None} for lk in sc["links"]},
        "energy": {"total_power_watts": None},
    }


def from_series(series: dict[str, list[dict]], sc: dict, ts: str | None = None, window_s: int = 30) -> dict:
    """Assemble un snapshot depuis {metric: [{labels, value}]} (utile pour les tests et le rejeu)."""
    snap = empty(sc, ts, window_s)
    sl = snap["slices"]
    thr = defaultdict(float)
    seen_thr = set()
    for x in series.get("b6g_slice_throughput_mbps", []):
        s = x["labels"].get("slice")
        if s in sl:
            thr[s] += x["value"]
            seen_thr.add(s)
    for s in seen_thr:
        sl[s]["throughput_mbps"] = round(thr[s], 3)
    for x in series.get("b6g_slice_latency_ms", []):
        s, q = x["labels"].get("slice"), x["labels"].get("quantile")
        if s in sl and q in ("0.5", "0.95"):
            sl[s]["latency_ms_p50" if q == "0.5" else "latency_ms_p95"] = round(x["value"], 3)
    for metric, key, cast in (("b6g_slice_loss_ratio", "loss_ratio", float),
                              ("b6g_slice_bw_limit_mbps", "bw_limit_mbps", float),
                              ("b6g_slice_sessions", "sessions", lambda v: int(round(v)))):
        for x in series.get(metric, []):
            s = x["labels"].get("slice")
            if s in sl:
                v = cast(x["value"])
                sl[s][key] = min(max(v, 0.0), 1.0) if key == "loss_ratio" else v
    node_to_tier = {t["k8s_node"]: name for name, t in sc["tiers"].items()}
    for x in series.get("b6g_nf_cpu_ratio", []):
        nf = x["labels"].get("nf")
        if not nf:
            continue
        if nf in node_to_tier:  # CPU d'un nœud k3d = CPU du niveau
            snap["tiers"][node_to_tier[nf]]["cpu_ratio"] = round(min(max(x["value"], 0.0), 1.0), 4)
            continue
        snap["nfs"].setdefault(nf, {"cpu_ratio": None, "memory_bytes": None})["cpu_ratio"] = round(x["value"], 4)
    for x in series.get("b6g_nf_memory_bytes", []):
        nf = x["labels"].get("nf")
        if nf and nf not in node_to_tier:
            snap["nfs"].setdefault(nf, {"cpu_ratio": None, "memory_bytes": None})["memory_bytes"] = int(x["value"])
    for x in series.get("b6g_k8s_replicas", []):
        t, d = x["labels"].get("tier"), x["labels"].get("deployment")
        if t in snap["tiers"] and d:
            snap["tiers"][t]["replicas"][d] = int(round(x["value"]))
    for x in series.get("b6g_link_delay_ms", []):
        lk = x["labels"].get("link")
        if lk in snap["links"]:
            snap["links"][lk]["delay_ms"] = round(x["value"], 3)
    power = [x["value"] for x in series.get("b6g_energy_power_watts", [])]
    if power:
        snap["energy"]["total_power_watts"] = round(sum(power), 2)
    return validate(snap, "metric-snapshot")


def build(prom_url: str, ts: str | None = None, window_s: int = 30, sc: dict | None = None,
          client: httpx.Client | None = None) -> dict:
    """Construit le MetricSnapshot courant (ou à l'instant ts) depuis Prometheus."""
    sc = sc or scn.default()
    own = client is None
    client = client or httpx.Client()
    try:
        series = {m: _query(client, prom_url, m, window_s, ts) for m in METRICS}
    finally:
        if own:
            client.close()
    return from_series(series, sc, ts=ts, window_s=window_s)
