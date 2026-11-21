"""Jalon INT3 : cluster k3d à trois niveaux, edge-infer déployé, Actionneur v2, catalogue des données.

Critère (plan maître § 9.3) : CT-09, CT-10 et test_int3. Demande la plateforme et le cluster :
    make up-core up-obs up-actuator up-k8s k8s-connect k8s-namespaces k8s-obs
    kubectl apply -k platform/k8s/apps/echo-app ; kubectl apply -k platform/k8s/apps/edge-infer-edge
    .venv/bin/pytest -m int tests/integration/test_int3.py
Chaque action v2 est appliquée sur la plateforme réelle puis vérifiée par son effet, et l'état initial est rétabli.
L'image edge-infer est la version de remplacement (MAQUETTE) tant que l'équipe 2 n'a pas livré la sienne.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from b6g_common import scenario as scn

pytestmark = pytest.mark.int

ROOT = Path(__file__).resolve().parents[2]
KUBECTL = str(Path.home() / "b6g-ext" / "bin" / "kubectl")
ACT = os.environ.get("B6G_ACTUATOR_URL", "http://127.0.0.1:8081")
PROM = os.environ.get("B6G_PROM_URL", "http://127.0.0.1:9090")
RTT = re.compile(r"time=([\d.]+) ms")


def kubectl(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run([KUBECTL, *args], capture_output=True, text=True, check=check)


def node_ip(node: str) -> str:
    return subprocess.run(["docker", "inspect", "-f", '{{(index .NetworkSettings.Networks "k3d-b6g").IPAddress}}', node],
                          capture_output=True, text=True, check=True).stdout.strip()


def act(type_: str, target: str, params: dict) -> dict:
    r = httpx.post(f"{ACT}/v1/actions", json={"type": type_, "target": target, "params": params,
                                              "reason": f"test_int3 : {type_}"},
                   headers={"X-B6G-Caller": "test_int3"}, timeout=120)
    res = r.json()
    assert res.get("status") == "applied", res
    return res


def ue_ping(container: str, iface: str, dest: str, count: int = 5) -> list[float]:
    out = subprocess.run(["docker", "exec", container, "ping", "-I", iface, "-n", "-c", str(count), "-i", "0.2", "-W",
                          "1", dest], capture_output=True, text=True).stdout
    return [float(x) for x in RTT.findall(out)]


def wait(cond, timeout: float = 120, step: float = 1) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(step)
    return False


@pytest.fixture(scope="module")
def sc():
    return scn.load()


@pytest.fixture(scope="module", autouse=True)
def platform_up():
    try:
        httpx.get(f"{ACT}/v1/health", timeout=3).raise_for_status()
        kubectl("get", "nodes")
    except (httpx.HTTPError, subprocess.CalledProcessError, FileNotFoundError) as e:
        pytest.skip(f"plateforme ou cluster indisponible ({e})")


def test_actionneur_v2(sc):
    h = httpx.get(f"{ACT}/v1/health", timeout=3).json()
    assert h["backend"] == "tc" and h["version"].startswith("2."), h


def test_cluster_trois_niveaux(sc):
    nodes = json.loads(kubectl("get", "nodes", "-o", "json").stdout)["items"]
    tiers = {n["metadata"]["name"]: n["metadata"]["labels"].get("b6g/tier") for n in nodes}
    for tier, t in sc["tiers"].items():
        assert tiers.get(t["k8s_node"]) == tier, tiers


def test_ct09_edge_infer_sur_l_edge(sc):
    url = f"http://{node_ip(sc['tiers']['edge']['k8s_node'])}:{sc['ports']['edge_infer_nodeport']}/v1"
    assert httpx.get(f"{url}/health", timeout=3).json()["status"] == "ok"
    body = {"request_id": "ct09", "features": {"throughput_mbps": 80, "latency_ms_p95": 30, "loss_ratio": 0.001,
                                               "cpu_ratio": 0.4}}
    lat = []
    for _ in range(20):
        r = httpx.post(f"{url}/infer", json=body, headers={"X-B6G-Caller": "ct09"}, timeout=3).json()
        assert {"request_id", "prediction", "score", "model_version", "server_latency_ms"} <= set(r)
        assert r["prediction"] in ("congested", "normal") and 0 <= r["score"] <= 1
        lat.append(r["server_latency_ms"])
    assert max(lat) < 50, lat


@pytest.mark.parametrize("app", sorted(p.name for p in (ROOT / "platform" / "k8s" / "apps").iterdir() if p.is_dir()))
def test_ct10_gabarit_dry_run_serveur(app):
    res = kubectl("apply", "-k", str(ROOT / "platform" / "k8s" / "apps" / app), "--dry-run=server", check=False)
    assert res.returncode == 0, res.stderr


def test_link_netem_n6_mesure(sc):
    gw = "10.46.0.1"
    base = min(ue_ping("ue-v2x", "uesimtun1", gw))
    try:
        act("link.netem", "n6-v2x", {"delay_ms": 30})
        with_delay = min(ue_ping("ue-v2x", "uesimtun1", gw))
        assert with_delay >= base + 25, (base, with_delay)
    finally:
        act("link.netem", "n6-v2x", {})
    assert min(ue_ping("ue-v2x", "uesimtun1", gw)) < base + 10


def ready_on(node: str | None = None, count: int | None = None) -> bool:
    pods = json.loads(kubectl("-n", "b6g-cloud", "get", "pods", "-l", "app=b6g-echo-app", "-o", "json").stdout)["items"]
    live = [p for p in pods if not p["metadata"].get("deletionTimestamp")
            and any(c["type"] == "Ready" and c["status"] == "True" for c in p["status"].get("conditions", []))]
    if count is not None and len(live) != count:
        return False
    return bool(live) and (node is None or all(p["spec"]["nodeName"] == node for p in live))


def test_deployment_replicas_et_placement(sc):
    kubectl("-n", "b6g-cloud", "patch", "hpa", "b6g-echo-app", "--type=merge", "-p", '{"spec":{"minReplicas":1}}')
    act("deployment.replicas", "b6g-echo-app", {"replicas": 3})
    assert wait(lambda: ready_on(count=3), 90)
    act("deployment.replicas", "b6g-echo-app", {"replicas": 1})
    try:
        act("deployment.placement", "b6g-echo-app", {"tier": "edge"})
        assert wait(lambda: ready_on(sc["tiers"]["edge"]["k8s_node"]), 120)
    finally:
        act("deployment.placement", "b6g-echo-app", {"tier": "cloud"})
    assert wait(lambda: ready_on(sc["tiers"]["cloud"]["k8s_node"]), 120)


def test_ue_isolate_puis_release(sc):
    assert ue_ping("ue-miot", "uesimtun1", "10.47.0.1", 3)
    act("ue.isolate", "ue-miot-02", {})
    try:
        assert ue_ping("ue-miot", "uesimtun1", "10.47.0.1", 3) == []
        assert ue_ping("ue-miot", "uesimtun0", "10.47.0.1", 3), "un autre UE de la slice ne doit pas être affecté"
    finally:
        act("ue.release", "ue-miot-02", {})
    assert ue_ping("ue-miot", "uesimtun1", "10.47.0.1", 3)


def test_slice_state_arret_puis_reprise(sc):
    act("slice.state", "miot", {"active": False})
    try:
        state = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", "upf-miot", "smf-miot"],
                               capture_output=True, text=True).stdout.split()
        assert state == ["false", "false"]
    finally:
        act("slice.state", "miot", {"active": True})

    def reattached() -> bool:
        subprocess.run(["docker", "restart", "ue-miot"], capture_output=True)
        return wait(lambda: subprocess.run(["docker", "exec", "ue-miot", "sh", "-c",
                                            "ip -o -4 addr show | grep -c uesimtun"],
                                           capture_output=True, text=True).stdout.strip() == "10", 40)
    assert wait(reattached, 180, 10), "UEs miot non réattachés après reprise de la slice"
    out = subprocess.run(["docker", "exec", "-u", "0", "upf-miot", "tc", "class", "show", "dev", "ogstun"],
                         capture_output=True, text=True).stdout
    assert "rate 5Mbit ceil 10Mbit" in out, "limitation de la slice non réappliquée après reprise"


def test_metriques_k8s_et_liens(sc):
    def q(expr: str) -> list:
        return httpx.get(f"{PROM}/api/v1/query", params={"query": expr}, timeout=5).json()["data"]["result"]
    assert wait(lambda: bool(q('b6g_k8s_replicas{deployment="b6g-echo-app"}')), 60, 5)
    assert wait(lambda: bool(q('b6g_app_request_latency_ms{app="b6g-edge-infer"}')), 60, 5)
    assert len(q('b6g_link_delay_ms')) == len(sc["links"])


def test_catalogue_des_donnees():
    cat = ROOT / "datasets" / "catalog.yaml"
    if not cat.exists():
        pytest.skip("datasets/catalog.yaml : livrable de l'équipe 2 (M18), pas encore fourni")
