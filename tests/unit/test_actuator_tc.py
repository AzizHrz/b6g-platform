"""Actionneur v1 et v2, backend tc : commandes produites, sans Docker (exécuteur factice)."""
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
    assert any("police" in c and "10mbit" in c and "100" in c for c in run.calls)   # policer montant, prio 100
    assert state["slices"]["v2x"]["rate_mbps"] == 5 and state["slices"]["v2x"]["ceil_mbps"] == 10


def test_racine_htb_creee_si_absente(sc):
    run = FakeRunner(qdisc_out="qdisc noqueue 0: root")
    TcBackend(sc, runner=run).setup({"slices": {"embb": {"rate_mbps": 60, "ceil_mbps": 100}}})
    assert ("upf-embb", "tc", "qdisc", "add", "dev", "ogstun", "root", "handle", "1:", "htb", "default", "10") in run.calls


class FakeHost:
    def __init__(self, outputs: dict[str, str] | None = None):
        self.calls: list[tuple[str, ...]] = []
        self.outputs = outputs or {}

    def __call__(self, *cmd: str) -> str:
        self.calls.append(cmd)
        return next((v for k, v in self.outputs.items() if k in " ".join(cmd)), "")


def state():
    return {"slices": {"embb": {"rate_mbps": 60, "ceil_mbps": 100, "active": True}},
            "links": {}, "deployments": {"b6g-echo-app": {"replicas": 1, "tier": "cloud"}}, "isolated_ues": []}


def test_netem_niveau_par_conteneur_appoint_dans_le_noeud(sc):
    host = FakeHost()
    TcBackend(sc, runner=FakeRunner(), host=host).apply(
        {"type": "link.netem", "target": "tier-edge", "params": {"delay_ms": 2}, "reason": "t"}, state())
    cmd = host.calls[0]
    assert cmd[:4] == ("docker", "run", "--rm", "--net") and cmd[4] == "container:k3d-b6g-agent-0"
    assert cmd[-8:] == ("qdisc", "replace", "dev", "eth0", "root", "netem", "delay", "2ms")


def test_netem_n6_sous_la_classe_htb_de_la_slice(sc):
    run = FakeRunner()
    TcBackend(sc, runner=run, host=FakeHost()).apply(
        {"type": "link.netem", "target": "n6-v2x", "params": {"delay_ms": 30, "loss_pct": 1}, "reason": "t"}, state())
    assert ("upf-v2x", "tc", "qdisc", "replace", "dev", "ogstun", "parent", "1:10", "handle", "10:", "netem", "delay",
            "30ms", "loss", "1%") in run.calls


def test_placement_par_nodeselector(sc):
    host = FakeHost({"get deploy": "b6g-cloud"})
    TcBackend(sc, runner=FakeRunner(), host=host).apply(
        {"type": "deployment.placement", "target": "b6g-echo-app", "params": {"tier": "edge"}, "reason": "t"}, state())
    patch = host.calls[-1]
    assert "patch" in patch and "b6g-cloud" in patch and '"b6g/tier": "edge"' in patch[-1]


def test_isolement_ue_filtres_dans_son_upf(sc):
    class UeRunner(FakeRunner):
        def __call__(self, container, *cmd):
            if cmd[:2] == ("ip", "-o"):
                self.calls.append((container, *cmd))
                return "5: uesimtun2    inet 10.46.1.7/16 scope global uesimtun2"
            return super().__call__(container, *cmd)

    run = UeRunner()
    st = state()
    TcBackend(sc, runner=run, host=FakeHost()).apply({"type": "ue.isolate", "target": "ue-v2x-03", "params": {},
                                                      "reason": "t"}, st)
    adds = [c for c in run.calls if c[0] == "upf-v2x" and "add" in c]
    assert any("dst" in c and "10.46.1.7/32" in c and "13" in c for c in adds)   # prio 13 : 10 UEs embb + 3
    assert any("src" in c and "ffff:" in c for c in adds)
    assert st["isolated_ues"] == ["ue-v2x-03"]


def test_arret_de_slice(sc):
    host = FakeHost()
    TcBackend(sc, runner=FakeRunner(), host=host).apply(
        {"type": "slice.state", "target": "miot", "params": {"active": False}, "reason": "t"},
        {"slices": {"miot": {"rate_mbps": 5, "ceil_mbps": 10, "active": True}}})
    assert host.calls == [("docker", "stop", "smf-miot", "upf-miot")]


def test_compteurs_octets_par_slice_et_sens(sc):
    lines = TcBackend(sc, runner=FakeRunner()).metrics()
    assert 'b6g_slice_tun_bytes_total{slice="v2x",direction="dl"} 8000' in lines
    assert 'b6g_slice_tun_bytes_total{slice="v2x",direction="ul"} 1000' in lines


def test_netem_gnb_par_conteneur_appoint(sc):
    """Le conteneur gNB n'a pas NET_ADMIN : netem appliqué depuis un conteneur d'appoint dans son espace réseau."""
    host = FakeHost()
    TcBackend(sc, runner=FakeRunner(), host=host).apply(
        {"type": "link.netem", "target": "n2n3-gnb1", "params": {"delay_ms": 20}, "reason": "t"}, state())
    assert host.calls[0][4] == "container:gnb" and host.calls[0][-2:] == ("delay", "20ms")
