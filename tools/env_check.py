"""make check : vérifie l'environnement. INT0 n'exige que Python ; le reste est indiqué pour INT1."""
from __future__ import annotations

import importlib
import os
import platform as pf
import shutil
import subprocess
import sys

OK, KO, INFO = "\033[32mOK\033[0m", "\033[31mÉCHEC\033[0m", "\033[33mINFO\033[0m"
fail = 0


def line(status, what, detail=""):
    print(f"[{status}] {what}{(' : ' + detail) if detail else ''}")


print("== INT0 (obligatoire) ==")
if sys.version_info >= (3, 11):
    line(OK, "Python", pf.python_version())
else:
    line(KO, "Python", f"{pf.python_version()} < 3.11")
    fail += 1
for mod in ("b6g_common", "b6g_actuator", "jsonschema", "yaml", "fastapi", "httpx", "pytest"):
    try:
        importlib.import_module(mod)
        line(OK, f"module {mod}")
    except ImportError as e:
        line(KO, f"module {mod}", str(e))
        fail += 1
try:
    from b6g_common import scenario
    sc = scenario.load()
    line(OK, "config/scenario.yaml", f"{len(sc['slices'])} slices, {3 * sc['ues']['count_per_slice']} UEs")
except Exception as e:  # noqa: BLE001
    line(KO, "config/scenario.yaml", str(e))
    fail += 1

print("\n== INT1 et suivants (indicatif, rien n'est installé par ce script) ==")
for tool in ("git", "docker", "kubectl", "k3d", "qemu-system-x86_64", "tc", "iperf3"):
    found = shutil.which(tool)
    line(OK if found else INFO, tool, "présent" if found else "absent (pas nécessaire pour INT0)")
kvm = os.path.exists("/dev/kvm")
line(OK if kvm else INFO, "/dev/kvm", "présent" if kvm else "absent (VM de l'atelier 7)")
try:
    mods = open("/proc/modules").read()
    has_sctp = "sctp" in mods
    if not has_sctp:
        has_sctp = subprocess.run(["modinfo", "sctp"], capture_output=True).returncode == 0
    line(OK if has_sctp else INFO, "module noyau sctp", "disponible" if has_sctp else "introuvable (N2 Open5GS)")
except OSError:
    line(INFO, "module noyau sctp", "non vérifiable")
try:
    mem_kb = int(next(x for x in open("/proc/meminfo") if x.startswith("MemTotal")).split()[1])
    line(INFO, "RAM", f"{mem_kb / 1024 / 1024:.1f} Gio ; CPU : {os.cpu_count()} ; disque libre : "
         f"{shutil.disk_usage('.').free / 1e9:.0f} Go")
except (OSError, StopIteration):
    pass

sys.exit(1 if fail else 0)
