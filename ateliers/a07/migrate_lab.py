"""Atelier 7 (T07.4) : migration à chaud QEMU entre deux hyperviseurs locaux, interruption mesurée par ping continu.

Exécuté dans le conteneur b6g/qemu-lab (platform/vm/qemu-lab), lancé par ateliers/a07/run_migration.sh :
  - pont interne br0 (10.10.0.1/24) et deux interfaces tap, une par hyperviseur ;
  - VM de test Ubuntu 22.04 (disque qcow2 adossé à l'image de base, partagé par les deux hyperviseurs), 10.10.0.10 ;
  - hyperviseur A lancé normalement, hyperviseur B lancé en attente (-incoming) ; migration par QMP (« migrate ») ;
  - ping toutes les 10 ms pendant la migration : plus long intervalle sans réponse = interruption mesurée ;
  - 3 migrations en aller-retour (A -> B -> A -> B).
Bibliothèque standard uniquement. Résultat : /out/migration.csv. Réalisme : ÉMULÉ (deux processus QEMU/KVM réels sur M1).
"""
from __future__ import annotations

import csv
import json
import os
import socket
import subprocess
import time
from datetime import datetime, timezone

LAB, OUT, BASE = "/lab", "/out", "/vm/jammy-server-cloudimg-amd64.img"
VM_IP, MAC, MIGRATE_PORT = "10.10.0.10", "52:54:00:b6:00:10", 4444


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True).stdout


class QMP:
    def __init__(self, path: str):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        for _ in range(100):
            try:
                self.s.connect(path)
                break
            except OSError:
                time.sleep(0.1)
        self.f = self.s.makefile("rw")
        json.loads(self.f.readline())
        self.cmd("qmp_capabilities")

    def cmd(self, name: str, **args) -> dict:
        self.f.write(json.dumps({"execute": name, "arguments": args}) + "\n")
        self.f.flush()
        while True:
            msg = json.loads(self.f.readline())
            if "return" in msg or "error" in msg:
                return msg


def setup() -> None:
    sh("ip link add br0 type bridge && ip addr add 10.10.0.1/24 dev br0 && ip link set br0 up")
    for tap in ("tap0", "tap1"):
        sh(f"ip tuntap add {tap} mode tap && ip link set {tap} master br0 && ip link set {tap} up")
    sh(f"qemu-img create -q -f qcow2 -b {BASE} -F qcow2 {LAB}/disk.qcow2 10G")
    os.makedirs(f"{LAB}/seed", exist_ok=True)
    with open(f"{LAB}/seed/meta-data", "w") as f:
        f.write("instance-id: migration-test\nlocal-hostname: migration-test\n")
    with open(f"{LAB}/seed/user-data", "w") as f:
        f.write("#cloud-config\npackage_update: false\n")
    with open(f"{LAB}/seed/network-config", "w") as f:
        f.write("version: 2\nethernets:\n  nic0:\n    match: {name: \"en*\"}\n"
                f"    addresses: [{VM_IP}/24]\n")
    sh(f"cd {LAB}/seed && xorriso -as mkisofs -quiet -o {LAB}/seed.iso -V cidata -J -r meta-data user-data network-config")


def start(name: str, tap: str, incoming: bool) -> QMP:
    cmd = (f"qemu-system-x86_64 -enable-kvm -cpu host -m 512 -smp 1 -name {name} -display none "
           f"-drive file={LAB}/disk.qcow2,if=virtio,cache=none -drive file={LAB}/seed.iso,media=cdrom,readonly=on "
           f"-netdev tap,id=n0,ifname={tap},script=no,downscript=no -device virtio-net-pci,netdev=n0,mac={MAC} "
           f"-qmp unix:{LAB}/{name}.qmp,server=on,wait=off -pidfile {LAB}/{name}.pid -daemonize")
    if incoming:
        cmd += f" -incoming tcp:127.0.0.1:{MIGRATE_PORT}"
    sh(cmd)
    return QMP(f"{LAB}/{name}.qmp")


def wait_ping(timeout: float = 180) -> float:
    t0 = time.time()
    while time.time() - t0 < timeout:
        if subprocess.run(["ping", "-c", "1", "-W", "1", VM_IP], capture_output=True).returncode == 0:
            return time.time() - t0
    raise RuntimeError("la VM de test ne répond pas")


def migrate(src: QMP, dst_name: str, dst_tap: str) -> tuple[QMP, dict]:
    dst = start(dst_name, dst_tap, incoming=True)
    log = open(f"{LAB}/ping-{dst_name}.log", "w")
    pinger = subprocess.Popen(["ping", "-D", "-n", "-i", "0.01", "-W", "1", VM_IP], stdout=log, stderr=subprocess.DEVNULL)
    time.sleep(2)
    t0 = time.time()
    src.cmd("migrate", uri=f"tcp:127.0.0.1:{MIGRATE_PORT}")
    while True:
        info = src.cmd("query-migrate")["return"]
        if info.get("status") in ("completed", "failed"):
            break
        time.sleep(0.05)
    t1 = time.time()
    time.sleep(2)
    pinger.terminate()
    pinger.wait()
    log.close()
    src.cmd("quit")
    stamps = []
    for line in open(f"{LAB}/ping-{dst_name}.log"):
        if line.startswith("[") and "bytes from" in line:
            stamps.append(float(line[1:line.index("]")]))
    gap = max((b - a for a, b in zip(stamps, stamps[1:], strict=False)), default=0.0) * 1000
    sent = int((t1 + 2 - (t0 - 2)) / 0.01)
    return dst, {"status": info.get("status"), "qemu_downtime_ms": info.get("downtime"),
                 "total_time_ms": info.get("total-time"), "duree_mesuree_s": round(t1 - t0, 3),
                 "ping_interruption_ms": round(gap, 1), "pings_recus": len(stamps), "pings_attendus_env": sent,
                 "ram_transferee_mo": round(info.get("ram", {}).get("transferred", 0) / 1e6, 1)}


def main() -> None:
    setup()
    hv = start("hvA", "tap0", incoming=False)
    boot = wait_ping()
    print(f"VM de test joignable après {boot:.1f} s", flush=True)
    time.sleep(10)
    rows = []
    names = [("hvB", "tap1"), ("hvA2", "tap0"), ("hvB2", "tap1")]
    for i, (dst_name, tap) in enumerate(names, 1):
        hv, res = migrate(hv, dst_name, tap)
        row = {"ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z", "config": f"migration-{i}",
               "vcpu": 1, "cpu_ratio": "", "memory_bytes": 512 * 1024 * 1024, "throughput_mbps": "",
               "downtime_ms": res["ping_interruption_ms"], **res}
        rows.append(row)
        print(row, flush=True)
        time.sleep(5)
    hv.cmd("quit")
    with open(f"{OUT}/migration.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    if os.environ.get("HOST_UID"):   # fichier rendu à l'utilisateur de l'hôte (le conteneur écrit en root)
        os.chown(f"{OUT}/migration.csv", int(os.environ["HOST_UID"]), int(os.environ["HOST_GID"]))
    print(f"démarrage de la VM de test : {boot:.1f} s", flush=True)


if __name__ == "__main__":
    main()
