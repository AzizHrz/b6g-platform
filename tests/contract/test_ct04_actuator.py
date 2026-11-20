"""CT-04 : chaque ActionRequest valide → 200 en dry_run ; invalides → 400/404/409."""
import pytest
from b6g_common import errors

from ..conftest import H, load_examples

pytestmark = pytest.mark.ct
VALID = load_examples("actions/valid")
INVALID = load_examples("actions/invalid")


def test_health(actuator):
    assert actuator.get("/v1/health").json()["status"] == "ok"


@pytest.mark.parametrize("name", sorted(VALID))
def test_valides_en_dry_run(actuator, name):
    before = actuator.get("/v1/state", headers=H).json()
    r = actuator.post("/v1/actions?dry_run=true", json=VALID[name], headers=H)
    assert r.status_code == 200, r.text
    body = r.json()
    assert errors(body, "action-result") == []
    assert body["status"] == "dry_run"
    assert actuator.get("/v1/state", headers=H).json() == before, "dry_run ne doit rien modifier"


@pytest.mark.parametrize("name", sorted(INVALID))
def test_invalides_refusees(actuator, name):
    expected = int(name.split("_")[0])
    r = actuator.post("/v1/actions?dry_run=true", json=INVALID[name], headers=H)
    assert r.status_code == expected, r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["status"] == expected and r.json()["title"]


def test_entete_appelant_obligatoire(actuator):
    r = actuator.post("/v1/actions?dry_run=true", json=VALID["noop"])
    assert r.status_code == 400


def test_application_memoire_et_evenements(actuator):
    r = actuator.post("/v1/actions", json=VALID["slice_bandwidth_v2x"], headers=H)
    assert r.status_code == 200 and r.json()["status"] == "applied"
    assert actuator.get("/v1/state", headers=H).json()["slices"]["v2x"]["rate_mbps"] == 30
    outbox = actuator.app.state.outbox
    assert [e["type"] for e in outbox] == ["actuator.applied", "slice.resized"]
    assert all(errors(e, "event") == [] for e in outbox)
    assert 'b6g_actions_total{type="slice.bandwidth",status="applied"} 1' in actuator.get("/metrics").text


def test_capacite_tient_compte_de_l_etat(actuator):
    a = {"type": "slice.bandwidth", "target": "embb", "params": {"rate_mbps": 100, "ceil_mbps": 100}, "reason": "pointe"}
    assert actuator.post("/v1/actions", json=a, headers=H).status_code == 200      # 100+20+5 = 125
    b = {"type": "slice.bandwidth", "target": "v2x", "params": {"rate_mbps": 50}, "reason": "trop"}
    assert actuator.post("/v1/actions", json=b, headers=H).status_code == 409      # 100+50+5 = 155


def test_lot_arret_au_premier_echec(actuator):
    acts = [VALID["noop"], INVALID["409_capacity_exceeded"], VALID["slice_bandwidth_v2x"]]
    r = actuator.post("/v1/actions/batch?dry_run=true", json={"actions": acts}, headers=H)
    res = r.json()["results"]
    assert [x["status"] for x in res] == ["dry_run", "rejected"]
