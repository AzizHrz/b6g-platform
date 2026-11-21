"""Jalon INT1 : plateforme v0 (3 slices, 30 UEs), métriques b6g_* réelles, Actionneur v1.

Critère de passage (plan maître § 9.3) : CT-02 contre le vrai Prometheus et une action slice.bandwidth appliquée.
Demande la plateforme démarrée (make up-core up-obs up-actuator up-probes) :

    B6G_PROM_URL=http://b6g-plat:9090 B6G_ACTUATOR_URL=http://b6g-plat:8081 .venv/bin/pytest -m int tests/integration/test_int1.py

Sans variable : 127.0.0.1 (lancement depuis M1). Réalisme des valeurs mesurées : ÉMULÉ.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time

import httpx
import pytest
from b6g_common import scenario as scn
from b6g_common import snapshot

from mocks.platform.fake_exporter import METRICS

pytestmark = pytest.mark.int

PROM = os.environ.get("B6G_PROM_URL", "http://127.0.0.1:9090")
ACT = os.environ.get("B6G_ACTUATOR_URL", "http://127.0.0.1:8081")
H = {"X-B6G-Caller": "test_int1"}

# Métriques I-02 dont le producteur n'existe pas encore à INT1 : jalon où elles apparaissent
LATER = {
    "b6g_k8s_replicas": "INT3 (kube-state-metrics, k3d)",
    "b6g_app_request_latency_ms": "INT3 (echo-app / edge-infer)",
    "b6g_energy_power_watts": "S6 (exporteur énergie M09)",
    "b6g_energy_joules_total": "S6 (exporteur énergie M09)",
    "b6g_loop_iterations_total": "INT5 (boucle M10)",
    "b6g_security_alerts_total": "INT4+ (politique anomaly-reaction)",
}
INT1_METRICS = [m for m in METRICS if m not in LATER]


def query(expr: str) -> list[dict]:
    r = httpx.get(f"{PROM}/api/v1/query", params={"query": expr}, timeout=5)
    r.raise_for_status()
    return r.json()["data"]["result"]


def wait_for(expr: str, check, timeout_s: float = 30) -> list[dict]:
    deadline = time.monotonic() + timeout_s
    res: list[dict] = []
    while time.monotonic() < deadline:
        res = query(expr)
        if res and check(res):
            return res
        time.sleep(2)
    return res


def action(params: dict, target: str = "v2x", reason: str = "test_int1") -> dict:
    body = {"type": "slice.bandwidth", "target": target, "params": params, "reason": reason}
    r = httpx.post(f"{ACT}/v1/actions", json=body, headers=H, timeout=10)
    return r.json()


@pytest.fixture(scope="module")
def sc():
    return scn.load()


@pytest.fixture(scope="module", autouse=True)
def platform_up():
    try:
        httpx.get(f"{PROM}/-/ready", timeout=3).raise_for_status()
        httpx.get(f"{ACT}/v1/health", timeout=3).raise_for_status()
    except httpx.HTTPError as e:
        pytest.skip(f"plateforme non joignable ({e}) : make up-core up-obs up-actuator up-probes")


def test_actionneur_backend_reel():
    h = httpx.get(f"{ACT}/v1/health", timeout=3).json()
    assert h["backend"] == "tc", h
    assert "setup_error" not in h, h["setup_error"]


def test_cibles_prometheus_actives():
    targets = httpx.get(f"{PROM}/api/v1/targets", params={"state": "active"}, timeout=5).json()["data"]
    down = [(t["labels"].get("job"), t["labels"].get("nf"), t.get("lastError")) for t in targets["activeTargets"]
            if t["health"] != "up"]
    assert not down, down


@pytest.mark.parametrize("metric", INT1_METRICS)
def test_ct02_reel_metrique_et_etiquettes(metric):
    if metric == "b6g_actions_total":
        action({"rate_mbps": 20, "ceil_mbps": 40}, reason="test_int1 : compteur d'actions")
    _typ, labels = METRICS[metric]
    res = wait_for(metric, lambda r: True)
    assert res, f"{metric} absente de Prometheus"
    for item in res:
        for lab in labels:
            assert lab in item["metric"], f"{metric} sans étiquette {lab} : {item['metric']}"


@pytest.mark.parametrize("metric", sorted(LATER))
def test_ct02_metriques_des_jalons_suivants(metric):
    pytest.skip(f"{metric} : producteur prévu à {LATER[metric]}")


def test_30_ues_et_10_sessions_par_slice(sc):
    n = sc["ues"]["count_per_slice"]
    reg = query("b6g_ue_registered")
    assert reg and float(reg[0]["value"][1]) == len(sc["slices"]) * n
    sessions = {r["metric"]["slice"]: float(r["value"][1]) for r in query("b6g_slice_sessions")}
    assert sessions == {s: n for s in scn.slice_ids(sc)}


def test_snapshot_reel_valide(sc):
    snap = snapshot.build(PROM, sc=sc)  # validé contre metric-snapshot.schema.json
    for sid, v in snap["slices"].items():
        assert v["sessions"] == sc["ues"]["count_per_slice"], sid
        assert v["latency_ms_p95"] is not None, f"{sid} : latence absente (sondes trafficgen lancées ?)"
        assert v["bw_limit_mbps"] is not None, sid
    assert any(k.startswith("upf-") for k in snap["nfs"]), snap["nfs"]


def test_action_slice_bandwidth_appliquee(sc):
    init = next(s["bandwidth"] for s in sc["slices"] if s["id"] == "v2x")
    try:
        res = action({"rate_mbps": 15, "ceil_mbps": 30}, reason="test_int1 : action réelle")
        assert res["status"] == "applied", res
        assert res["current"]["rate_mbps"] == 15 and res["current"]["ceil_mbps"] == 30
        got = wait_for('b6g_slice_bw_limit_mbps{slice="v2x"}', lambda r: float(r[0]["value"][1]) == 15)
        assert got and float(got[0]["value"][1]) == 15, got
    finally:
        back = action({"rate_mbps": init["rate_mbps"], "ceil_mbps": init["ceil_mbps"]}, reason="test_int1 : retour")
        assert back["status"] == "applied", back


@pytest.mark.skipif(shutil.which("docker") is None, reason="mesure iperf3 seulement sur M1 (accès Docker)")
def test_debit_mesure_suit_le_plafond(sc):
    """T06.2 : débit descendant mesuré à ±10 % du plafond (ceil) après l'action."""
    init = next(s["bandwidth"] for s in sc["slices"] if s["id"] == "v2x")
    ue_ip = subprocess.run(["docker", "exec", "ue-v2x", "sh", "-c",
                            "ip -o -4 addr show uesimtun0 | awk '{print $4}' | cut -d/ -f1"],
                           capture_output=True, text=True, check=True).stdout.strip()
    try:
        assert action({"rate_mbps": 5, "ceil_mbps": 10}, reason="test_int1 : mesure")["status"] == "applied"
        out = subprocess.run(["docker", "exec", "ue-v2x", "iperf3", "-c", "iperf", "-B", ue_ip, "-R", "-t", "5", "-J"],
                             capture_output=True, text=True, timeout=30)
        if out.returncode != 0:
            out = subprocess.run(["docker", "exec", "ue-v2x", "iperf3", "-c", "172.22.0.70", "-B", ue_ip, "-R", "-t",
                                  "5", "-J"], capture_output=True, text=True, timeout=30, check=True)
        import json

        mbps = json.loads(out.stdout)["end"]["sum_received"]["bits_per_second"] / 1e6
        assert 9.0 <= mbps <= 11.0, f"débit mesuré {mbps:.2f} Mbit/s pour un plafond de 10"
    finally:
        action({"rate_mbps": init["rate_mbps"], "ceil_mbps": init["ceil_mbps"]}, reason="test_int1 : retour")
