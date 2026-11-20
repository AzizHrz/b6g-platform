"""CT-06 : réponse whatif valide pour les 5 snapshots d'exemple."""
import pytest
from b6g_common import errors
from fastapi.testclient import TestClient

from mocks.intelligence.mock_decision import decide
from mocks.intelligence.mock_twin import create_app

from ..conftest import H

pytestmark = pytest.mark.ct


@pytest.fixture(scope="module")
def twin():
    return TestClient(create_app())


def test_cinq_snapshots(twin, snapshots):
    assert len(snapshots) == 5
    for name, snap in snapshots.items():
        actions = decide(snap, "qos-tree")["actions"]
        r = twin.post("/v1/whatif", json={"snapshot": snap, "actions": actions, "horizon_s": 60}, headers=H)
        assert r.status_code == 200, (name, r.text)
        assert errors(r.json(), "whatif-response") == [], name


def test_plus_de_debit_moins_de_latence(twin, snapshots):
    snap = snapshots["snapshot_incident"]
    act = {"type": "slice.bandwidth", "target": "v2x", "params": {"rate_mbps": 40}, "reason": "test"}
    p = twin.post("/v1/whatif", json={"snapshot": snap, "actions": [act]}, headers=H).json()
    assert p["predicted"]["slices"]["v2x"]["latency_ms_p95"] < snap["slices"]["v2x"]["latency_ms_p95"]


def test_requete_invalide(twin):
    assert twin.post("/v1/whatif", json={"actions": []}, headers=H).status_code == 400
