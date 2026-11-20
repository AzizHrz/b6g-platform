"""Mock I-02 : publie les 16 métriques b6g_* avec des profils de journée, et une mini API Prometheus.

Réalisme : SYNTHÉTIQUE. Sert tant que la plateforme réelle (INT1) n'est pas disponible.

    uvicorn mocks.platform.fake_exporter:app --port 9100
    curl localhost:9100/metrics
    curl 'localhost:9100/api/v1/query?query=avg_over_time(b6g_slice_latency_ms[30s])'
    curl -X POST localhost:9100/profile/peak     # day | peak | incident | night | satellite

La mini API ne comprend que `NOM` et `avg_over_time(NOM[..s])` (et un filtre {cle="val"} simple) :
c'est ce qu'utilise b6g_common.snapshot.build(). Elle renvoie la valeur courante du profil.
"""
from __future__ import annotations

import random
import re
import time

from b6g_common import scenario as scn
from fastapi import FastAPI, Query
from fastapi.responses import PlainTextResponse

# 16 métriques du contrat I-02 : nom -> (type, étiquettes)
METRICS: dict[str, tuple[str, tuple[str, ...]]] = {
    "b6g_slice_sessions": ("gauge", ("slice",)),
    "b6g_ue_registered": ("gauge", ()),
    "b6g_slice_throughput_mbps": ("gauge", ("slice", "direction")),
    "b6g_slice_latency_ms": ("gauge", ("slice", "quantile")),
    "b6g_slice_loss_ratio": ("gauge", ("slice",)),
    "b6g_slice_bw_limit_mbps": ("gauge", ("slice",)),
    "b6g_nf_cpu_ratio": ("gauge", ("nf",)),
    "b6g_nf_memory_bytes": ("gauge", ("nf",)),
    "b6g_link_delay_ms": ("gauge", ("link",)),
    "b6g_k8s_replicas": ("gauge", ("deployment", "tier")),
    "b6g_app_request_latency_ms": ("summary", ("app", "tier", "quantile")),
    "b6g_energy_power_watts": ("gauge", ("component",)),
    "b6g_energy_joules_total": ("counter", ("component",)),
    "b6g_actions_total": ("counter", ("type", "status")),
    "b6g_loop_iterations_total": ("counter", ("outcome",)),
    "b6g_security_alerts_total": ("counter", ("class",)),
}

# Charge offerte (Mbit/s) et facteurs de dégradation par profil
PROFILES = {
    "day":       {"load": {"embb": 45, "v2x": 3.0, "miot": 0.8}, "lat_x": 1.0, "loss_x": 1.0, "sat": False, "cpu": 0.35},
    "peak":      {"load": {"embb": 95, "v2x": 4.5, "miot": 1.2}, "lat_x": 1.0, "loss_x": 1.0, "sat": False, "cpu": 0.75},
    "incident":  {"load": {"embb": 98, "v2x": 4.0, "miot": 1.0}, "lat_x": 2.0, "loss_x": 6.0, "sat": False, "cpu": 0.85},
    "night":     {"load": {"embb": 6, "v2x": 0.6, "miot": 0.5}, "lat_x": 1.0, "loss_x": 1.0, "sat": False, "cpu": 0.10},
    "satellite": {"load": {"embb": 20, "v2x": 2.0, "miot": 0.6}, "lat_x": 1.0, "loss_x": 3.0, "sat": True, "cpu": 0.30},
}
BASE_LAT = {"embb": 15.0, "v2x": 6.0, "miot": 40.0}
NFS = ["amf", "smf", "upf", "nrf", "ausf", "udm", "udr", "pcf", "nssf", "bsf", "gnb"]


def generate(profile: str, sc: dict, seed: int = 0, bandwidth: dict | None = None,
             drop: tuple[str, ...] = ()) -> dict[str, list[dict]]:
    """Séries {métrique: [{labels, value}]} pour un profil. `drop` retire des métriques (test du null)."""
    p = PROFILES[profile]
    rnd = random.Random(f"{profile}-{seed}")
    jit = lambda v, r=0.05: v * (1 + rnd.uniform(-r, r))  # noqa: E731
    bw = {s["id"]: dict(s["bandwidth"]) for s in sc["slices"]}
    if bandwidth:
        bw.update(bandwidth)
    n_ue = sc["ues"]["count_per_slice"]
    out: dict[str, list[dict]] = {m: [] for m in METRICS}
    add = lambda m, labels, v: out[m].append({"labels": labels, "value": float(v)})  # noqa: E731
    add("b6g_ue_registered", {}, 3 * n_ue)
    # Interférence : quand embb sature le lien partagé, les autres slices attendent aussi (UPF commune)
    cong = min(p["load"]["embb"] / bw["embb"]["rate_mbps"], 1.5)
    shared_ms = 12 * max(0.0, cong - 0.9)
    for s in scn.slice_ids(sc):
        offered, limit = p["load"][s], bw[s]["rate_mbps"]
        util = min(offered / limit, 0.999)
        served = min(offered, limit)
        q = 1 / (1 - util)                       # M/M/1 : retard ∝ 1/(1-ρ)
        p50 = (BASE_LAT[s] * min(q, 8) * 0.6 + (shared_ms if s != "embb" else 0)) * p["lat_x"]
        p95 = p50 * 2.3
        if p["sat"]:
            p50, p95 = p50 + 30, p95 + 45
        loss = min(0.0002 * q * p["loss_x"] + (0.02 if offered > limit else 0), 0.5)
        add("b6g_slice_sessions", {"slice": s}, n_ue)
        add("b6g_slice_throughput_mbps", {"slice": s, "direction": "dl"}, jit(served * (0.85 if s == "embb" else 0.2)))
        add("b6g_slice_throughput_mbps", {"slice": s, "direction": "ul"}, jit(served * (0.15 if s == "embb" else 0.8)))
        add("b6g_slice_latency_ms", {"slice": s, "quantile": "0.5"}, jit(p50))
        add("b6g_slice_latency_ms", {"slice": s, "quantile": "0.95"}, jit(p95))
        add("b6g_slice_loss_ratio", {"slice": s}, jit(loss, 0.1))
        add("b6g_slice_bw_limit_mbps", {"slice": s}, limit)
    for nf in NFS:
        cpu = p["cpu"] * (1.4 if nf in ("upf", "gnb") else 0.3)
        add("b6g_nf_cpu_ratio", {"nf": nf}, jit(min(cpu, 0.99)))
        add("b6g_nf_memory_bytes", {"nf": nf}, int(jit(80e6 if nf in ("upf", "gnb") else 40e6)))
    for t in sc["tiers"].values():
        add("b6g_nf_cpu_ratio", {"nf": t["k8s_node"]}, jit(min(p["cpu"] * 0.9, 0.99)))
    for lk in sc["links"]:
        d = 0.0
        if lk.startswith("tier-"):
            d = sc["tiers"][lk[5:]]["added_rtt_ms"]
        if p["sat"] and lk == "n2n3-gnb1":
            d = 30.0
        add("b6g_link_delay_ms", {"link": lk}, d)
    reps = 3 if profile in ("peak", "incident") else (0 if profile == "night" else 1)
    for t in sc["tiers"]:
        for dep in sc.get("deployments", []):
            add("b6g_k8s_replicas", {"deployment": dep, "tier": t}, reps if t == "edge" else 1)
        for q_ in ("0.5", "0.95"):
            base = 2 + sc["tiers"][t]["added_rtt_ms"]
            add("b6g_app_request_latency_ms", {"app": "edge-infer", "tier": t, "quantile": q_},
                jit(base * (2 if q_ == "0.95" else 1)))
    comps = {"core": 40 + 60 * p["cpu"], "ran": 30 + 20 * p["cpu"], "k8s": 50 + 80 * p["cpu"]}
    for c, w in comps.items():
        add("b6g_energy_power_watts", {"component": c}, jit(w))
        add("b6g_energy_joules_total", {"component": c}, w * 3600)
    add("b6g_actions_total", {"type": "slice.bandwidth", "status": "dry_run"}, 0)
    add("b6g_loop_iterations_total", {"outcome": "no_action"}, 0)
    add("b6g_security_alerts_total", {"class": "udp_flood"}, 1 if profile == "incident" else 0)
    for m in drop:
        out[m] = []
    return out


def exposition(series: dict[str, list[dict]]) -> str:
    """Format texte Prometheus 0.0.4."""
    lines = []
    for m, items in series.items():
        typ = METRICS[m][0]
        lines.append(f"# HELP {m} B6G contrat I-02 (mock)")
        lines.append(f"# TYPE {m} {typ}")
        for x in items:
            lab = ",".join(f'{k}="{v}"' for k, v in x["labels"].items())
            lines.append(f"{m}{{{lab}}} {x['value']}" if lab else f"{m} {x['value']}")
    return "\n".join(lines) + "\n"


_Q = re.compile(r"^\s*(?:avg_over_time\()?\s*([a-z_:][a-z0-9_:]*)\s*(\{[^}]*\})?\s*(?:\[\d+[smh]\])?\)?\s*$")
_L = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def query(series: dict[str, list[dict]], expr: str) -> list[dict]:
    m = _Q.match(expr)
    if not m:
        raise ValueError(f"expression non prise en charge par le mock : {expr}")
    name, sel = m.group(1), m.group(2) or ""
    want = dict(_L.findall(sel))
    return [x for x in series.get(name, []) if all(x["labels"].get(k) == v for k, v in want.items())]


def create_app(profile: str = "day", seed: int = 0) -> FastAPI:
    sc = scn.default()
    app = FastAPI(title="B6G fake_exporter (mock I-02)", version="1.0.0")
    app.state.profile, app.state.seed, app.state.drop = profile, seed, ()

    def current():
        return generate(app.state.profile, sc, app.state.seed, drop=app.state.drop)

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics():
        return exposition(current())

    @app.get("/api/v1/query")
    def api_query(query_: str = Query(alias="query"), time_: str | None = Query(None, alias="time")):
        try:
            res = query(current(), query_)
        except ValueError as e:
            return {"status": "error", "errorType": "bad_data", "error": str(e)}
        now = time.time()
        return {"status": "success", "data": {"resultType": "vector", "result": [
            {"metric": {"__name__": query_, **x["labels"]}, "value": [now, repr(x["value"])]} for x in res]}}

    @app.post("/profile/{name}")
    def set_profile(name: str, seed: int = 0):
        if name not in PROFILES:
            return {"error": f"profils : {sorted(PROFILES)}"}
        app.state.profile, app.state.seed = name, seed
        return {"profile": name, "seed": seed}

    return app


app = create_app()
