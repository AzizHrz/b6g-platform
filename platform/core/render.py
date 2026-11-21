"""Génère la configuration du cœur Open5GS et du RAN UERANSIM à partir de config/scenario.yaml (I-01).

    .venv/bin/python platform/core/render.py

Produit (non versionné, à régénérer après toute modification du scénario) :
    platform/core/generated/compose.yaml        projet Docker Compose « b6g-core » (cœur + RAN)
    platform/core/generated/open5gs/*.yaml      une configuration par NF (SMF et UPF : une par slice)
    platform/core/generated/subscribers.js      30 abonnés (10 par slice) pour MongoDB
    platform/ran/generated/gnb.yaml             gNB à 3 slices
    platform/ran/generated/ue-<slice>.yaml      gabarit d'UE par slice (lancé avec nr-ue -n 10)

Aucune adresse, slice ou nombre d'UE n'est écrit en dur : tout vient du scénario.
"""
from __future__ import annotations

import ipaddress
import json
from pathlib import Path

import yaml
from b6g_common import scenario as scn

ROOT = Path(__file__).resolve().parents[2]
CORE_OUT = ROOT / "platform" / "core" / "generated"
RAN_OUT = ROOT / "platform" / "ran" / "generated"
OBS_OUT = ROOT / "platform" / "observability" / "generated"

IMAGES = {
    "open5gs": "gradiant/open5gs:2.7.7",
    "ueransim": "gradiant/ueransim:3.2.8",
    "mongo": "mongo:6.0",
}
NETWORK = {"name": "b6g-core", "subnet": "172.22.0.0/24"}
# Adresse fixe de chaque conteneur dans le réseau b6g-core (dernier octet)
HOST_OCTET = {"mongo": 2, "nrf": 10, "ausf": 11, "udm": 12, "udr": 13, "pcf": 14, "nssf": 15, "bsf": 16,
              "amf": 20, "gnb": 50, "iperf": 70}
SMF_BASE, UPF_BASE, UE_BASE = 31, 41, 61
SBI_PORT, METRICS_PORT = 7777, 9090

# Valeurs de test publiques de UERANSIM (clé et OPc d'exemple) : aucune carte SIM réelle.
TEST_K = "465B5CE8B199B49FAA5F0A2EE238A6BC"
TEST_OPC = "E8ED289DEBA952E4283B54E88E6183CA"


def ip(octet: int) -> str:
    return str(ipaddress.ip_network(NETWORK["subnet"])[octet])


def addresses(sc: dict) -> dict[str, str]:
    addr = {name: ip(o) for name, o in HOST_OCTET.items()}
    for i, s in enumerate(sc["slices"]):
        addr[s["smf"]] = ip(SMF_BASE + i)
        addr[s["upf"]] = ip(UPF_BASE + i)
        addr[f"ue-{s['id']}"] = ip(UE_BASE + i)
    return addr


def plmn(sc: dict) -> dict:
    return {"mcc": sc["plmn"]["mcc"], "mnc": sc["plmn"]["mnc"]}


def snssai(s: dict) -> dict:
    return {"sst": s["sst"], "sd": s["sd"]}


def sbi(addr: str, nrf: str) -> dict:
    return {"server": [{"address": addr, "port": SBI_PORT}], "client": {"nrf": [{"uri": f"http://{nrf}:{SBI_PORT}"}]}}


def gateway(subnet: str) -> str:
    return str(ipaddress.ip_network(subnet)[1])


def prefix(subnet: str) -> int:
    return ipaddress.ip_network(subnet).prefixlen


def open5gs_configs(sc: dict, a: dict[str, str]) -> dict[str, dict]:
    logger = {"level": "info"}
    db = f"mongodb://{a['mongo']}/open5gs"
    nrf = a["nrf"]
    cfg: dict[str, dict] = {
        "nrf": {"logger": logger, "nrf": {"serving": [{"plmn_id": plmn(sc)}],
                                          "sbi": {"server": [{"address": nrf, "port": SBI_PORT}]}}},
        "ausf": {"logger": logger, "ausf": {"sbi": sbi(a["ausf"], nrf)}},
        "udm": {"logger": logger, "udm": {"sbi": sbi(a["udm"], nrf)}},
        "udr": {"logger": logger, "db_uri": db, "udr": {"sbi": sbi(a["udr"], nrf)}},
        "pcf": {"logger": logger, "db_uri": db,
                "pcf": {"sbi": sbi(a["pcf"], nrf), "metrics": {"server": [{"address": a["pcf"], "port": METRICS_PORT}]}}},
        "bsf": {"logger": logger, "bsf": {"sbi": sbi(a["bsf"], nrf)}},
    }
    nssf_sbi = sbi(a["nssf"], nrf)
    nssf_sbi["client"]["nsi"] = [{"uri": f"http://{nrf}:{SBI_PORT}", "s_nssai": snssai(s)} for s in sc["slices"]]
    cfg["nssf"] = {"logger": logger, "nssf": {"sbi": nssf_sbi}}
    cfg["amf"] = {"logger": logger, "amf": {
        "sbi": sbi(a["amf"], nrf),
        "ngap": {"server": [{"address": a["amf"]}]},
        "metrics": {"server": [{"address": a["amf"], "port": METRICS_PORT}]},
        "guami": [{"plmn_id": plmn(sc), "amf_id": {"region": 2, "set": 1}}],
        "tai": [{"plmn_id": plmn(sc), "tac": sc["tac"]}],
        "plmn_support": [{"plmn_id": plmn(sc), "s_nssai": [snssai(s) for s in sc["slices"]]}],
        "security": {"integrity_order": ["NIA2", "NIA1", "NIA0"], "ciphering_order": ["NEA0", "NEA1", "NEA2"]},
        "network_name": {"full": "B6G", "short": "B6G"},
        "amf_name": "b6g-amf0",
        "time": {"t3512": {"value": 540}},
    }}
    for s in sc["slices"]:
        session = [{"subnet": f"{gateway(s['subnet'])}/{prefix(s['subnet'])}", "gateway": gateway(s["subnet"]),
                    "dnn": s["dnn"]}]
        smf, upf = s["smf"], s["upf"]
        cfg[smf] = {"logger": logger, "smf": {
            "sbi": sbi(a[smf], nrf),
            "pfcp": {"server": [{"address": a[smf]}], "client": {"upf": [{"address": a[upf], "dnn": [s["dnn"]]}]}},
            "gtpc": {"server": [{"address": a[smf]}]},
            "gtpu": {"server": [{"address": a[smf]}]},
            "metrics": {"server": [{"address": a[smf], "port": METRICS_PORT}]},
            "session": session,
            "dns": ["8.8.8.8", "8.8.4.4"],
            "mtu": 1400,
            "info": [{"s_nssai": [{**snssai(s), "dnn": [s["dnn"]]}]}],
        }}
        cfg[upf] = {"logger": logger, "upf": {
            "pfcp": {"server": [{"address": a[upf]}]},
            "gtpu": {"server": [{"address": a[upf]}]},
            "session": session,
            "metrics": {"server": [{"address": a[upf], "port": METRICS_PORT}]},
        }}
    return cfg


def gnb_config(sc: dict, a: dict[str, str]) -> dict:
    return {
        "mcc": sc["plmn"]["mcc"], "mnc": sc["plmn"]["mnc"], "nci": "0x000000010", "idLength": 32, "tac": sc["tac"],
        "linkIp": a["gnb"], "ngapIp": a["gnb"], "gtpIp": a["gnb"],
        "amfConfigs": [{"address": a["amf"], "port": 38412}],
        "slices": [{"sst": s["sst"], "sd": int(s["sd"], 16)} for s in sc["slices"]],
        "ignoreStreamIds": True,
    }


def imsi(sc: dict, index: int) -> str:
    base = sc["ues"]["imsi_base"]
    return str(int(base) + index).zfill(len(base))


def ue_config(sc: dict, a: dict[str, str], s: dict, first_index: int) -> dict:
    nssai = [{"sst": s["sst"], "sd": int(s["sd"], 16)}]
    return {
        "supi": f"imsi-{imsi(sc, first_index)}", "mcc": sc["plmn"]["mcc"], "mnc": sc["plmn"]["mnc"],
        "protectionScheme": 0, "homeNetworkPublicKeyId": 1, "routingIndicator": "0000",
        "homeNetworkPublicKey": "5a8d38864820197c3394b92613b20b91633cbd897119273bf8e4a6f4eec0a650",
        "key": TEST_K, "op": TEST_OPC, "opType": "OPC", "amf": "8000",
        "imei": "356938035643803", "imeiSv": "4370816125816151",
        "gnbSearchList": [a["gnb"]],
        "uacAic": {"mps": False, "mcs": False},
        "uacAcc": {"normalClass": 0, "class11": False, "class12": False, "class13": False, "class14": False,
                   "class15": False},
        "sessions": [{"type": "IPv4", "apn": s["dnn"], "slice": nssai[0]}],
        "configured-nssai": nssai, "default-nssai": nssai,
        "integrity": {"IA1": True, "IA2": True, "IA3": True},
        "ciphering": {"EA1": True, "EA2": True, "EA3": True},
        "integrityMaxRate": {"uplink": "full", "downlink": "full"},
    }


def subscribers_js(sc: dict) -> str:
    """Script mongosh idempotent : un abonné par UE, rattaché à la slice et au DNN de sa slice."""
    n = sc["ues"]["count_per_slice"]
    docs = []
    for i, s in enumerate(sc["slices"]):
        ambr = {"downlink": {"value": 1, "unit": 3}, "uplink": {"value": 1, "unit": 3}}
        for k in range(n):
            docs.append({
                "imsi": imsi(sc, i * n + k), "msisdn": [], "imeisv": [], "mme_host": [], "mme_realm": [],
                "purge_flag": [],
                "security": {"k": TEST_K, "op": None, "opc": TEST_OPC, "amf": "8000"},
                "ambr": ambr,
                "slice": [{"sst": s["sst"], "sd": s["sd"], "default_indicator": True, "session": [{
                    "name": s["dnn"], "type": 3,
                    "qos": {"index": s["five_qi"], "arp": {"priority_level": 8, "pre_emption_capability": 1,
                                                           "pre_emption_vulnerability": 1}},
                    "ambr": ambr, "pcc_rule": []}]}],
                "access_restriction_data": 32, "subscriber_status": 0, "network_access_mode": 0,
                "subscribed_rau_tau_timer": 12, "__v": 0,
            })
    body = json.dumps(docs, indent=1)
    return ("// Généré par platform/core/render.py — ne pas modifier à la main\n"
            "db = db.getSiblingDB('open5gs');\n"
            f"const docs = {body};\n"
            "for (const d of docs) {\n"
            "  d.security.sqn = NumberLong(1);\n"
            "  db.subscribers.replaceOne({imsi: d.imsi}, d, {upsert: true});\n"
            "}\n"
            "print('abonnes: ' + db.subscribers.countDocuments({}));\n")


def compose(sc: dict, a: dict[str, str]) -> dict:
    net = NETWORK["name"]
    core_cfg = "./open5gs"
    services: dict[str, dict] = {
        "mongo": {"image": IMAGES["mongo"], "container_name": "mongo", "command": ["--bind_ip_all"],
                  "volumes": ["b6g-mongo:/data/db", "./subscribers.js:/subscribers.js:ro"],
                  "networks": {net: {"ipv4_address": a["mongo"]}}},
    }

    def nf(name: str, binary: str, depends: list[str], extra: dict | None = None) -> None:
        svc = {"image": IMAGES["open5gs"], "container_name": name,
               "command": [binary, "-c", f"/etc/open5gs/custom/{name}.yaml"],
               "volumes": [f"{core_cfg}/{name}.yaml:/etc/open5gs/custom/{name}.yaml:ro"],
               "networks": {net: {"ipv4_address": a[name]}}, "depends_on": depends, "restart": "unless-stopped"}
        svc.update(extra or {})
        services[name] = svc

    nf("nrf", "open5gs-nrfd", [])
    for name in ("ausf", "udm", "bsf", "nssf"):
        nf(name, f"open5gs-{name}d", ["nrf"])
    nf("udr", "open5gs-udrd", ["nrf", "mongo"])
    nf("pcf", "open5gs-pcfd", ["nrf", "mongo"])
    for s in sc["slices"]:
        upf = s["upf"]
        nf(upf, "open5gs-upfd", ["nrf"], {
            "entrypoint": ["/bin/bash", "/upf-entrypoint.sh"],
            "environment": {"UE_SUBNET": s["subnet"], "UE_GATEWAY": f"{gateway(s['subnet'])}/{prefix(s['subnet'])}"},
            # L'image tourne sous l'utilisateur open5gs (uid 999) : créer ogstun et les règles NAT exige root
            "user": "root", "cap_add": ["NET_ADMIN"], "devices": ["/dev/net/tun:/dev/net/tun"],
            "sysctls": {"net.ipv4.ip_forward": 1},
        })
        services[upf]["volumes"].append("../upf-entrypoint.sh:/upf-entrypoint.sh:ro")
        nf(s["smf"], "open5gs-smfd", ["nrf", upf])
    nf("amf", "open5gs-amfd", ["nrf", "ausf", "udm", "udr", "pcf", "nssf", "bsf"] + [s["smf"] for s in sc["slices"]])
    ran = "../../ran/generated"
    services["gnb"] = {"image": IMAGES["ueransim"], "container_name": "gnb", "entrypoint": ["nr-gnb"],
                       "command": ["-c", "/gnb.yaml"],
                       "volumes": [f"{ran}/gnb.yaml:/gnb.yaml:ro"], "depends_on": ["amf"],
                       "networks": {net: {"ipv4_address": a["gnb"]}}, "restart": "unless-stopped"}
    # Serveur de mesure côté réseau de données (N6) : joint par les UEs à travers la NAT de leur UPF
    services["iperf"] = {"image": IMAGES["ueransim"], "container_name": "iperf", "entrypoint": ["iperf3"],
                         "command": ["-s"], "networks": {net: {"ipv4_address": a["iperf"]}},
                         "restart": "unless-stopped"}
    n = sc["ues"]["count_per_slice"]
    for s in sc["slices"]:
        name = f"ue-{s['id']}"
        services[name] = {"image": IMAGES["ueransim"], "container_name": name, "entrypoint": ["nr-ue"],
                          "command": ["-c", f"/{name}.yaml", "-n", str(n)],
                          "volumes": [f"{ran}/{name}.yaml:/{name}.yaml:ro"], "depends_on": ["gnb"],
                          "cap_add": ["NET_ADMIN"], "devices": ["/dev/net/tun:/dev/net/tun"],
                          "networks": {net: {"ipv4_address": a[name]}}, "restart": "unless-stopped"}
    return {"name": "b6g-core", "services": services,
            "networks": {net: {"name": net, "driver": "bridge",
                               "ipam": {"config": [{"subnet": NETWORK["subnet"]}]}}},
            "volumes": {"b6g-mongo": {}}}


def prometheus_targets(sc: dict, a: dict[str, str]) -> list[dict]:
    """Cibles de collecte des métriques Open5GS (file_sd de Prometheus), étiquetées nf et slice."""
    targets = [{"targets": [f"{a[nf]}:{METRICS_PORT}"], "labels": {"nf": nf}} for nf in ("amf", "pcf")]
    for s in sc["slices"]:
        for nf in (s["smf"], s["upf"]):
            targets.append({"targets": [f"{a[nf]}:{METRICS_PORT}"], "labels": {"nf": nf, "slice": s["id"]}})
    return targets


def dump(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = data if isinstance(data, str) else yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    sc = scn.load()
    a = addresses(sc)
    for name, cfg in open5gs_configs(sc, a).items():
        dump(CORE_OUT / "open5gs" / f"{name}.yaml", cfg)
    dump(CORE_OUT / "subscribers.js", subscribers_js(sc))
    dump(CORE_OUT / "compose.yaml", compose(sc, a))
    dump(RAN_OUT / "gnb.yaml", gnb_config(sc, a))
    n = sc["ues"]["count_per_slice"]
    for i, s in enumerate(sc["slices"]):
        dump(RAN_OUT / f"ue-{s['id']}.yaml", ue_config(sc, a, s, i * n))
    dump(CORE_OUT / "addresses.json", json.dumps(a, indent=1) + "\n")
    dump(OBS_OUT / "targets" / "open5gs.json", json.dumps(prometheus_targets(sc, a), indent=1) + "\n")
    print(f"Configurations générées : {CORE_OUT.relative_to(ROOT)}, {RAN_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
