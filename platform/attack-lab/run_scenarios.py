"""Campagne étiquetée du laboratoire isolé (M11, T27.2) : captures et étiquettes du jeu D7 `security_labels`.

    .venv/bin/python platform/attack-lab/run_scenarios.py        (make lab-run ; prérequis : make up-lab)

Déroulement (platform/attack-lab/scenarios.yaml) : captures tcpdump (ogstun de chaque UPF du laboratoire : trafic
des UEs désencapsulé ; NGAP de l'AMF), trafic normal de fond (un ping par seconde de chaque UE vers la victime), puis
chaque attaque après une pause de trafic normal. Une ligne d'étiquette par UE et par fenêtre (normal ou attaque).
Refuse de s'exécuter si le réseau b6g-lab n'est pas « internal ». Réalisme : ÉMULÉ.
Sorties (hors Git) : datasets/raw/security/{labels.csv, labels.manifest.yaml, captures.json, *.pcap}.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml
from b6g_common import scenario as scn
from b6g_common.paths import contracts_dir

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "datasets" / "raw" / "security"
# Interface « any » sur chaque UPF : le trafic montant (attaques) arrive encapsulé et ressort par eth0, pas par
# ogstun ; « any » capture les deux sens (ogstun pour le descendant, eth0 pour le montant décapsulé et le GTP-U).
CAPTURES = {"lab-upf-embb": "any", "lab-upf-v2x": "any", "lab-upf-miot": "any", "lab-amf": "any"}
TOOLS = "b6g/attack-tools:0.1.0"
IPERF_BASE_PORT = 5201


def iperf_port(sc: dict, slice_id: str, idx: int) -> int:
    """Port du serveur iperf3 de la victime pour un UE (même convention que platform/core/render.py)."""
    n = sc["ues"]["count_per_slice"]
    return IPERF_BASE_PORT + [s["id"] for s in sc["slices"]].index(slice_id) * n + idx


def sh(*cmd: str, check: bool = True) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=check).stdout


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def ue_ips(sc: dict) -> dict[str, str]:
    out = {}
    for s in sc["slices"]:
        text = sh("docker", "exec", f"lab-ue-{s['id']}", "ip", "-o", "-4", "addr", "show", check=False)
        for m in re.finditer(r"\d+: uesimtun(\d+)\s+inet ([\d.]+)/", text):
            out[sc["ues"]["id_pattern"].format(slice=s["id"], nn=int(m.group(1)) + 1)] = m.group(2)
    return out


def background(sc: dict, victim: str) -> None:
    for s in sc["slices"]:
        c = f"lab-ue-{s['id']}"
        sh("docker", "exec", c, "sh", "-c", "pkill ping; true", check=False)
        for k in range(sc["ues"]["count_per_slice"]):
            sh("docker", "exec", "-d", c, "ping", "-I", f"uesimtun{k}", "-i", "1", "-q", victim, check=False)


def tun_ip(slice_id: str, idx: int) -> str:
    out = sh("docker", "exec", f"lab-ue-{slice_id}", "ip", "-o", "-4", "addr", "show", f"uesimtun{idx}")
    return re.search(r"inet ([\d.]+)/", out).group(1)


def tun_tx(slice_id: str, idx: int) -> int:
    """Paquets émis par le tunnel : sert à prouver que l'attaque est bien passée par la liaison 5G de l'UE."""
    out = sh("docker", "exec", f"lab-ue-{slice_id}", "cat", f"/sys/class/net/uesimtun{idx}/statistics/tx_packets")
    return int(out.strip())


def pin_route(slice_id: str, idx: int, dst: str) -> None:
    """Route hôte vers la victime par le tunnel de l'UE (sinon le routage par source d'UERANSIM rejette le trafic)."""
    sh("docker", "exec", f"lab-ue-{slice_id}", "ip", "route", "replace", f"{dst}/32", "dev", f"uesimtun{idx}",
       "src", tun_ip(slice_id, idx), check=False)


def unpin_route(slice_id: str, idx: int, dst: str) -> None:
    sh("docker", "exec", f"lab-ue-{slice_id}", "ip", "route", "del", f"{dst}/32", check=False)


def wait_tunnels(container: str, n: int, timeout: float = 90) -> None:
    end = time.time() + timeout
    while time.time() < end:
        out = sh("docker", "exec", container, "sh", "-c", "ip -o -4 addr show | grep -c uesimtun", check=False).strip()
        if out.isdigit() and int(out) >= n:
            return
        time.sleep(1)
    raise RuntimeError(f"{container} : tunnels non rétablis")


def label_rows(ips: dict[str, str], t0: float, t1: float, attacked: dict[str, str]) -> list[dict]:
    """Une ligne par UE : étiquette d'attaque pour les UEs visés, « normal » pour les autres."""
    return [{"start_ts": iso(t0), "end_ts": iso(t1), "ue_id": ue, "src_ip": ip, "label": attacked.get(ue, "normal")}
            for ue, ip in sorted(ips.items())]


def main() -> None:
    sc = scn.load()
    cfg = yaml.safe_load((ROOT / "platform" / "attack-lab" / "scenarios.yaml").read_text(encoding="utf-8"))
    if sh("docker", "network", "inspect", "b6g-lab", "-f", "{{.Internal}}").strip() != "true":
        raise SystemExit("réseau b6g-lab absent ou non isolé (internal: true exigé) : arrêt")
    victim = sh("docker", "inspect", "-f", '{{(index .NetworkSettings.Networks "b6g-lab").IPAddress}}', cfg["victim"]).strip()
    n = sc["ues"]["count_per_slice"]
    OUT.mkdir(parents=True, exist_ok=True)
    for c, iface in CAPTURES.items():
        sh("docker", "rm", "-f", f"cap-{c}", check=False)
        sh("docker", "run", "-d", "--name", f"cap-{c}", "--net", f"container:{c}", "--cap-add", "NET_RAW",
           "--cap-add", "NET_ADMIN", "--entrypoint", "tcpdump", TOOLS, "-i", iface, "-s", "0", "-U", "-w", f"/tmp/{c}.pcap")
    labels: list[dict] = []
    try:
        background(sc, victim)
        ips = ue_ips(sc)
        t0 = time.time()
        time.sleep(cfg["background_s"])
        labels += label_rows(ips, t0, time.time(), {})
        for scen in cfg["scenarios"]:
            t0 = time.time()
            time.sleep(cfg["pause_s"])
            labels += label_rows(ips, t0, time.time(), {})
            p = scen.get("intensity", {})
            t0 = time.time()
            if scen["label"] in ("udp_flood", "scan"):
                slice_id = scen["ue"].split("-")[1]
                idx = int(scen["ue"].rsplit("-", 1)[1]) - 1
                iface = f"uesimtun{idx}"
                src = tun_ip(slice_id, idx)   # adresse source du tunnel : déclenche le routage par source d'UERANSIM
                pin_route(slice_id, idx, victim)
                tx0 = tun_tx(slice_id, idx)
                if scen["label"] == "udp_flood":
                    # Inondation UDP par iperf3 (socket normal, routé par le tunnel via l'adresse source -B) :
                    # hping3 utilise un socket brut qui contourne le tunnel. Débit élevé = flood.
                    bitrate = f"{p['pps'] * p['size_bytes'] * 8}"
                    sh("docker", "exec", f"lab-ue-{slice_id}", "iperf3", "-c", victim, "-p",
                       str(iperf_port(sc, slice_id, idx)), "-B", src, "-u", "-b", bitrate, "-l", str(p["size_bytes"]),
                       "-t", str(scen["duration_s"]), check=False)
                else:
                    # Balayage TCP par connexion (-sT : sockets normaux) : la route /32 épinglée fixe la source au
                    # tunnel, donc le balayage sort par le tunnel. -sS (socket brut) contournerait le tunnel.
                    sh("docker", "exec", f"lab-attacker-{slice_id}", "timeout", str(scen["duration_s"] + 10), "nmap",
                       "-sT", f"-{p['timing']}", "-p", p["ports"], "-Pn", "--max-retries", "1", victim, check=False)
                sent = tun_tx(slice_id, idx) - tx0
                unpin_route(slice_id, idx, victim)
                # Honnêteté du jeu : si rien n'est passé par le tunnel, on n'étiquette pas une attaque fictive
                if sent < 10:
                    raise SystemExit(f"{scen['label']} : seulement {sent} paquets émis par {iface} ; "
                                     "trafic d'attaque non confirmé, jeu D7 non produit")
                attacked = {scen["ue"]: scen["label"]}
            elif scen["label"] == "reg_storm":
                c = scen["ue_container"]
                for _ in range(p["restarts"]):
                    sh("docker", "restart", "-t", "0", c)
                    time.sleep(p["interval_s"])
                wait_tunnels(c, n)
                background(sc, victim)
                new = ue_ips(sc)
                slice_id = c.removeprefix("lab-ue-")
                attacked = {ue: "reg_storm" for ue in new if ue.startswith(f"ue-{slice_id}-")}
                ips = new
            else:
                raise SystemExit(f"scénario inconnu : {scen['label']}")
            t1 = max(time.time(), t0 + scen["duration_s"])
            time.sleep(max(0.0, t1 - time.time()))
            labels += label_rows(ips, t0, t1, attacked)
            print(scen["label"], "terminé", flush=True)
        t0 = time.time()
        time.sleep(cfg["pause_s"])
        labels += label_rows(ips, t0, time.time(), {})
    finally:
        for s in sc["slices"]:
            sh("docker", "exec", f"lab-ue-{s['id']}", "sh", "-c", "pkill ping; true", check=False)
        files = []
        for c in CAPTURES:
            sh("docker", "stop", "-t", "5", f"cap-{c}", check=False)
            sh("docker", "cp", f"cap-{c}:/tmp/{c}.pcap", str(OUT / f"{c}.pcap"), check=False)
            sh("docker", "rm", f"cap-{c}", check=False)
            f = OUT / f"{c}.pcap"
            if f.exists():
                files.append({"file": f.name, "interface": CAPTURES[c], "bytes": f.stat().st_size,
                              "sha256": hashlib.sha256(f.read_bytes()).hexdigest()})
        (OUT / "captures.json").write_text(json.dumps(files, indent=1) + "\n", encoding="utf-8")
    with (OUT / "labels.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["start_ts", "end_ts", "ue_id", "src_ip", "label"], lineterminator="\n")
        w.writeheader()
        w.writerows(labels)
    spec = yaml.safe_load((contracts_dir() / "datasets.yaml").read_text(encoding="utf-8"))["D7"]
    schema = [{"column": c, "type": t, **({"values": spec["categories"][c]} if c in spec.get("categories", {}) else {})}
              for c, t in spec["columns"].items()]
    man = {"id": "D7", "name": "security_labels", "version": "1.0.0",
           "producer": "I1.1 / platform/attack-lab/run_scenarios.py", "created_at": iso(time.time()),
           "source": "laboratoire isolé b6g-lab (réseau Docker internal), captures dans captures.json",
           "realism": "EMULE", "file": "labels.csv",
           "sha256": hashlib.sha256((OUT / "labels.csv").read_bytes()).hexdigest(), "rows": len(labels),
           "time_range": {"start": labels[0]["start_ts"], "end": labels[-1]["end_ts"]}, "schema": schema}
    (OUT / "labels.manifest.yaml").write_text(yaml.safe_dump(man, sort_keys=False, allow_unicode=True), encoding="utf-8")
    counts: dict[str, int] = {}
    for r in labels:
        counts[r["label"]] = counts.get(r["label"], 0) + 1
    print(f"D7 : {len(labels)} étiquettes {counts} ; captures : {[(x['file'], x['bytes']) for x in files]}")


if __name__ == "__main__":
    main()
