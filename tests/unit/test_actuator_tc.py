"""Actionneur v1, backend tc : commandes produites, sans Docker (exécuteur factice)."""
import pytest
from b6g_actuator.backends import TcBackend


class FakeRunner:
    def __init__(self, qdisc_out: str = ""):
        self.calls: list[tuple[str, ...]] = []
        self.qdisc_out = qdisc_out

    def __call__(self, container: str, *cmd: str) -> str:
        self.calls.append((container, *cmd))
        if cmd[:3] == ("tc", "qdisc", "show"):
            return self.qdisc_out
        if cmd[0] == "cat":
            return "8000\n1000\n"
        return ""


def test_bandwidth_modifie_la_classe_de_la_bonne_upf(sc):
    run = FakeRunner(qdisc_out="qdisc htb 1: root")
    be = TcBackend(sc, runner=run)
    state = {"slices": {"v2x": {"rate_mbps": 20, "ceil_mbps": 40, "active": True}}}
    be.apply({"type": "slice.bandwidth", "target": "v2x", "params": {"rate_mbps": 5, "ceil_mbps": 10}, "reason": "t"},
             state)
    assert all(c[0] == "upf-v2x" for c in run.calls)
    assert ("upf-v2x", "tc", "class", "replace", "dev", "ogstun", "parent", "1:1", "classid", "1:10", "htb",
            "rate", "5mbit", "ceil", "10mbit") in run.calls
    assert not any(c[1:4] == ("tc", "qdisc", "add") for c in run.calls)  # racine HTB déjà présente
    assert any("police" in c and "10mbit" in c for c in run.calls)       # sens montant plafonné à ceil
    assert state["slices"]["v2x"]["rate_mbps"] == 5 and state["slices"]["v2x"]["ceil_mbps"] == 10


def test_racine_htb_creee_si_absente(sc):
    run = FakeRunner(qdisc_out="qdisc noqueue 0: root")
    TcBackend(sc, runner=run).setup({"slices": {"embb": {"rate_mbps": 60, "ceil_mbps": 100}}})
    assert ("upf-embb", "tc", "qdisc", "add", "dev", "ogstun", "root", "handle", "1:", "htb", "default", "10") in run.calls


def test_types_v2_refuses_explicitement(sc):
    be = TcBackend(sc, runner=FakeRunner())
    with pytest.raises(RuntimeError, match="v2"):
        be.apply({"type": "link.netem", "target": "n6-v2x", "params": {"delay_ms": 10}, "reason": "t"}, {})


def test_compteurs_octets_par_slice_et_sens(sc):
    lines = TcBackend(sc, runner=FakeRunner()).metrics()
    assert 'b6g_slice_tun_bytes_total{slice="v2x",direction="dl"} 8000' in lines
    assert 'b6g_slice_tun_bytes_total{slice="v2x",direction="ul"} 1000' in lines
