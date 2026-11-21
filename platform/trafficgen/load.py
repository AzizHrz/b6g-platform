"""Générateur de charge trafficgen (M02, T04.2 / T06.3) : trafics simultanés des UEs selon les profils du scénario.

Chaque UE lance iperf3 vers son propre port du serveur `iperf` (IPERF_BASE_PORT + index d'UE), à travers son
interface uesimtunK, donc à travers gNB, GTP-U et l'UPF de sa slice. En parallèle, un `ping` par UE vers la
passerelle de son UPF mesure le RTT sous charge. Résultats au format measure.v1 (D2).

Réalisme : ÉMULÉ (paquets réels, sans couche radio). Aucune action sur la plateforme : mesure seulement.
"""
from __future__ import annotations

import ipaddress
import json
import re
import statistics
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from b6g_common import now_iso

IPERF_HOST = "iperf"
IPERF_BASE_PORT = 5201
RTT = re.compile(r"time=([\d.]+) ms")


@dataclass
class UE:
    ue_id: str
    slice: str
    container: str
    iface: str
    ip: str
    port: int


def list_ues(sc: dict) -> list[UE]:
    """UEs actifs : interfaces uesimtunK de chaque conteneur ue-<slice> (K = 0..n-1 -> ue-<slice>-01..n)."""
    ues = []
    n = sc["ues"]["count_per_slice"]
    for i, s in enumerate(sc["slices"]):
        container = f"ue-{s['id']}"
        out = subprocess.run(["docker", "exec", container, "ip", "-o", "-4", "addr", "show"],
                             capture_output=True, text=True, check=True).stdout
        addrs = dict(re.findall(r"\d+: (uesimtun\d+)\s+inet ([\d.]+)/", out))
        for k in range(n):
            iface = f"uesimtun{k}"
            if iface in addrs:
                ue_id = sc["ues"]["id_pattern"].format(slice=s["id"], nn=k + 1)
                ues.append(UE(ue_id, s["id"], container, iface, addrs[iface], IPERF_BASE_PORT + i * n + k))
    return ues


def gateway(sc: dict, slice_id: str) -> str:
    sub = next(s["subnet"] for s in sc["slices"] if s["id"] == slice_id)
    return str(ipaddress.ip_network(sub)[1])


def iperf(ue: UE, proto: str, direction: str, rate_bps: float, duration: int, size: int | None = None) -> dict:
    cmd = ["docker", "exec", ue.container, "iperf3", "-c", IPERF_HOST, "-p", str(ue.port), "-B", ue.ip,
           "-t", str(duration), "-J", "-b", str(int(rate_bps))]
    if proto == "udp":
        cmd.append("-u")
    if size:
        cmd += ["-l", str(size)]
    if direction == "dl":
        cmd.append("-R")
    cmd[cmd.index("-J"):cmd.index("-J")] = ["--connect-timeout", "5000"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 30)
    except subprocess.TimeoutExpired:
        # Client bloqué (connexion de contrôle iperf3) : mesure comptée en échec, le client est arrêté
        subprocess.run(["docker", "exec", ue.container, "pkill", "-f", f"iperf3 -c {IPERF_HOST} -p {ue.port} "],
                       capture_output=True, check=False)
        return {"error": f"délai dépassé ({duration + 30} s)"}
    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError:
        return {"error": (res.stderr or res.stdout)[-200:]}
    if "error" in data:
        return {"error": data["error"]}
    end = data["end"]
    if proto == "tcp":
        return {"throughput_mbps": end["sum_received"]["bits_per_second"] / 1e6, "loss_ratio": None}
    s = end["sum"]
    loss = s.get("lost_percent", 0) / 100
    # « sum_received » (iperf3 ≥ 3.16) donne le débit réellement reçu ; « sum » peut porter le débit émis (mode -R)
    if "sum_received" in end:
        return {"throughput_mbps": end["sum_received"]["bits_per_second"] / 1e6, "loss_ratio": loss}
    return {"throughput_mbps": s["bits_per_second"] * (1 - loss) / 1e6, "loss_ratio": loss}


def ping(ue: UE, dest: str, count: int, interval: float = 0.2) -> dict:
    res = subprocess.run(["docker", "exec", ue.container, "ping", "-I", ue.iface, "-n", "-c", str(count), "-i",
                          str(interval), "-W", "1", dest], capture_output=True, text=True, timeout=count * interval + 15)
    rtts = [float(x) for x in RTT.findall(res.stdout)]
    if not rtts:
        return {"rtt_ms": None, "rtt_p95_ms": None, "loss_ratio": 1.0}
    p95 = statistics.quantiles(rtts, n=100, method="inclusive")[94] if len(rtts) > 1 else rtts[0]
    return {"rtt_ms": statistics.median(rtts), "rtt_p95_ms": p95, "loss_ratio": 1 - len(rtts) / count}


def profile_params(profile: dict, scale: float) -> tuple[str, str, float, int | None]:
    """(proto, sens, débit en bit/s, taille de paquet) d'un profil du scénario, multiplié par `scale`."""
    if "rate_mbps" in profile:
        return profile["proto"], profile["direction"], profile["rate_mbps"] * 1e6 * scale, None
    size = profile["size_bytes"]
    return profile["proto"], profile["direction"], size * 8 * profile["rate_hz"] * scale, size


def run(sc: dict, run_id: str, scenario: str, duration: int, plan: dict[str, tuple[str, dict, float]],
        ues: list[UE] | None = None) -> list[dict]:
    """Lance simultanément, pour chaque slice de `plan` ({slice: (nom de profil, profil, échelle)}), le trafic de
    tous ses UEs et un ping par UE ; renvoie des lignes measure.v1."""
    ues = [u for u in (ues or list_ues(sc)) if u.slice in plan]
    for container in {u.container for u in ues}:   # clients restés bloqués d'une mesure précédente
        subprocess.run(["docker", "exec", container, "pkill", "iperf3"], capture_output=True, check=False)
    ts = now_iso()
    count = max(5, int((duration - 2) / 0.2))
    with ThreadPoolExecutor(max_workers=2 * len(ues)) as pool:
        traffic = {u.ue_id: pool.submit(iperf, u, *_args(plan[u.slice], duration)) for u in ues}
        pings = {u.ue_id: pool.submit(ping, u, gateway(sc, u.slice), count) for u in ues}
        rows = []
        for u in ues:
            t, p = traffic[u.ue_id].result(), pings[u.ue_id].result()
            prof_name = plan[u.slice][0]
            base = {"ts": ts, "run_id": run_id, "scenario": scenario, "slice": u.slice, "ue_id": u.ue_id,
                    "profile": prof_name}
            if "error" in t:
                rows.append({**base, "tool": "iperf3", "metric": "throughput_mbps", "value": None, "unit": "Mbit/s",
                             "error": t["error"]})
            else:
                rows.append({**base, "tool": "iperf3", "metric": "throughput_mbps", "value": round(t["throughput_mbps"], 4),
                             "unit": "Mbit/s"})
                if t["loss_ratio"] is not None:
                    rows.append({**base, "tool": "iperf3", "metric": "loss_ratio", "value": round(t["loss_ratio"], 5),
                                 "unit": "ratio"})
            if p["rtt_ms"] is not None:
                rows.append({**base, "tool": "ping", "metric": "rtt_ms", "value": round(p["rtt_ms"], 3), "unit": "ms"})
            if t.get("loss_ratio") is None:
                rows.append({**base, "tool": "ping", "metric": "loss_ratio", "value": round(p["loss_ratio"], 5),
                             "unit": "ratio"})
    return rows


def _args(entry: tuple[str, dict, float], duration: int) -> tuple:
    _name, profile, scale = entry
    proto, direction, rate, size = profile_params(profile, scale)
    return proto, direction, rate, duration, size
