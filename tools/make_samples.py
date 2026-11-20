"""Génère les exemples de contrats et les échantillons D1–D8 (100 lignes, SYNTHÉTIQUES, graine fixe).

    python tools/make_samples.py        # réécrit contracts/examples/ et datasets/samples/

Les échantillons servent aux tests CT-08 et au développement avant les vraies campagnes.
Chaque producteur remplacera son jeu par des données réelles ou simulées, avec le même manifeste.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from b6g_common import events, scenario  # noqa: E402
from b6g_common.snapshot import from_series  # noqa: E402

from mocks.platform.fake_exporter import PROFILES, generate  # noqa: E402

SC = scenario.load()
T0 = datetime(2026, 11, 20, 7, 0, tzinfo=timezone.utc)
N = 100


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def dump(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def examples():
    ex = ROOT / "contracts" / "examples"
    for i, prof in enumerate(PROFILES):
        snap = from_series(generate(prof, SC, seed=1), SC, ts=iso(T0 + timedelta(hours=i * 3)))
        dump(ex / "snapshots" / f"snapshot_{prof}.json", snap)
    valid = {
        "slice_bandwidth_v2x": {"type": "slice.bandwidth", "target": "v2x", "params": {"rate_mbps": 30, "ceil_mbps": 50}, "reason": "latence p95 27 ms > 20 ms"},
        "slice_bandwidth_rate_only": {"type": "slice.bandwidth", "target": "miot", "params": {"rate_mbps": 8}, "reason": "capteurs en rafale"},
        "slice_state_miot": {"type": "slice.state", "target": "miot", "params": {"active": False}, "reason": "mise en veille de nuit"},
        "link_netem_leo": {"type": "link.netem", "target": "n2n3-gnb1", "params": {"delay_ms": 30, "jitter_ms": 5, "loss_pct": 0.5}, "reason": "bascule satellite LEO"},
        "link_netem_clear": {"type": "link.netem", "target": "n2n3-gnb1", "params": {}, "reason": "retour terrestre"},
        "deployment_replicas": {"type": "deployment.replicas", "target": "b6g-edge-infer", "params": {"replicas": 3}, "reason": "CPU Edge > 70 %"},
        "deployment_placement": {"type": "deployment.placement", "target": "b6g-echo-app", "params": {"tier": "fog"}, "reason": "Edge saturé"},
        "ue_isolate": {"type": "ue.isolate", "target": "ue-miot-07", "params": {"duration_s": 300}, "reason": "flood UDP détecté"},
        "ue_release": {"type": "ue.release", "target": "ue-miot-07", "params": {}, "reason": "fin de quarantaine"},
        "noop": {"type": "noop", "target": "-", "params": {}, "reason": "SLA respectés"},
    }
    for k, v in valid.items():
        dump(ex / "actions" / "valid" / f"{k}.json", v)
    invalid = {
        "400_unknown_type": {"type": "slice.delete", "target": "v2x", "params": {}, "reason": "test"},
        "400_missing_reason": {"type": "slice.bandwidth", "target": "v2x", "params": {"rate_mbps": 30}},
        "400_bad_field_name": {"type": "slice.bandwidth", "target": "v2x", "params": {"bw_mbps": 30}, "reason": "mauvais nom de champ"},
        "400_rate_out_of_range": {"type": "slice.bandwidth", "target": "v2x", "params": {"rate_mbps": 5000}, "reason": "trop"},
        "400_ceil_below_rate": {"type": "slice.bandwidth", "target": "v2x", "params": {"rate_mbps": 30, "ceil_mbps": 10}, "reason": "ceil < rate"},
        "400_bad_ue_id": {"type": "ue.isolate", "target": "ue-v2x-3", "params": {}, "reason": "identifiant mal formé"},
        "400_replicas_too_many": {"type": "deployment.replicas", "target": "b6g-edge-infer", "params": {"replicas": 50}, "reason": "trop"},
        "404_unknown_ue": {"type": "ue.isolate", "target": "ue-v2x-99", "params": {}, "reason": "UE hors scénario"},
        "404_unknown_deployment": {"type": "deployment.replicas", "target": "b6g-unknown", "params": {"replicas": 2}, "reason": "inconnu"},
        "409_capacity_exceeded": {"type": "slice.bandwidth", "target": "embb", "params": {"rate_mbps": 140, "ceil_mbps": 140}, "reason": "dépasse 150 Mbit/s au total"},
    }
    for k, v in invalid.items():
        dump(ex / "actions" / "invalid" / f"{k}.json", v)
    e = events.make("actuator", "slice.resized", {"slice": "v2x", "rate_mbps": 30}, ts="2026-11-20T08:30:00.000Z")
    e["event_id"] = "00000000-0000-4000-8000-000000000001"
    dump(ex / "events" / "slice_resized.json", e)


def write_dataset(did: str, rows: list[dict], realism="SYNTHETIQUE", time_range=None):
    spec = yaml.safe_load((ROOT / "contracts" / "datasets.yaml").read_text(encoding="utf-8"))[did]
    out = ROOT / "datasets" / "samples"
    out.mkdir(parents=True, exist_ok=True)
    f = out / f"{spec['name']}.csv"
    cols = list(spec["columns"])
    with f.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: (str(r[k]).lower() if isinstance(r[k], bool) else r[k]) for k in cols})
    cats = spec.get("categories", {})
    manifest = {
        "id": did, "name": spec["name"], "version": "1.0.0", "producer": f"{spec['producer']} / tools/make_samples.py",
        "created_at": "2026-11-17T00:00:00Z", "source": "échantillon synthétique (graine 42), à remplacer par le producteur",
        "realism": realism, "file": f.name, "sha256": hashlib.sha256(f.read_bytes()).hexdigest(), "rows": len(rows),
        "schema": [dict({"column": c, "type": t}, **({"values": cats[c]} if c in cats else {})) for c, t in spec["columns"].items()],
    }
    if time_range:
        manifest["time_range"] = time_range
    (out / f"{spec['name']}.manifest.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False), encoding="utf-8")


def datasets():
    rnd = random.Random(42)
    sl = scenario.slice_ids(SC)
    ues = scenario.ue_ids(SC)
    # D1 kpi_timeseries : 34 pas de 5 s × 3 slices ≈ 100 lignes
    rows = []
    for i in range(N):
        s = sl[i % 3]
        snap = from_series(generate(list(PROFILES)[(i // 21) % 5], SC, seed=i), SC)["slices"][s]
        rows.append({"ts": iso(T0 + timedelta(seconds=5 * (i // 3))), "run_id": "sample-01", "slice": s,
                     **{k: snap[k] for k in ("throughput_mbps", "latency_ms_p50", "latency_ms_p95", "loss_ratio", "bw_limit_mbps", "sessions")},
                     "upf_cpu_ratio": round(rnd.uniform(0.1, 0.9), 3), "upf_memory_bytes": rnd.randint(70_000_000, 90_000_000)})
    write_dataset("D1", rows, time_range={"start": rows[0]["ts"], "end": rows[-1]["ts"], "step_s": 5})
    # D2 measure
    metrics = {"throughput_mbps": "Mbit/s", "rtt_ms": "ms", "loss_ratio": "ratio", "attach_time_ms": "ms"}
    rows = []
    for i in range(N):
        ue = ues[i % 30]
        s = ue.split("-")[1]
        m = list(metrics)[i % 4]
        val = {"throughput_mbps": rnd.uniform(1, 9), "rtt_ms": rnd.uniform(5, 40), "loss_ratio": rnd.uniform(0, 0.01), "attach_time_ms": rnd.uniform(80, 300)}[m]
        rows.append({"ts": iso(T0 + timedelta(seconds=i)), "run_id": "sample-01", "scenario": "baseline", "slice": s, "ue_id": ue,
                     "profile": {"embb": "embb-video", "v2x": "v2x-cam", "miot": "miot-sensor"}[s],
                     "tool": "iperf3" if m == "throughput_mbps" else ("ping" if m != "attach_time_ms" else "nr-ue-log"),
                     "metric": m, "value": round(val, 4), "unit": metrics[m]})
    write_dataset("D2", rows)
    # D3 mobility_fcd : 10 véhicules × 10 pas sur une avenue de 1 km
    rows = []
    for i in range(N):
        v, t = i % 10, i // 10
        speed = 8 + v
        x = (v * 60 + speed * t) % 1000
        rows.append({"t_s": float(t), "vehicle_id": f"veh{v}", "x_m": round(x, 2), "y_m": 3.5 * (v % 2), "speed_mps": float(speed),
                     "angle_deg": 90.0, "edge_id": f"e{int(x // 250)}"})
    write_dataset("D3", rows, realism="SIMULE")
    # D4 handover_log
    rows = []
    for i in range(N):
        strat = ["a3", "a3_ttt", "predictive"][i % 3]
        src = i % 4
        rows.append({"t_s": round(i * 2.5, 1), "run_id": "sample-01", "ue_id": ues[10 + i % 10], "strategy": strat,
                     "source_cell": f"cell{src}", "target_cell": f"cell{(src + 1) % 4}",
                     "interruption_ms": round({"a3": 45, "a3_ttt": 40, "predictive": 25}[strat] * rnd.uniform(0.8, 1.2), 2),
                     "rsrp_source_dbm": round(rnd.uniform(-110, -95), 1), "rsrp_target_dbm": round(rnd.uniform(-100, -85), 1),
                     "ping_pong": strat == "a3" and rnd.random() < 0.2})
    write_dataset("D4", rows, realism="SIMULE")
    # D5 v2x_results
    rows = []
    for i in range(N):
        dens = [20, 60, 120][i % 3]
        d = 50 * (1 + (i // 3) % 10)
        prr = max(0.0, min(1.0, 1 / (1 + math.exp((d - 300 + dens) / 60))))
        rows.append({"run_id": "sample-01", "tech": ["nr_v2x_mode2", "nr_v2x_mode1", "v2n"][(i // 30) % 3], "density_veh_per_km": float(dens),
                     "msg_type": ["cam", "denm", "cpm"][i % 3], "distance_bin_m": float(d), "prr": round(prr, 4),
                     "latency_ms_mean": round(3 + dens / 40, 2), "latency_ms_p95": round(6 + dens / 20, 2)})
    write_dataset("D5", rows, realism="SIMULE")
    # D6 ntn_profile : passage LEO de 100 s
    rows = []
    for i in range(N):
        elev = 10 + 80 * math.sin(math.pi * i / (N - 1))
        rng_km = 550 / math.sin(math.radians(elev))
        rows.append({"t_s": float(i), "segment": "pass-1", "link": "leo" if 30 <= i < 80 else "terrestrial", "elevation_deg": round(elev, 2),
                     "delay_ms_oneway": round(rng_km / 299.792, 3) if 30 <= i < 80 else 5.0, "loss_pct": round(0.5 if 30 <= i < 80 else 0.05, 2)})
    write_dataset("D6", rows, realism="SIMULE")
    # D7 security_labels
    rows = []
    for i in range(N):
        lab = "normal" if i % 5 else ["udp_flood", "scan", "reg_storm"][(i // 5) % 3]
        ue = ues[i % 30]
        k = scenario.ue_ids(SC).index(ue)
        st = T0 + timedelta(seconds=30 * i)
        rows.append({"start_ts": iso(st), "end_ts": iso(st + timedelta(seconds=20)), "ue_id": ue,
                     "src_ip": f"10.{45 + k // 10}.0.{k % 10 + 2}", "label": lab})
    write_dataset("D7", rows)
    # D8 actions_log
    rows = []
    types = ["slice.bandwidth", "noop", "link.netem", "deployment.replicas", "ue.isolate"]
    for i in range(N):
        t = types[i % 5]
        rows.append({"ts": iso(T0 + timedelta(seconds=10 * i)), "action_id": f"00000000-0000-4000-8000-{i:012d}",
                     "caller": "loop", "type": t, "target": {"slice.bandwidth": "v2x", "noop": "-", "link.netem": "n2n3-gnb1",
                                                              "deployment.replicas": "b6g-edge-infer", "ue.isolate": "ue-miot-07"}[t],
                     "params_json": json.dumps({"slice.bandwidth": {"rate_mbps": 30}, "noop": {}, "link.netem": {"delay_ms": 30},
                                                "deployment.replicas": {"replicas": 2}, "ue.isolate": {}}[t]),
                     "status": "dry_run", "decision_id": f"10000000-0000-4000-8000-{i:012d}",
                     "sla_ok_before": i % 3 != 0, "sla_ok_after": True})
    write_dataset("D8", rows)


if __name__ == "__main__":
    examples()
    datasets()
    print("exemples et échantillons écrits")
