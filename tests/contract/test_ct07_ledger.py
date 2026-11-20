"""CT-07 : un événement posté est relu et vérifié (hash_match = true) ; une altération est détectée."""
import json

import pytest
from b6g_common import errors, events

from ..conftest import H

pytestmark = pytest.mark.ct


def test_poster_relire_verifier(ledger):
    e = events.make("tests", "slice.resized", {"slice": "v2x", "rate_mbps": 30})
    r = ledger.post("/v1/events", json=e, headers=H)
    assert r.status_code == 200, r.text
    assert errors(r.json(), "ledger-receipt") == []
    got = ledger.get(f"/v1/events/{e['event_id']}").json()
    assert got["payload"] == e["payload"] and got["block_number"] == 0
    v = ledger.get(f"/v1/verify/{e['event_id']}").json()
    assert errors(v, "ledger-verify") == [] and v["hash_match"] is True


def test_refus_doublon_et_empreinte_fausse(ledger):
    e = events.make("tests", "alert.qos", {"slice": "v2x"})
    assert ledger.post("/v1/events", json=e, headers=H).status_code == 200
    assert ledger.post("/v1/events", json=e, headers=H).status_code == 409
    bad = events.make("tests", "alert.qos", {"slice": "v2x"})
    bad["payload"]["slice"] = "embb"
    assert ledger.post("/v1/events", json=bad, headers=H).status_code == 400


def test_alteration_du_journal_detectee(tmp_path):
    from fastapi.testclient import TestClient

    from mocks.platform.mock_ledger import create_app
    path = tmp_path / "l.jsonl"
    c = TestClient(create_app(str(path)))
    ids = []
    for i in range(3):
        e = events.make("tests", "loop.iteration", {"i": i})
        c.post("/v1/events", json=e, headers=H)
        ids.append(e["event_id"])
    lines = path.read_text().splitlines()
    b = json.loads(lines[1])
    b["event"]["payload"]["i"] = 99           # falsification du bloc 1
    lines[1] = json.dumps(b)
    path.write_text("\n".join(lines) + "\n")
    c2 = TestClient(create_app(str(path)))   # relecture du fichier
    assert c2.get(f"/v1/verify/{ids[0]}").json()["hash_match"] is True
    assert c2.get(f"/v1/verify/{ids[2]}").json()["hash_match"] is False


def test_actionneur_vers_registre(ledger):
    """Chaîne Actionneur → Registre (événements actuator.applied)."""
    from b6g_actuator.app import create_app
    from fastapi.testclient import TestClient
    act = TestClient(create_app(backend="memory", ledger_url=""))
    act.post("/v1/actions", json={"type": "noop", "target": "-", "params": {}, "reason": "test"}, headers=H)
    for e in act.app.state.outbox:
        assert ledger.post("/v1/events", json=e, headers={"X-B6G-Caller": "actuator"}).status_code == 200
    assert ledger.get("/v1/events?type=actuator.applied").json()["total"] == 1
