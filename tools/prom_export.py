"""W1.4 : export Prometheus -> jeu D1 `kpi_timeseries` (I-09) avec son manifeste.

    .venv/bin/python tools/prom_export.py --run-id campagne-01 --since 30m [--step 5] [--format csv|parquet]
    .venv/bin/python tools/prom_export.py --run-id essai --start 2026-11-21T15:00:00Z --end 2026-11-21T15:30:00Z

Une ligne par (instant, slice), colonnes du contrat `contracts/datasets.yaml` (D1). Seuls les noms `b6g_*` (I-02)
sont interrogés ; une valeur absente reste vide (null), jamais 0. Sortie par défaut : `datasets/raw/` (hors Git),
fichier `kpi_timeseries-<run_id>.<csv|parquet>` et `.manifest.yaml`. Contrôle : `tools/validate_dataset.py`.
Réalisme du jeu : ÉMULÉ (plateforme Open5GS / UERANSIM), à préciser par --realism si la source diffère.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import yaml
from b6g_common import scenario as scn
from b6g_common.paths import contracts_dir

ROOT = Path(__file__).resolve().parents[1]
NAME = "kpi_timeseries"


def queries(sc: dict) -> dict[str, str]:
    """Colonne D1 -> requête PromQL (un résultat par slice, étiquette `slice`)."""
    upf = " or ".join(f'label_replace(%s{{nf="{s["upf"]}"}}, "slice", "{s["id"]}", "", "")' for s in sc["slices"])
    return {
        "throughput_mbps": "sum by (slice) (b6g_slice_throughput_mbps)",
        "latency_ms_p50": 'max by (slice) (b6g_slice_latency_ms{quantile="0.5"})',
        "latency_ms_p95": 'max by (slice) (b6g_slice_latency_ms{quantile="0.95"})',
        "loss_ratio": "max by (slice) (b6g_slice_loss_ratio)",
        "bw_limit_mbps": "max by (slice) (b6g_slice_bw_limit_mbps)",
        "sessions": "max by (slice) (b6g_slice_sessions)",
        "upf_cpu_ratio": upf.replace("%s", "b6g_nf_cpu_ratio"),
        "upf_memory_bytes": upf.replace("%s", "b6g_nf_memory_bytes"),
    }


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_time(value: str) -> float:
    m = re.fullmatch(r"(\d+)([smhd])", value)
    if m:
        unit = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[m.group(2)]
        return (datetime.now(timezone.utc) - timedelta(**{unit: int(m.group(1))})).timestamp()
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def collect(prom: str, sc: dict, start: float, end: float, step: int, run_id: str,
            client: httpx.Client | None = None) -> list[dict]:
    """Lignes D1 triées par (ts, ordre des slices du scénario)."""
    http = client or httpx.Client(timeout=30)
    grid = [start + k * step for k in range(int((end - start) // step) + 1)]
    table = {(round(t, 3), s): {} for t in grid for s in scn.slice_ids(sc)}
    for col, expr in queries(sc).items():
        r = http.get(f"{prom.rstrip('/')}/api/v1/query_range",
                     params={"query": expr, "start": start, "end": end, "step": step})
        r.raise_for_status()
        for series in r.json()["data"]["result"]:
            sid = series["metric"].get("slice")
            for t, v in series["values"]:
                key = (round(float(t), 3), sid)
                if key in table:
                    table[key][col] = float(v)
    int_cols = {"sessions", "upf_memory_bytes"}
    rows = []
    for t in grid:
        for sid in scn.slice_ids(sc):
            vals = table[(round(t, 3), sid)]
            if not vals:
                continue  # aucune métrique à cet instant pour cette slice
            row = {"ts": iso(t), "run_id": run_id, "slice": sid}
            for col in queries(sc):
                v = vals.get(col)
                row[col] = None if v is None else (int(round(v)) if col in int_cols else round(v, 6))
            rows.append(row)
    return rows


def manifest(rows: list[dict], data_file: Path, prom: str, run_id: str, start: float, end: float, step: int,
             realism: str) -> dict:
    spec = yaml.safe_load((contracts_dir() / "datasets.yaml").read_text(encoding="utf-8"))["D1"]
    units = {"throughput_mbps": "Mbit/s", "latency_ms_p50": "ms", "latency_ms_p95": "ms", "loss_ratio": "ratio",
             "bw_limit_mbps": "Mbit/s", "upf_memory_bytes": "octets", "upf_cpu_ratio": "fraction d'un cœur", "ts": "UTC"}
    schema = []
    for col, typ in spec["columns"].items():
        entry = {"column": col, "type": typ}
        if col in spec.get("categories", {}):
            entry["values"] = spec["categories"][col]
        if col in units:
            entry["unit"] = units[col]
        schema.append(entry)
    return {
        "id": "D1", "name": NAME, "version": "1.0.0", "producer": "I1.2 / tools/prom_export.py",
        "created_at": iso(datetime.now(timezone.utc).timestamp()),
        "source": f"prometheus {prom}, run_id={run_id}", "realism": realism, "file": data_file.name,
        "sha256": hashlib.sha256(data_file.read_bytes()).hexdigest(), "rows": len(rows),
        "time_range": {"start": iso(start), "end": iso(end), "step_s": step}, "schema": schema,
    }


def write(rows: list[dict], path: Path, fmt: str, columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "csv":
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
            w.writeheader()
            w.writerows([{k: ("" if r[k] is None else r[k]) for k in columns} for r in rows])
        return
    import pyarrow as pa
    import pyarrow.parquet as pq

    types = {"ts": pa.timestamp("ms", tz="UTC"), "run_id": pa.string(), "slice": pa.string(),
             "sessions": pa.int64(), "upf_memory_bytes": pa.int64()}
    arrays = {}
    for c in columns:
        vals = [r[c] for r in rows]
        if c == "ts":
            vals = [datetime.fromisoformat(v.replace("Z", "+00:00")) for v in vals]
        arrays[c] = pa.array(vals, type=types.get(c, pa.float64()))
    pq.write_table(pa.table(arrays), path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prom", default="http://127.0.0.1:9090")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--since", help="durée jusqu'à maintenant : 30m, 2h, 1d…")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--step", type=int, default=5)
    ap.add_argument("--format", choices=["csv", "parquet"], default="csv")
    ap.add_argument("--realism", default="EMULE", choices=["REEL", "EMULE", "SIMULE", "PRE-CALCULE", "MAQUETTE",
                                                           "SYNTHETIQUE"])
    ap.add_argument("--out-dir", type=Path, default=ROOT / "datasets" / "raw")
    args = ap.parse_args()
    if args.since:
        start, end = parse_time(args.since), datetime.now(timezone.utc).timestamp()
    elif args.start and args.end:
        start, end = parse_time(args.start), parse_time(args.end)
    else:
        ap.error("--since ou --start et --end")
    start -= start % args.step
    sc = scn.load()
    rows = collect(args.prom, sc, start, end, args.step, args.run_id)
    if not rows:
        raise SystemExit("aucune donnée sur l'intervalle demandé")
    cols = ["ts", "run_id", "slice", *queries(sc)]
    data = args.out_dir / f"{NAME}-{args.run_id}.{args.format}"
    write(rows, data, args.format, cols)
    man = manifest(rows, data, args.prom, args.run_id, start, end, args.step, args.realism)
    man_path = args.out_dir / f"{NAME}-{args.run_id}.manifest.yaml"
    man_path.write_text(yaml.safe_dump(man, sort_keys=False, allow_unicode=True), encoding="utf-8")
    missing = {c: sum(r[c] is None for r in rows) for c in cols if any(r[c] is None for r in rows)}
    print(f"{len(rows)} lignes -> {data}\nmanifeste -> {man_path}\nvaleurs absentes : {missing or 'aucune'}")


if __name__ == "__main__":
    main()
