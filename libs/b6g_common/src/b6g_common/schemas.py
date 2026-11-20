"""Chargement des schémas JSON de contracts/ et validation (JSON Schema 2020-12)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .paths import contracts_dir

BASE = "https://b6g.local/contracts/"


class ContractError(ValueError):
    """Objet non conforme à un contrat. `details` liste les erreurs lisibles."""

    def __init__(self, schema: str, details: list[str]):
        self.schema = schema
        self.details = details
        super().__init__(f"{schema}: " + " ; ".join(details[:5]))


@lru_cache(maxsize=1)
def _registry() -> Registry:
    resources = []
    for f in sorted(Path(contracts_dir()).glob("*.schema.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        resources.append((doc["$id"], Resource.from_contents(doc)))
    return Registry().with_resources(resources)


def _name(schema: str) -> str:
    return schema if schema.endswith(".schema.json") else f"{schema}.schema.json"


@lru_cache(maxsize=None)
def validator(schema: str) -> Draft202012Validator:
    reg = _registry()
    contents = reg.contents(BASE + _name(schema))
    return Draft202012Validator(contents, registry=reg)


def errors(obj, schema: str) -> list[str]:
    """Liste des erreurs (vide si conforme)."""
    out = []
    for e in sorted(validator(schema).iter_errors(obj), key=lambda e: list(e.absolute_path)):
        path = "/".join(str(p) for p in e.absolute_path) or "(racine)"
        out.append(f"{path}: {e.message}")
    return out


def validate(obj, schema: str):
    """Lève ContractError si `obj` ne respecte pas `schema` (ex. "metric-snapshot"). Renvoie obj."""
    errs = errors(obj, schema)
    if errs:
        raise ContractError(_name(schema), errs)
    return obj


def list_schemas() -> list[str]:
    return [f.name for f in sorted(Path(contracts_dir()).glob("*.schema.json"))]
