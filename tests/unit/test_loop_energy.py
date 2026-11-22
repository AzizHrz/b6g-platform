"""Tests sans plateforme : Analyze (SLA), validation de sécurité du jumeau (Decide), modèle de puissance (énergie)."""
import importlib.util
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


analyze = _load("platform/loop/analyze.py", "analyze")
decide = _load("platform/loop/decide.py", "decide")
energy = _load("platform/energy/energy_exporter.py", "energy_exporter")


def snap(**over):
    # Débit au-dessus du minimum de chaque SLA pour n'isoler que la violation testée
    thr = {"embb": 30.0, "v2x": 5.0, "miot": 1.0}
    base = {s: {"latency_ms_p95": 3.0, "throughput_mbps": thr[s], "loss_ratio": 0.0, "sessions": 10,
                "bw_limit_mbps": 20} for s in ("embb", "v2x", "miot")}
    for sid, v in over.items():
        base[sid].update(v)
    return {"slices": base}


def test_analyze_detecte_violation_latence(sc):
    v = analyze.sla_violations(snap(v2x={"latency_ms_p95": 80.0}), sc)
    assert [(x["slice"], x["metric"]) for x in v] == [("v2x", "latency_ms_p95")]
    assert analyze.sla_ok(snap(), sc) is True


def test_decide_jumeau_refuse_si_nouvelle_violation(sc):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/decide"):
            return httpx.Response(200, json={"decision_id": "d1", "actions": [
                {"type": "slice.bandwidth", "target": "v2x", "params": {"rate_mbps": 30, "ceil_mbps": 40}}]})
        # Le jumeau prévoit une NOUVELLE violation sur embb (effet de bord) -> action refusée
        return httpx.Response(200, json={"sla_ok": False, "violations": [
            {"slice": "embb", "metric": "throughput_mbps"}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    d = decide.Decider("http://dec", "http://twin", client=client)
    res = d.decide(snap(v2x={"latency_ms_p95": 80.0}), sc)
    assert res["actions"] == [] and len(res["rejected"]) == 1


def test_decide_jumeau_accepte_si_pas_de_nouvelle_violation(sc):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/decide"):
            return httpx.Response(200, json={"decision_id": "d2", "actions": [
                {"type": "slice.bandwidth", "target": "v2x", "params": {"rate_mbps": 30, "ceil_mbps": 40}}]})
        # Même violation v2x qu'avant (pas de nouvelle) -> action retenue (amélioration progressive)
        return httpx.Response(200, json={"sla_ok": False, "violations": [
            {"slice": "v2x", "metric": "latency_ms_p95"}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    d = decide.Decider("http://dec", "http://twin", client=client)
    res = d.decide(snap(v2x={"latency_ms_p95": 80.0}), sc)
    assert len(res["actions"]) == 1 and res["rejected"] == []


def test_modele_puissance_par_prefixe():
    model = energy.load_model()
    assert energy.power_params("gnb", model) == (5.0, 25.0)
    assert energy.power_params("upf-v2x", model)[1] == 15.0      # classe « upf- »
    assert energy.power_params("amf", model) == (model["default"]["p_idle_w"], model["default"]["p_max_w"])


def test_energie_composant_arrete_tombe_a_zero(sc):
    em = energy.EnergyModel(energy.load_model(), "http://prom")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        comps = [("amf", 0.5), ("gnb", 0.4)] if calls["n"] == 1 else [("gnb", 0.4)]
        return httpx.Response(200, json={"data": {"result": [
            {"metric": {"nf": c}, "value": [0, str(v)]} for c, v in comps]}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    em.step(client)
    assert em.power["amf"] > 0
    em.step(client)   # deuxième relevé sans amf (composant arrêté) : puissance remise à 0
    assert em.power["amf"] == 0.0 and em.power["gnb"] > 0
