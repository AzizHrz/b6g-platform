"""Atelier 9 — même UPF (slice miot) en machine virtuelle et en conteneur : démarrage, RAM, CPU, débit (T09.3).

    .venv/bin/python ateliers/a09/run_a09.py [--reps 3] [--duration 15]

Prérequis : make up-core up-obs up-actuator ; VM upf-miot-vm créée (make up-vm). Le script bascule l'UPF miot :
  1. VM : arrêt, puis démarrage chronométré jusqu'à la réponse de l'UPF (point de métriques http://<N4>:9090) ;
  2. conteneur : même mesure avec `docker start upf-miot`.
Dans les deux cas : 10 UEs miot réattachés, 3 répétitions de 15 s de trafic TCP descendant sans limitation tc,
CPU (VM : virsh domstats ; conteneur : cgroup cpu.stat) et mémoire (VM : RSS du processus QEMU ; conteneur : cgroup
memory.current). Le script termine sur le conteneur, état nominal de la plateforme, et rétablit la limitation miot
du scénario par l'Actionneur. Produit results/vm_vs_container.csv. Réalisme : ÉMULÉ.
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from b6g_common import now_iso
from b6g_common import scenario as scn

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "platform" / "trafficgen"))
import load  # noqa: E402

DOM, CONT = "upf-miot-vm", "upf-miot"
VIRSH = ["virsh", "-c", "qemu:///system"]
ACT = "http://127.0.0.1:8081"


def run(*cmd: str, check: bool = True) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=check).stdout


def upf_ready(ip: str) -> bool:
    try:
        with urllib.request.urlopen(f"http://{ip}:9090/metrics", timeout=1) as r:
            return r.status == 200
    except OSError:
        return False


def wait_ready(ip: str, timeout: float = 240) -> float:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if upf_ready(ip):
            return time.time() - t0
        time.sleep(0.2)
    raise RuntimeError("UPF non prête")


def vm_state() -> str:
    return run(*VIRSH, "domstate", DOM, check=False).strip()


def vm_stop() -> None:
    if vm_state() == "running":
        run(*VIRSH, "shutdown", DOM)
        for _ in range(120):
            if vm_state() == "shut off":
                return
            time.sleep(1)
        run(*VIRSH, "destroy", DOM, check=False)


def reattach(sc: dict, attempts: int = 4) -> None:
    """Redémarre les UEs miot jusqu'à obtenir tous les tunnels (la SMF met quelques secondes à se réassocier à l'UPF)."""
    n = sc["ues"]["count_per_slice"]
    for _ in range(attempts):
        run("docker", "restart", "ue-miot")
        for _ in range(40):
            out = run("docker", "exec", "ue-miot", "sh", "-c", "ip -o -4 addr show | grep -c uesimtun", check=False).strip()
            if out.isdigit() and int(out) >= n:
                return
            time.sleep(1)
        time.sleep(10)
    raise RuntimeError("UEs miot non réattachés après plusieurs essais")


def vm_usage() -> tuple[float, int]:
    out = run(*VIRSH, "domstats", DOM, "--cpu-total", "--balloon")
    d = dict(line.strip().split("=", 1) for line in out.splitlines() if "=" in line)
    return float(d["cpu.time"]) / 1e9, int(d["balloon.rss"]) * 1024


def cont_usage() -> tuple[float, int]:
    cpu = run("docker", "exec", CONT, "cat", "/sys/fs/cgroup/cpu.stat")
    usec = int(next(line.split()[1] for line in cpu.splitlines() if line.startswith("usage_usec")))
    mem = int(run("docker", "exec", CONT, "cat", "/sys/fs/cgroup/memory.current").strip())
    return usec / 1e6, mem


def measure(sc: dict, kind: str, usage, reps: int, duration: int, boot_s: float) -> list[dict]:
    prof = {"slice": "miot", "proto": "tcp", "direction": "dl", "rate_mbps": 0}
    rows = []
    for rep in range(1, reps + 1):
        ues = load.list_ues(sc)
        (c0, _), t0 = usage(), time.time()
        res = load.run(sc, "a09", f"{kind}-rep{rep}", duration, {"miot": ("saturation", prof, 1.0)}, ues=ues)
        (c1, mem), t1 = usage(), time.time()
        thr = sum(r["value"] for r in res if r["metric"] == "throughput_mbps" and r["value"] is not None)
        rows.append({"ts": now_iso(), "config": f"{kind}-rep{rep}", "deploiement": kind, "demarrage_s": round(boot_s, 2),
                     "cpu_coeurs": round((c1 - c0) / (t1 - t0), 3), "memory_bytes": mem,
                     "throughput_mbps": round(thr, 2)})
        print(rows[-1], flush=True)
        time.sleep(5)
    return rows


def act(sc: dict, rate: float, ceil: float, reason: str) -> None:
    body = json.dumps({"type": "slice.bandwidth", "target": "miot", "params": {"rate_mbps": rate, "ceil_mbps": ceil},
                       "reason": reason}).encode()
    req = urllib.request.Request(f"{ACT}/v1/actions", data=body, method="POST",
                                 headers={"Content-Type": "application/json", "X-B6G-Caller": "atelier-a09"})
    print(json.load(urllib.request.urlopen(req, timeout=10))["status"], flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--duration", type=int, default=15)
    args = ap.parse_args()
    sc = scn.load()
    ip = json.loads((ROOT / "platform" / "core" / "generated" / "addresses.json").read_text())[CONT]
    rows = []
    # 1. VM
    run("docker", "stop", CONT, check=False)
    vm_stop()
    run(*VIRSH, "start", DOM)
    boot = wait_ready(ip, timeout=300)
    print(f"VM prête en {boot:.1f} s", flush=True)
    time.sleep(10)
    reattach(sc)
    rows += measure(sc, "vm", vm_usage, args.reps, args.duration, boot)
    # 2. Conteneur (sans limitation tc : réseau du conteneur recréé au démarrage)
    vm_stop()
    run("docker", "start", CONT)
    boot = wait_ready(ip)
    print(f"conteneur prêt en {boot:.1f} s", flush=True)
    time.sleep(10)
    reattach(sc)
    rows += measure(sc, "conteneur", cont_usage, args.reps, args.duration, boot)
    # 3. Retour à l'état nominal : limitation du scénario réappliquée par l'Actionneur
    bw = next(s["bandwidth"] for s in sc["slices"] if s["id"] == "miot")
    act(sc, bw["rate_mbps"], bw["ceil_mbps"], "atelier 9 : limitation du scénario sur l'UPF conteneurisée")
    out = HERE / "results" / "vm_vs_container.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    for kind in ("vm", "conteneur"):
        k = [r for r in rows if r["deploiement"] == kind]
        print(kind, "démarrage", k[0]["demarrage_s"], "s ; débit", round(statistics.mean(r["throughput_mbps"] for r in k), 1),
              "Mbit/s ; CPU", round(statistics.mean(r["cpu_coeurs"] for r in k), 3), "cœur ; RAM",
              round(statistics.mean(r["memory_bytes"] for r in k) / 1e6), "Mo")


if __name__ == "__main__":
    main()
