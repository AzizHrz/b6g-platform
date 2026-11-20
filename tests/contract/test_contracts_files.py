"""Contrats eux-mêmes : schémas JSON et OpenAPI valides, versions cohérentes."""
from pathlib import Path

import pytest
from b6g_common import CONTRACTS_VERSION
from b6g_common.schemas import list_schemas, validator
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate
from openapi_spec_validator.readers import read_from_filename

pytestmark = pytest.mark.ct
ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("name", list_schemas())
def test_schemas_json(name):
    Draft202012Validator.check_schema(validator(name).schema)


@pytest.mark.parametrize("spec", sorted((ROOT / "contracts" / "openapi").glob("*.yaml")), ids=lambda p: p.stem)
def test_openapi(spec):
    d, base = read_from_filename(str(spec))
    validate(d, base_uri=base)
    assert d["info"]["version"] == CONTRACTS_VERSION


def test_changelog_version():
    assert f"## {CONTRACTS_VERSION}" in (ROOT / "contracts" / "CHANGELOG.md").read_text(encoding="utf-8")
