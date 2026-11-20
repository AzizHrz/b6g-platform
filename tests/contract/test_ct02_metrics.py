"""CT-02 (contre fake_exporter) : les 16 métriques b6g_* existent avec les bonnes étiquettes.
À INT1, le même contrôle tourne contre le vrai Prometheus (tests/integration/test_int1.py)."""
import pytest
from fastapi.testclient import TestClient

from mocks.platform.fake_exporter import METRICS, create_app

pytestmark = pytest.mark.ct


def test_16_metriques_exposees():
    assert len(METRICS) == 16
    text = TestClient(create_app()).get("/metrics").text
    for name, (_typ, labels) in METRICS.items():
        assert f"# TYPE {name} " in text, name
        lines = [x for x in text.splitlines() if x.startswith(name + "{") or x.startswith(name + " ")]
        assert lines, f"{name} sans échantillon"
        for lab in labels:
            assert all(f'{lab}="' in x for x in lines), f"{name} sans étiquette {lab}"
