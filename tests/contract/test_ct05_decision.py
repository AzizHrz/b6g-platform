"""CT-05 : chaque politique répond un Decision valide dont les actions passent CT-04."""
import pytest
from b6g_common import errors
from fastapi.testclient import TestClient

from mocks.intelligence.mock_decision import POLICIES, create_app

from ..conftest import H

pytestmark = pytest.mark.ct


@pytest.fixture(scope="module")
def decision():
    return TestClient(create_app())


def test_policies(decision):
    names = [p["name"] for p in decision.get("/v1/policies", headers=H).json()]
    assert names == list(POLICIES)


@pytest.mark.parametrize("policy", list(POLICIES))
def test_decisions_valides_et_applicables(decision, actuator, snapshots, policy):
    for name, snap in snapshots.items():
        r = decision.post("/v1/decide", json={"policy": policy, "snapshot": snap, "constraints": {"max_actions": 3}}, headers=H)
        assert r.status_code == 200, (name, r.text)
        d = r.json()
        assert errors(d, "decision") == [], name
        for a in d["actions"]:
            rr = actuator.post("/v1/actions?dry_run=true", json=a, headers=H)
            assert rr.status_code == 200, (policy, name, a, rr.text)


def test_pointe_declenche_une_action(decision, snapshots):
    d = decision.post("/v1/decide", json={"policy": "qos-tree", "snapshot": snapshots["snapshot_incident"]}, headers=H).json()
    assert any(a["target"] == "v2x" for a in d["actions"]), d


def test_politique_inconnue(decision, snapshots):
    r = decision.post("/v1/decide", json={"policy": "inconnue", "snapshot": snapshots["snapshot_day"]}, headers=H)
    assert r.status_code == 422
