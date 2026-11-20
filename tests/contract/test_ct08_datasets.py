"""CT-08 : chaque jeu D1–D8 publié a un manifeste valide et respecte ses colonnes."""
from pathlib import Path

import pytest
import yaml

from tools.validate_dataset import validate_manifest

pytestmark = pytest.mark.ct
ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = sorted((ROOT / "datasets").rglob("*.manifest.yaml"))


def test_d1_a_d8_presents():
    ids = {yaml.safe_load(p.read_text())["id"] for p in MANIFESTS}
    assert ids >= {f"D{i}" for i in range(1, 9)}


@pytest.mark.parametrize("manifest", MANIFESTS, ids=lambda p: p.stem)
def test_manifeste_et_colonnes(manifest):
    assert validate_manifest(manifest) == []
    assert yaml.safe_load(manifest.read_text())["rows"] >= 100 or "samples" not in str(manifest)
