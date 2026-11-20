"""I-01 : chargement et contrôle du scénario partagé config/scenario.yaml."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from .paths import scenario_path
from .schemas import ContractError, validate


def semantic_errors(sc: dict) -> list[str]:
    """Règles qu'un schéma JSON ne sait pas exprimer."""
    errs = []
    ids = [s["id"] for s in sc["slices"]]
    if sorted(ids) != ["embb", "miot", "v2x"]:
        errs.append(f"slices: il faut exactement embb, v2x, miot (trouvé {ids})")
    pairs = [(s["sst"], s["sd"]) for s in sc["slices"]]
    if len(set(pairs)) != len(pairs):
        errs.append("slices: couples (sst, sd) en double")
    if len({s["subnet"] for s in sc["slices"]}) != len(sc["slices"]):
        errs.append("slices: sous-réseaux en double")
    for s in sc["slices"]:
        if s["bandwidth"]["ceil_mbps"] < s["bandwidth"]["rate_mbps"]:
            errs.append(f"slices/{s['id']}: ceil_mbps < rate_mbps")
    total = sum(s["bandwidth"]["rate_mbps"] for s in sc["slices"])
    if total > sc["capacity"]["total_rate_mbps_max"]:
        errs.append(f"capacity: somme des rate_mbps {total} > {sc['capacity']['total_rate_mbps_max']}")
    for name, p in sc["profiles"].items():
        if p["slice"] not in ids:
            errs.append(f"profiles/{name}: slice inconnue {p['slice']}")
    for s in sc["slices"]:
        if f"n6-{s['id']}" not in sc["links"]:
            errs.append(f"links: n6-{s['id']} manquant")
    for t in sc["tiers"]:
        if f"tier-{t}" not in sc["links"]:
            errs.append(f"links: tier-{t} manquant")
    return errs


def load(path: str | Path | None = None) -> dict:
    """Charge, valide (schéma + règles) et renvoie le scénario."""
    p = Path(path) if path else scenario_path()
    sc = yaml.safe_load(p.read_text(encoding="utf-8"))
    validate(sc, "scenario")
    errs = semantic_errors(sc)
    if errs:
        raise ContractError("scenario (règles)", errs)
    return sc


@lru_cache(maxsize=1)
def default() -> dict:
    """Scénario du dépôt, chargé une seule fois."""
    return load()


def slice_ids(sc: dict) -> list[str]:
    return [s["id"] for s in sc["slices"]]


def slice_by_id(sc: dict, sid: str) -> dict:
    for s in sc["slices"]:
        if s["id"] == sid:
            return s
    raise KeyError(sid)


def ue_ids(sc: dict) -> list[str]:
    n = sc["ues"]["count_per_slice"]
    pat = sc["ues"]["id_pattern"]
    return [pat.format(slice=s, nn=i) for s in slice_ids(sc) for i in range(1, n + 1)]


def ue_imsi(sc: dict, ue_id: str) -> str:
    """IMSI d'un UE : embb 001–010, v2x 011–020, miot 021–030."""
    ids = ue_ids(sc)
    base = sc["ues"]["imsi_base"]
    return str(int(base) + ids.index(ue_id)).zfill(len(base))


def tier_ids(sc: dict) -> list[str]:
    return list(sc["tiers"].keys())
