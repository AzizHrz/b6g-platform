"""Jalon INT4 : registre Fabric réel (CT-07 réel), rejeu NTN par l'Actionneur, captures de sécurité D7.

Critère (plan maître § 9.3) : CT-07 réel et test_int4. Demande :
    make up-core up-obs up-actuator up-ledger ; Actionneur démarré avec B6G_LEDGER_URL=http://127.0.0.1:8082
    .venv/bin/pytest -m int tests/integration/test_int4.py
Le rejeu NTN utilise l'échantillon SYNTHÉTIQUE datasets/samples/ntn_profile.csv tant que l'équipe 2 n'a pas livré
son outil de rejeu (intelligence/ntn/replay.py) : le test vérifie le chemin plateforme (Actionneur -> lien gNB).
"""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import time
from pathlib import Path

import httpx
import pytest
from b6g_common import errors, events

pytestmark = pytest.mark.int

ROOT = Path(__file__).resolve().parents[2]
LEDGER = os.environ.get("B6G_LEDGER_URL", "http://127.0.0.1:8082")
ACT = os.environ.get("B6G_ACTUATOR_URL", "http://127.0.0.1:8081")
H = {"X-B6G-Caller": "test_int4", "Content-Type": "application/json"}
RTT = re.compile(r"time=([\d.]+) ms")


def post(evt: dict) -> httpx.Response:
    return httpx.post(f"{LEDGER}/v1/events", content=json.dumps(evt, ensure_ascii=False).encode(), headers=H, timeout=60)


@pytest.fixture(scope="module", autouse=True)
def ledger_up():
    try:
        h = httpx.get(f"{LEDGER}/v1/health", timeout=3).json()
    except httpx.HTTPError as e:
        pytest.skip(f"registre indisponible ({e}) : make up-ledger")
    if h.get("backend") != "hyperledger-fabric":
        pytest.skip(f"registre non Fabric : {h}")


def test_ct07_reel_poster_relire_verifier():
    e = events.make("tests", "slice.resized", {"slice": "v2x", "rate_mbps": 30.0, "note": "é"})
    t0 = time.time()
    r = post(e)
    assert r.status_code == 200, r.text
    assert time.time() - t0 < 5, "inscription en plus de 5 s"
    assert errors(r.json(), "ledger-receipt") == []
    got = httpx.get(f"{LEDGER}/v1/events/{e['event_id']}", timeout=10).json()
    assert got["payload"] == e["payload"] and got["tx_id"] == r.json()["tx_id"]
    v = httpx.get(f"{LEDGER}/v1/verify/{e['event_id']}", timeout=10).json()
    assert errors(v, "ledger-verify") == [] and v["hash_match"] is True
    assert v["endorsements"] == ["Org1MSP", "Org2MSP"], "endossement Org1 ET Org2 attendu"


def test_ct07_reel_doublon_empreinte_fausse_inconnu():
    e = events.make("tests", "alert.qos", {"slice": "v2x"})
    assert post(e).status_code == 200
    assert post(e).status_code == 409
    bad = events.make("tests", "alert.qos", {"slice": "v2x"})
    bad["payload"]["slice"] = "embb"
    assert post(bad).status_code == 400
    assert httpx.get(f"{LEDGER}/v1/verify/00000000-0000-4000-8000-0000000000ff", timeout=10).status_code == 404
    items = httpx.get(f"{LEDGER}/v1/events", params={"type": "alert.qos", "limit": 5}, timeout=10).json()
    assert "items" in items and len(items["items"]) <= 5


def test_actionneur_inscrit_ses_actions_dans_fabric():
    before = httpx.get(f"{LEDGER}/v1/events", params={"type": "actuator.applied"}, timeout=10).json()["total"]
    r = httpx.post(f"{ACT}/v1/actions", json={"type": "noop", "target": "-", "params": {}, "reason": "test_int4"},
                   headers=H, timeout=10)
    assert r.json()["status"] == "applied"
    deadline = time.time() + 30
    after = before
    while time.time() < deadline and after <= before:
        time.sleep(2)
        after = httpx.get(f"{LEDGER}/v1/events", params={"type": "actuator.applied"}, timeout=10).json()["total"]
    assert after == before + 1, "événement actuator.applied non inscrit dans Fabric"


def ue_rtt() -> float:
    out = subprocess.run(["docker", "exec", "ue-embb", "ping", "-I", "uesimtun0", "-n", "-c", "3", "-i", "0.2", "-W", "2",
                          "10.45.0.1"], capture_output=True, text=True).stdout
    return min(float(x) for x in RTT.findall(out))


def test_rejeu_ntn_par_l_actionneur():
    """Trois points du profil NTN (échantillon SYNTHÉTIQUE) rejoués sur le lien gNB <-> cœur : le RTT d'un UE suit."""
    rows = list(csv.DictReader((ROOT / "datasets" / "samples" / "ntn_profile.csv").open()))
    points = [r for r in rows if r["link"] != "terrestrial"][:1] + rows[:1]
    try:
        for r in points:
            d = float(r["delay_ms_oneway"])
            body = {"type": "link.netem", "target": "n2n3-gnb1", "params": {"delay_ms": d},
                    "reason": f"test_int4 : rejeu NTN t={r['t_s']}"}
            res = httpx.post(f"{ACT}/v1/actions", json=body, headers=H, timeout=30).json()
            assert res["status"] == "applied", res
            rtt = ue_rtt()
            assert d <= rtt < d + 15, f"délai rejoué {d} ms, RTT mesuré {rtt} ms"   # netem en sortie du gNB : un sens
    finally:
        httpx.post(f"{ACT}/v1/actions", json={"type": "link.netem", "target": "n2n3-gnb1", "params": {},
                                              "reason": "test_int4 : fin du rejeu"}, headers=H, timeout=30)


def test_captures_securite_d7():
    man = ROOT / "datasets" / "raw" / "security" / "labels.manifest.yaml"
    if not man.exists():
        pytest.skip("D7 non encore produit (T27.2, laboratoire isolé b6g-lab)")
    res = subprocess.run([str(ROOT / ".venv" / "bin" / "python"), str(ROOT / "tools" / "validate_dataset.py"), str(man)],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
