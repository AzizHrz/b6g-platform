"""Outils communs aux expériences des ateliers : écriture measure.v1 (D2) et lecture de Prometheus (noms b6g_*)."""
from __future__ import annotations

import csv
import time
from pathlib import Path

import httpx

MEASURE_COLUMNS = ["ts", "run_id", "scenario", "slice", "ue_id", "profile", "tool", "metric", "value", "unit"]


def write_measures(rows: list[dict], path: Path) -> Path:
    """Écrit les lignes au format measure.v1 ; les mesures en échec (value None) sont exclues et comptées."""
    path.parent.mkdir(parents=True, exist_ok=True)
    kept = [r for r in rows if r.get("value") is not None]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MEASURE_COLUMNS, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(kept)
    return path


def write_csv(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return path


def prom_range(prom: str, expr: str, start: float, end: float, step: float = 5) -> list[dict]:
    """Séries [{labels, points: [(t, v)]}] d'une requête PromQL sur [start, end] (secondes epoch)."""
    r = httpx.get(f"{prom.rstrip('/')}/api/v1/query_range",
                  params={"query": expr, "start": start, "end": end, "step": step}, timeout=10)
    r.raise_for_status()
    return [{"labels": s["metric"], "points": [(float(t), float(v)) for t, v in s["values"]]}
            for s in r.json()["data"]["result"]]


def prom_instant(prom: str, expr: str, at: float | None = None) -> list[dict]:
    params = {"query": expr}
    if at:
        params["time"] = at
    r = httpx.get(f"{prom.rstrip('/')}/api/v1/query", params=params, timeout=10)
    r.raise_for_status()
    return [{"labels": s["metric"], "value": float(s["value"][1])} for s in r.json()["data"]["result"]]


def wait(seconds: float) -> None:
    time.sleep(seconds)
