"""Laboratoire d'attaque isolé b6g-lab (M11, T27.2) : copie autonome du cœur et du RAN sur un réseau sans route externe.

    .venv/bin/python platform/attack-lab/render_lab.py        (appelé par make up-lab)

Réutilise les fonctions de platform/core/render.py (mêmes slices, abonnés, UEs, depuis config/scenario.yaml), avec :
  - réseau Docker « b6g-lab » en internal: true (10.230.0.0/24) : aucune sortie vers l'hôte ni vers Internet ;
  - services et conteneurs préfixés « lab- », projet Compose « b6g-lab », base MongoDB propre ;
  - deux conteneurs d'attaque (hping3, nmap, tcpdump) partageant l'espace réseau d'un conteneur d'UE, pour émettre
    à travers le tunnel de l'UE (uesimtunN) comme un terminal compromis.
Aucun élément n'est relié à la plateforme principale (b6g-core, Prometheus, Actionneur).
Sorties non versionnées : platform/attack-lab/generated/.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from b6g_common import scenario as scn

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "platform" / "attack-lab" / "generated"
PREFIX, NET, SUBNET = "lab-", "b6g-lab", "10.230.0.0/24"   # 172.23.0.0/16 occupé par fabric_test
ATTACK_IMAGE = "b6g/attack-tools:0.1.0"
ATTACKERS = {"embb": "lab-attacker-embb", "miot": "lab-attacker-miot"}   # slice dont les UEs portent les attaques

_spec = importlib.util.spec_from_file_location("render", ROOT / "platform" / "core" / "render.py")
render = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(render)


def lab_compose(sc: dict, a: dict[str, str]) -> dict:
    base = render.compose(sc, a)
    services = {}
    for name, svc in base["services"].items():
        s = dict(svc)
        s["container_name"] = PREFIX + svc["container_name"]
        if "depends_on" in s:
            s["depends_on"] = [PREFIX + d for d in s["depends_on"]]
        vols = []
        for v in s.get("volumes", []):
            v = v.replace("../upf-entrypoint.sh", str(ROOT / "platform" / "core" / "upf-entrypoint.sh"))
            v = v.replace("../../ran/generated/", "./ran/").replace("b6g-mongo:", "b6g-lab-mongo:")
            vols.append(v)
        if vols:
            s["volumes"] = vols
        s["networks"] = {NET: svc["networks"][render.NETWORK["name"]]}
        services[PREFIX + name] = s
    for slice_id, attacker in ATTACKERS.items():
        services[attacker] = {
            "image": ATTACK_IMAGE, "container_name": attacker, "network_mode": f"service:{PREFIX}ue-{slice_id}",
            "cap_add": ["NET_ADMIN", "NET_RAW"], "depends_on": [f"{PREFIX}ue-{slice_id}"], "restart": "unless-stopped",
        }
    return {"name": "b6g-lab", "services": services,
            "networks": {NET: {"name": NET, "driver": "bridge", "internal": True,
                               "ipam": {"config": [{"subnet": SUBNET}]}}},
            "volumes": {"b6g-lab-mongo": {}}}


def main() -> None:
    sc = scn.load()
    render.NETWORK = {"name": NET, "subnet": SUBNET}
    a = render.addresses(sc)
    for name, cfg in render.open5gs_configs(sc, a).items():
        render.dump(OUT / "open5gs" / f"{name}.yaml", cfg)
    render.dump(OUT / "subscribers.js", render.subscribers_js(sc))
    render.dump(OUT / "ran" / "gnb.yaml", render.gnb_config(sc, a))
    n = sc["ues"]["count_per_slice"]
    for i, s in enumerate(sc["slices"]):
        render.dump(OUT / "ran" / f"ue-{s['id']}.yaml", render.ue_config(sc, a, s, i * n))
    render.dump(OUT / "compose.yaml", lab_compose(sc, a))
    render.dump(OUT / "addresses.json", json.dumps({PREFIX + k: v for k, v in a.items()}, indent=1) + "\n")
    print(f"Laboratoire isolé généré : {OUT.relative_to(ROOT)} (réseau {NET} {SUBNET}, internal)")


if __name__ == "__main__":
    main()
