"""CT-03 : build_snapshot produit un objet valide (3 slices, 3 niveaux, null si absent)."""
import pytest
from b6g_common import errors, snapshot
from fastapi.testclient import TestClient

from mocks.platform.fake_exporter import PROFILES, create_app, generate

pytestmark = pytest.mark.ct


@pytest.mark.parametrize("profile", list(PROFILES))
def test_build_depuis_prometheus(sc, profile):
    app = create_app(profile=profile)
    with TestClient(app, base_url="http://fake") as client:
        snap = snapshot.build("http://fake", sc=sc, client=client)
    assert errors(snap, "metric-snapshot") == []
    assert set(snap["slices"]) == {"embb", "v2x", "miot"}
    assert set(snap["tiers"]) == {"edge", "fog", "cloud"}
    assert all(v["latency_ms_p95"] is not None for v in snap["slices"].values())
    assert snap["tiers"]["edge"]["cpu_ratio"] is not None


def test_null_si_absent_jamais_zero(sc):
    series = generate("day", sc, drop=("b6g_slice_latency_ms", "b6g_energy_power_watts", "b6g_k8s_replicas"))
    snap = snapshot.from_series(series, sc)
    assert all(v["latency_ms_p95"] is None and v["latency_ms_p50"] is None for v in snap["slices"].values())
    assert snap["energy"]["total_power_watts"] is None
    assert all(r is None for t in snap["tiers"].values() for r in t["replicas"].values())


def test_prometheus_vide(sc):
    snap = snapshot.from_series({}, sc)
    assert errors(snap, "metric-snapshot") == []
    assert snap["slices"]["v2x"]["throughput_mbps"] is None
    assert snap["links"]["n2n3-gnb1"]["delay_ms"] is None


def test_exemples_valides(snapshots):
    for name, snap in snapshots.items():
        assert errors(snap, "metric-snapshot") == [], name
