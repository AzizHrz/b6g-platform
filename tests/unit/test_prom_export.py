"""W1.4 : export Prometheus -> D1, contre une API Prometheus factice (aucune plateforme nécessaire)."""
import importlib.util
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("prom_export", ROOT / "tools" / "prom_export.py")
pe = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pe)
_spec2 = importlib.util.spec_from_file_location("validate_dataset", ROOT / "tools" / "validate_dataset.py")
vd = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(vd)

T0 = 1_795_000_000.0


def fake_prometheus(sc):
    cols = pe.queries(sc)

    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params["query"]
        col = next(c for c, e in cols.items() if e == q)
        result = []
        for k, s in enumerate(sc["slices"]):
            if col == "latency_ms_p95" and s["id"] == "miot":
                continue  # série absente : doit donner une valeur vide, pas 0
            value = {"sessions": 10, "upf_memory_bytes": 26e6}.get(col, 1.5 + k)
            result.append({"metric": {"slice": s["id"]}, "values": [[T0, str(value)], [T0 + 5, str(value)]]})
        return httpx.Response(200, json={"status": "success", "data": {"resultType": "matrix", "result": result}})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_lignes_d1_et_null(sc):
    rows = pe.collect("http://prom", sc, T0, T0 + 5, 5, "essai", client=fake_prometheus(sc))
    assert len(rows) == 2 * 3
    assert {r["slice"] for r in rows} == {"embb", "v2x", "miot"}
    miot = next(r for r in rows if r["slice"] == "miot")
    assert miot["latency_ms_p95"] is None and miot["sessions"] == 10
    assert isinstance(miot["upf_memory_bytes"], int)


def test_fichier_et_manifeste_valides_ct08(sc, tmp_path):
    rows = pe.collect("http://prom", sc, T0, T0 + 5, 5, "essai", client=fake_prometheus(sc))
    cols = ["ts", "run_id", "slice", *pe.queries(sc)]
    data = tmp_path / "kpi_timeseries-essai.csv"
    pe.write(rows, data, "csv", cols)
    man = pe.manifest(rows, data, "http://prom", "essai", T0, T0 + 5, 5, "EMULE")
    path = tmp_path / "kpi_timeseries-essai.manifest.yaml"
    path.write_text(yaml.safe_dump(man, sort_keys=False, allow_unicode=True), encoding="utf-8")
    assert vd.validate_manifest(path) == []
