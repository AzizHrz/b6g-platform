"""Localisation du dépôt (contracts/, config/)."""
from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    """Racine du dépôt : variable B6G_ROOT, sinon premier parent qui contient contracts/ et config/."""
    env = os.environ.get("B6G_ROOT")
    if env:
        return Path(env).resolve()
    for start in (Path.cwd(), Path(__file__).resolve()):
        for p in (start, *start.parents):
            if (p / "contracts").is_dir() and (p / "config").is_dir():
                return p
    raise FileNotFoundError("Racine du dépôt B6G introuvable : définir B6G_ROOT")


def contracts_dir() -> Path:
    return repo_root() / "contracts"


def scenario_path() -> Path:
    return repo_root() / "config" / "scenario.yaml"
