"""CT-01 : config/scenario.yaml valide contre son schéma et ses règles."""
import copy

import pytest
from b6g_common import ContractError, errors, scenario

pytestmark = pytest.mark.ct


def test_scenario_valide(sc):
    assert scenario.slice_ids(sc) == ["embb", "v2x", "miot"]
    assert [s["sst"] for s in sc["slices"]] == [1, 4, 3]
    assert len(scenario.ue_ids(sc)) == 30


def test_ue_ids_et_imsi(sc):
    assert scenario.ue_ids(sc)[10] == "ue-v2x-01"
    assert scenario.ue_imsi(sc, "ue-embb-01") == "001010000000001"
    assert scenario.ue_imsi(sc, "ue-miot-10") == "001010000000030"


@pytest.mark.parametrize("mutate,expected", [
    (lambda s: s["slices"][1].update(sst=0), "sst"),
    (lambda s: s["slices"][0].update(sd="12"), "sd"),
    (lambda s: s.pop("tiers"), "tiers"),
    (lambda s: s["tiers"].pop("fog"), "fog"),
])
def test_schema_refuse(sc, mutate, expected):
    bad = copy.deepcopy(sc)
    mutate(bad)
    assert any(expected in e for e in errors(bad, "scenario"))


def test_regles_refusent_capacite(sc, tmp_path):
    import yaml
    bad = copy.deepcopy(sc)
    bad["slices"][0]["bandwidth"] = {"rate_mbps": 140, "ceil_mbps": 140}
    p = tmp_path / "s.yaml"
    p.write_text(yaml.safe_dump(bad))
    with pytest.raises(ContractError, match="capacity"):
        scenario.load(p)
