"""slice-autoscaler : décisions de la règle à seuils, sans plateforme."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("slice_autoscaler", ROOT / "platform" / "loop" / "slice_autoscaler.py")
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


def snap(**slices):
    base = {"throughput_mbps": 0.1, "latency_ms_p95": 3.0}
    return {"slices": {s: {**base, **slices.get(s, {})} for s in ("embb", "v2x", "miot")}}


def state(**over):
    st = {"embb": {"rate_mbps": 60, "ceil_mbps": 100}, "v2x": {"rate_mbps": 20, "ceil_mbps": 40},
          "miot": {"rate_mbps": 5, "ceil_mbps": 10}}
    st.update(over)
    return st


def test_latence_hors_sla_releve_la_slice(sc):
    a = mod.SliceAutoscaler(sc, "http://p", "http://a")
    d = a.decide(snap(v2x={"latency_ms_p95": 80.0}), state(), now=100)
    assert len(d) == 1
    sid, rate, ceil, reason = d[0]
    assert sid == "v2x" and ceil == 60 and rate == 30 and "SLA" in reason


def test_capacite_totale_respectee(sc):
    a = mod.SliceAutoscaler(sc, "http://p", "http://a")
    d = a.decide(snap(embb={"throughput_mbps": 99.0}), state(), now=100)
    sid, rate, ceil, _ = d[0]
    assert sid == "embb" and ceil == 150 and rate == 90       # 1,5 × 60, et 90 + 20 + 5 ≤ 150
    d = a.decide(snap(embb={"throughput_mbps": 149.0}), state(embb={"rate_mbps": 125, "ceil_mbps": 150}), now=100)
    assert d == []                                               # déjà au maximum : aucune action


def test_periode_de_garde(sc):
    a = mod.SliceAutoscaler(sc, "http://p", "http://a", cooldown_s=10)
    a.last_action["v2x"] = 95
    assert a.decide(snap(v2x={"latency_ms_p95": 80.0}), state(), now=100) == []


def test_retour_aux_valeurs_du_scenario(sc):
    a = mod.SliceAutoscaler(sc, "http://p", "http://a")
    d = a.decide(snap(v2x={"throughput_mbps": 0.2}), state(v2x={"rate_mbps": 45, "ceil_mbps": 90}), now=100)
    assert d and d[0][:3] == ("v2x", 20, 40)
