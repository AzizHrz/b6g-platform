import json
from pathlib import Path

import pytest
from b6g_common import scenario
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
EX = ROOT / "contracts" / "examples"
H = {"X-B6G-Caller": "tests"}


def load_examples(sub: str) -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted((EX / sub).glob("*.json"))}


@pytest.fixture(scope="session")
def sc():
    return scenario.load()


@pytest.fixture(scope="session")
def snapshots():
    snaps = load_examples("snapshots")
    assert len(snaps) >= 5, "5 snapshots d'exemple attendus (make samples)"
    return snaps


@pytest.fixture()
def actuator():
    from b6g_actuator.app import create_app
    return TestClient(create_app(backend="memory", ledger_url=""))


@pytest.fixture()
def ledger(tmp_path):
    from mocks.platform.mock_ledger import create_app
    return TestClient(create_app(str(tmp_path / "ledger.jsonl")))
