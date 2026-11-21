"""Atelier 7 — UPF virtualisée : ressources selon le nombre de vCPU (T07.3).

    .venv/bin/python ateliers/a07/run_a07.py [--reps 3] [--duration 15]

Prérequis : VM upf-miot-vm active (make up-vm), conteneur upf-miot arrêté, UEs miot attachés à travers la VM.
Pour 1, 2 et 4 vCPU (changement à froid : setvcpus --config, redémarrage) : 3 répétitions de 15 s de TCP descendant sans
limite sur les 10 UEs miot ; CPU de la VM (virsh domstats, temps CPU total), mémoire résidente du processus QEMU.
Produit results/vm_resources.csv (colonnes M05 : ts, config, vcpu, cpu_ratio, memory_bytes, throughput_mbps,
downtime_ms) et figures/vm_resources.png. Réalisme : ÉMULÉ.
"""
from __future__ import annotations

import argparse
import csv
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

DOM = "upf-miot-vm"
VIRSH = ["virsh", "-c", "qemu:///system"]


def domstats() -> dict[str, float]:
    out = subprocess.run([*VIRSH, "domstats", DOM, "--cpu-total", "--balloon", "--vcpu"], capture_output=True,
                         text=True, check=True).stdout
    return {k.strip(): float(v) for k, v in (line.split("=", 1) for line in out.splitlines() if "=" in line)
            if v.strip().replace(".", "", 1).isdigit()}


def set_vcpus(n: int) -> None:
    """Changement à froid : l'ajout à chaud (setvcpus --live) n'active pas les processeurs dans l'invité Ubuntu
    (mesuré : nproc reste à 1). Arrêt, nouvelle configuration, redémarrage, puis UPF prête et UEs miot réattachés."""
    state = subprocess.run([*VIRSH, "domstate", DOM], capture_output=True, text=True).stdout.strip()
    if state == "running":
        subprocess.run([*VIRSH, "shutdown", DOM], capture_output=True, check=True)
        for _ in range(120):
            if subprocess.run([*VIRSH, "domstate", DOM], capture_output=True, text=True).stdout.strip() == "shut off":
                break
            time.sleep(1)
    subprocess.run([*VIRSH, "setvcpus", DOM, str(n), "--config"], capture_output=True, check=True)
    subprocess.run([*VIRSH, "start", DOM], capture_output=True, check=True)
    for _ in range(240):
        try:
            with urllib.request.urlopen("http://172.22.0.43:9090/metrics", timeout=1):
                break
        except OSError:
            time.sleep(1)
    reattach_miot()
    if guest_online_cpus() != n:
        raise RuntimeError(f"{guest_online_cpus()} processeurs actifs dans l'invité au lieu de {n}")


def reattach_miot(attempts: int = 4) -> None:
    """Redémarre les UEs miot jusqu'à 10 tunnels : la SMF met quelques secondes à se réassocier (PFCP) à l'UPF
    redémarrée ; avant cela, les sessions sont refusées (NETWORK_FAILURE)."""
    for _ in range(attempts):
        time.sleep(10)
        subprocess.run(["docker", "restart", "ue-miot"], capture_output=True, check=True)
        for _ in range(40):
            out = subprocess.run(["docker", "exec", "ue-miot", "sh", "-c", "ip -o -4 addr show | grep -c uesimtun"],
                                 capture_output=True, text=True).stdout.strip()
            if out.isdigit() and int(out) >= 10:
                return
            time.sleep(1)
    raise RuntimeError("UEs miot non réattachés après plusieurs essais")


def guest_online_cpus() -> int:
    key = Path.home() / "b6g-data" / "vm" / "id_upfvm"
    out = subprocess.run(["ssh", "-q", "-i", str(key), "-o", f"UserKnownHostsFile={key.parent / 'known_hosts'}",
                          "b6g@172.22.0.43", "nproc"], capture_output=True, text=True, timeout=15).stdout.strip()
    return int(out) if out.isdigit() else -1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--duration", type=int, default=15)
    args = ap.parse_args()
    sc = scn.load()
    prof = {"slice": "miot", "proto": "tcp", "direction": "dl", "rate_mbps": 0}
    rows = []
    for vcpu in (1, 2, 4):
        set_vcpus(vcpu)
        time.sleep(5)
        online = guest_online_cpus()
        for rep in range(1, args.reps + 1):
            ues = load.list_ues(sc)
            s0, t0 = domstats(), time.time()
            res = load.run(sc, "a07", f"vm-{vcpu}vcpu", args.duration, {"miot": ("saturation", prof, 1.0)}, ues=ues)
            s1, t1 = domstats(), time.time()
            thr = sum(r["value"] for r in res if r["metric"] == "throughput_mbps" and r["value"] is not None)
            cores = (s1["cpu.time"] - s0["cpu.time"]) / 1e9 / (t1 - t0)
            rows.append({"ts": now_iso(), "config": f"vm-{vcpu}vcpu-rep{rep}", "vcpu": vcpu, "vcpu_en_ligne": online,
                         "cpu_ratio": round(cores / vcpu, 4), "cpu_coeurs": round(cores, 3),
                         "memory_bytes": int(s1.get("balloon.rss", 0) * 1024), "throughput_mbps": round(thr, 2),
                         "downtime_ms": ""})
            print(rows[-1], flush=True)
            time.sleep(5)
    set_vcpus(1)
    out = HERE / "results" / "vm_resources.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    figure(rows)


def figure(rows: list[dict]) -> None:
    import statistics

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    v = [1, 2, 4]
    thr = [statistics.mean(r["throughput_mbps"] for r in rows if r["vcpu"] == x) for x in v]
    cores = [statistics.mean(r["cpu_coeurs"] for r in rows if r["vcpu"] == x) for x in v]
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.5))
    ax[0].bar([str(x) for x in v], thr, color="#4a6fa5")
    ax[0].set_title("Débit UPF en VM (10 UEs miot, TCP)")
    ax[0].set_ylabel("Mbit/s")
    ax[1].bar([str(x) for x in v], cores, color="#c98a1b")
    ax[1].set_title("CPU consommé par la VM")
    ax[1].set_ylabel("cœurs")
    for a in ax:
        a.set_xlabel("vCPU")
        a.grid(alpha=0.3, axis="y")
    fig.suptitle("Atelier 7 — UPF miot virtualisée (ÉMULÉ)", fontsize=10)
    fig.tight_layout()
    (HERE / "figures").mkdir(exist_ok=True)
    fig.savefig(HERE / "figures" / "vm_resources.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
