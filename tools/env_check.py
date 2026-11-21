"""make check / make env-check : vérifie l'environnement (T01.6).

INT0 n'exige que Python et les modules du dépôt (code de sortie 1 en cas d'échec). Les autres lignes sont
indicatives : elles disent ce qui manque pour les jalons suivants, sans rien installer.
Seuils matériels : plan maître § 4.2 et docs/setup/ENVIRONMENT.md (étape 0).
"""
from __future__ import annotations

import importlib
import os
import platform as pf
import shutil
import socket
import subprocess
import sys
import urllib.request

OK, KO, INFO = "\033[32mOK\033[0m", "\033[31mÉCHEC\033[0m", "\033[33mINFO\033[0m"
SBIN = os.pathsep.join(["/usr/local/sbin", "/usr/sbin", "/sbin"])
fail = 0


def line(status: str, what: str, detail: str = "") -> None:
    print(f"[{status}] {what}{(' : ' + detail) if detail else ''}")


def which(tool: str) -> str | None:
    return shutil.which(tool) or shutil.which(tool, path=SBIN)


def run(*cmd: str) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None


def http_ok(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status == 200
    except OSError:
        return False


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
sc = None
try:
    from b6g_common import scenario
    sc = scenario.load()
    line(OK, "config/scenario.yaml", f"{len(sc['slices'])} slices, {3 * sc['ues']['count_per_slice']} UEs")
except Exception as e:  # noqa: BLE001
    line(KO, "config/scenario.yaml", str(e))
    fail += 1

print("\n== Matériel (plan maître § 4.2 : 16 Go de RAM minimum, 32 conseillés ; 60 Go de disque libre minimum) ==")
mem_gb = int(next(x for x in open("/proc/meminfo") if x.startswith("MemTotal")).split()[1]) / 1024 / 1024
line(OK if mem_gb >= 15 else INFO, "RAM", f"{mem_gb:.1f} Gio")
line(OK if (os.cpu_count() or 0) >= 8 else INFO, "CPU", f"{os.cpu_count()} cœurs logiques")
free_gb = shutil.disk_usage(".").free / 1e9
line(OK if free_gb >= 60 else INFO, "disque libre", f"{free_gb:.0f} Go" + ("" if free_gb >= 60 else " (< 60 Go)"))
kvm = os.path.exists("/dev/kvm")
line(OK if kvm else INFO, "/dev/kvm", "présent" if kvm else "absent (VM de l'atelier 7)")

print("\n== Plateforme (INT1 et suivants ; indicatif, rien n'est installé) ==")
for tool in ("git", "docker", "tc", "iperf3", "tcpdump", "tshark", "qemu-system-x86_64", "virsh", "virt-install",
             "k3d", "kubectl", "helm"):
    found = which(tool)
    line(OK if found else INFO, tool, found or "absent")
d = run("docker", "info", "--format", "{{.ServerVersion}}")
line(OK if d and d.returncode == 0 else INFO, "accès au démon Docker", d.stdout.strip() if d and d.returncode == 0
     else "refusé ou démon arrêté (groupe docker ?)")
c = run("docker", "compose", "version", "--short")
line(OK if c and c.returncode == 0 else INFO, "Docker Compose", c.stdout.strip() if c and c.returncode == 0 else "absent")
mods = open("/proc/modules").read()
if "sctp " in mods:
    line(OK, "module noyau sctp", "chargé")
else:
    m = run(which("modinfo") or "modinfo", "sctp")
    line(INFO, "module noyau sctp", "disponible, non chargé (sudo modprobe sctp)" if m and m.returncode == 0
         else "introuvable (interface N2 d'Open5GS)")
t = run("timedatectl", "show", "-p", "NTPSynchronized", "--value")
line(OK if t and t.stdout.strip() == "yes" else INFO, "horloge synchronisée (NTP)",
     t.stdout.strip() if t else "non vérifiable")
if sc:
    for role, host in sc["hosts"].items():
        try:
            line(OK, f"nom {host} ({role})", socket.gethostbyname(host))
        except OSError:
            line(INFO, f"nom {host} ({role})", "non résolu (/etc/hosts, voir docs/hardware.md)")
    ports = sc["ports"]
    for name, url in (("Prometheus", f"http://127.0.0.1:{ports['prometheus']}/-/ready"),
                      ("Grafana", f"http://127.0.0.1:{ports['grafana']}/api/health"),
                      ("Actionneur", f"http://127.0.0.1:{ports['actuator']}/v1/health"),
                      ("Registre d'images", f"http://127.0.0.1:{ports['registry']}/v2/")):
        up = http_ok(url)
        line(OK if up else INFO, name, "joignable" if up else "arrêté")

sys.exit(1 if fail else 0)
