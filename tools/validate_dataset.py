"""CT-08 : vérifie un jeu de données (manifeste conforme, colonnes et types du contrat contracts/datasets.yaml).

    python tools/validate_dataset.py datasets/samples/*.manifest.yaml
"""
from __future__ import annotations

import csv
import hashlib
import sys
from datetime import datetime
from pathlib import Path

import yaml
from b6g_common import errors
from b6g_common.paths import contracts_dir


def _ok(value: str, typ: str, values=None) -> bool:
    if value == "":
        return True  # valeur absente autorisée (null)
    try:
        if typ == "float":
            float(value)
        elif typ == "int":
            int(value)
        elif typ == "bool":
            return value in ("true", "false")
        elif typ == "timestamp":
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif typ == "category":
            return values is None or value in values
    except ValueError:
        return False
    return True


def validate_manifest(path: str | Path) -> list[str]:
    path = Path(path)
    man = yaml.safe_load(path.read_text(encoding="utf-8"))
    errs = [f"manifeste : {e}" for e in errors(man, "dataset-manifest")]
    if errs:
        return errs
    contract = yaml.safe_load((contracts_dir() / "datasets.yaml").read_text(encoding="utf-8"))
    spec = next((v for v in contract.values() if v["name"] == man["name"]), None)
    if spec is None:
        return [f"jeu {man['name']} absent de contracts/datasets.yaml"]
    declared = {c["column"]: c["type"] for c in man["schema"]}
    for col, typ in spec["columns"].items():
        if declared.get(col) != typ:
            errs.append(f"colonne {col} : attendu {typ}, manifeste {declared.get(col)}")
    data = path.parent / man.get("file", f"{man['name']}.csv")
    if not data.exists():
        return errs + [f"fichier de données absent : {data.name} (hors Git ? vérifier sha256)"]
    if "sha256" in man and hashlib.sha256(data.read_bytes()).hexdigest() != man["sha256"]:
        errs.append("sha256 du fichier différent du manifeste")
    if data.suffix != ".csv":
        return errs  # Parquet : vérification des colonnes faite par pandas dans les tests du producteur
    cats = spec.get("categories", {})
    with data.open(encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        missing = set(spec["columns"]) - set(rd.fieldnames or [])
        if missing:
            return errs + [f"colonnes manquantes : {sorted(missing)}"]
        n = 0
        for n, row in enumerate(rd, 1):
            for col, typ in spec["columns"].items():
                if not _ok(row[col], typ, cats.get(col)):
                    errs.append(f"ligne {n}, {col}={row[col]!r} n'est pas {typ}")
                    if len(errs) > 20:
                        return errs
    if n != man["rows"]:
        errs.append(f"rows={man['rows']} mais {n} lignes")
    return errs


def main(argv: list[str]) -> int:
    bad = 0
    for p in argv:
        errs = validate_manifest(p)
        print(("OK   " if not errs else "ÉCHEC ") + p)
        for e in errs:
            print("     - " + e)
        bad += bool(errs)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
