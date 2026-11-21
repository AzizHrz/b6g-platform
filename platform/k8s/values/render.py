"""Valeurs Helm d'Open5GS et de UERANSIM dans k3d (T08.2), générées depuis config/scenario.yaml.

    .venv/bin/python platform/k8s/values/render.py        (appelé par make k8s-core)

Charts Gradiant : open5gs 2.2.5 (Open5GS 2.7.2) et ueransim-gnb 0.2.6 (UERANSIM 3.2.6), version figée.
Le cœur déployé dans Kubernetes porte la slice embb du scénario (PLMN, S-NSSAI, DNN, sous-réseau) et un UE de test
(premier IMSI de la slice). Sorties non versionnées : platform/k8s/generated/open5gs.yaml et gnb.yaml.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from b6g_common import scenario as scn

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "platform" / "k8s" / "generated"
SLICE = "embb"
TEST_K = "465B5CE8B199B49FAA5F0A2EE238A6BC"      # valeurs de test publiques de UERANSIM
TEST_OPC = "E8ED289DEBA952E4283B54E88E6183CA"


def main() -> None:
    sc = scn.load()
    s = next(x for x in sc["slices"] if x["id"] == SLICE)
    plmn = {"mcc": sc["plmn"]["mcc"], "mnc": sc["plmn"]["mnc"]}
    gw = s["subnet"].split("/")[0].rsplit(".", 1)[0] + ".1/" + s["subnet"].split("/")[1]
    imsi = sc["ues"]["imsi_base"]
    msin = imsi[len(plmn["mcc"]) + len(plmn["mnc"]):]
    core = {
        "populate": {"enabled": True, "initCommands": [
            f"open5gs-dbctl add_ue_with_slice {imsi} {TEST_K} {TEST_OPC} {s['dnn']} {s['sst']} {s['sd']}"]},
        "webui": {"enabled": False},
        # Cœur 5G autonome uniquement : fonctions 4G (EPC) désactivées
        **{nf: {"enabled": False} for nf in ("hss", "mme", "pcrf", "sgwc", "sgwu")},
        "amf": {"config": {
            "guamiList": [{"plmn_id": plmn, "amf_id": {"region": 2, "set": 1}}],
            "taiList": [{"plmn_id": plmn, "tac": [sc["tac"]]}],
            "plmnList": [{"plmn_id": plmn, "s_nssai": [{"sst": s["sst"], "sd": s["sd"]}]}],
            "networkName": "B6G"}},
        # PLMN servi par le NRF : sans lui, le SCP traite l'UE comme itinérant (« No SEPP », rejet cause 95)
        "nrf": {"config": {"servingList": [{"plmn_id": plmn}]}},
        "nssf": {"config": {"nsiList": [{"uri": "", "sst": s["sst"], "sd": s["sd"]}]}},
        "smf": {"config": {"pcrf": {"enabled": False}, "subnetList": [{"subnet": gw, "dnn": s["dnn"]}]}},
        "upf": {"config": {"subnetList": [{"subnet": gw, "dnn": s["dnn"], "dev": "ogstun", "createDev": True,
                                           "enableNAT": True}]}},
        # Images Bitnami retirées de docker.io/bitnami en 2025 : même version depuis bitnamilegacy
        "mongodb": {"image": {"repository": "bitnamilegacy/mongodb", "tag": "5.0.10-debian-11-r3"}},
    }
    sd_hex = "0x" + s["sd"]
    gnb = {
        "mcc": plmn["mcc"], "mnc": plmn["mnc"], "sst": s["sst"], "sd": sd_hex, "tac": f"{sc['tac']:04d}",
        "amf": {"hostname": "open5gs-amf-ngap"},
        "ues": {"enabled": True, "count": 1, "initialMSISDN": msin, "key": TEST_K, "op": TEST_OPC, "opType": "OPC",
                "apnList": [{"type": "IPv4", "apn": s["dnn"], "slice": {"sst": s["sst"], "sd": sd_hex},
                             "emergency": False}]},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "open5gs.yaml").write_text(yaml.safe_dump(core, sort_keys=False), encoding="utf-8")
    (OUT / "gnb.yaml").write_text(yaml.safe_dump(gnb, sort_keys=False), encoding="utf-8")
    print(f"Valeurs Helm générées : {OUT.relative_to(ROOT)} (slice {SLICE}, IMSI {imsi})")


if __name__ == "__main__":
    main()
