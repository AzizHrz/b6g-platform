"""Atelier 3 (T03.3) : décodage des captures NGAP, NAS-5GS, PFCP, GTP-U et SBI par tshark.

    .venv/bin/python ateliers/a03/decode_captures.py [--pcap-dir ~/b6g-data/a03/pcap]

Les captures .pcap (non versionnées, `~/b6g-data/a03/pcap/`) sont prises dans les espaces réseau de gnb, amf,
smf-v2x et upf-v2x pendant le ré-enregistrement des 10 UEs v2x puis un ping. Le script produit, dans le dépôt :
    results/captures/sequence_ue.csv      séquence horodatée d'un UE (NGAP / NAS / SBI / PFCP / GTP-U)
    results/captures/resume.csv           nombre de messages par protocole et par type
    figures/sequence_enregistrement.png   diagramme de séquence annoté
Le chiffrement NAS est NEA0 (nul, premier de `ciphering_order` dans la configuration AMF) : tshark peut afficher les
messages NAS protégés en intégrité (option nas-5gs.null_decipher).
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import xml.etree.ElementTree as ET  # noqa: N817 - sortie PDML de tshark (fichier local)
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
OPTS = ["-o", "nas-5gs.null_decipher:TRUE", "-d", "tcp.port==7777,http2"]
# Types de messages (3GPP TS 29.244 pour PFCP, TS 29.281 pour GTP-U)
NAMES = {"PFCP": {"1": "Heartbeat Request", "2": "Heartbeat Response", "5": "Association Setup Request",
                  "6": "Association Setup Response", "50": "Session Establishment Request",
                  "51": "Session Establishment Response", "52": "Session Modification Request",
                  "53": "Session Modification Response", "54": "Session Deletion Request",
                  "55": "Session Deletion Response", "56": "Session Report Request", "57": "Session Report Response"},
         "GTP": {"0xff": "G-PDU (données utilisateur)", "0x01": "Echo Request", "0x02": "Echo Response",
                 "0x1a": "Error Indication", "0xfe": "End Marker"}}


def tshark(pcap: Path, display_filter: str, fields: list[str]) -> list[list[str]]:
    cmd = ["tshark", "-r", str(pcap), *OPTS, "-Y", display_filter, "-T", "fields", "-E", "separator=\t",
           "-E", "occurrence=a", "-E", "aggregator=|", *sum((["-e", f] for f in fields), [])]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return [line.split("\t") for line in out.splitlines()]


def _label(showname: str) -> str:
    """« procedureCode: id-InitialContextSetup (14) » -> « InitialContextSetup » ; « Message type: X (0x42) » -> « X »."""
    v = showname.split(": ", 1)[-1].rsplit(" (", 1)[0]
    return v[3:] if v.startswith("id-") else v


def ngap_events(pcap: Path) -> list[dict]:
    """Un événement par PDU NGAP (SCTP regroupe parfois plusieurs UEs dans une trame) : identifiant RAN de l'UE,
    procédure NGAP, type (initiating / successful / unsuccessful), messages NAS contenus, IMSI (MSIN du SUCI)."""
    pdml = subprocess.run(["tshark", "-r", str(pcap), *OPTS, "-Y", "ngap", "-T", "pdml"], capture_output=True,
                          text=True, check=True).stdout
    out = []
    for pkt in ET.fromstring(pdml).iter("packet"):
        t = float(next(f.get("show") for f in pkt.iter("field") if f.get("name") == "frame.time_epoch"))
        for proto in pkt.iter("proto"):
            if proto.get("name") != "ngap":
                continue
            f = {x.get("name"): x for x in proto.iter("field")}
            if "ngap.procedureCode" not in f:
                continue
            nas = [_label(x.get("showname")) for x in proto.iter("field")
                   if x.get("name") in ("nas-5gs.mm.message_type", "nas-5gs.sm.message_type")]
            kind = _label(f["ngap.NGAP_PDU"].get("showname")) if "ngap.NGAP_PDU" in f else ""
            proc = _label(f["ngap.procedureCode"].get("showname"))
            suffix = {"successfulOutcome": "Response", "unsuccessfulOutcome": "Failure"}.get(kind, "")
            out.append({"t": t, "ran_ue_id": f["ngap.RAN_UE_NGAP_ID"].get("show") if "ngap.RAN_UE_NGAP_ID" in f else "",
                        "ngap": proc + (f" ({suffix})" if suffix else ""), "nas": nas,
                        "msin": f["nas-5gs.mm.suci.msin"].get("show") if "nas-5gs.mm.suci.msin" in f else None,
                        "ue_ip": (f["nas-5gs.sm.pdu_addr_inf_ipv4"].get("show")
                                  if "nas-5gs.sm.pdu_addr_inf_ipv4" in f else None)})
    return out


def first_complete_ue(ev: list[dict]) -> str:
    """Premier UE dont la séquence va de la demande d'enregistrement à l'établissement de la session PDU."""
    seen: dict[str, set] = {}
    for e in ev:
        seen.setdefault(e["ran_ue_id"], set()).update([e["ngap"], *e["nas"]])
    for e in ev:
        s = seen.get(e["ran_ue_id"], set())
        if "Registration request" in s and "PDU session establishment accept" in s:
            return e["ran_ue_id"]
    raise SystemExit("aucun UE complet dans la capture")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcap-dir", type=Path, default=Path.home() / "b6g-data" / "a03" / "pcap")
    args = ap.parse_args()
    d = args.pcap_dir
    out_dir = HERE / "results" / "captures"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Séquence NGAP / NAS d'un UE (côté AMF)
    ev = ngap_events(d / "amf.pcap")
    ue = first_complete_ue(ev)
    seq = []
    msin = None
    for e in ev:
        if e["ran_ue_id"] != ue:
            continue
        msin = msin or e["msin"]
        seq.append({"t": e["t"], "interface": "N2", "protocole": "NGAP", "message": e["ngap"], "capture": "amf"})
        for m in e["nas"]:
            seq.append({"t": e["t"], "interface": "N1", "protocole": "NAS-5GS", "message": m, "capture": "amf"})
    t_start = seq[0]["t"]
    t_end = max(x["t"] for x in seq)
    # 2. SBI (HTTP/2) de l'AMF pour cet UE : requêtes dont le chemin contient son IMSI (MSIN du SUCI)
    for t, method, path in tshark(d / "amf.pcap", "http2.header.name == \":path\"",
                                  ["frame.time_epoch", "http2.headers.method", "http2.headers.path"]):
        p = path.split("|")[0].split("?")[0]
        if t_start <= float(t) <= t_end and method and msin and msin in p:
            seq.append({"t": float(t), "interface": "SBI", "protocole": "HTTP/2",
                        "message": f"{method.split('|')[0]} {p}", "capture": "amf"})
    # 3. PFCP (N4) côté SMF v2x : établissement de la session de cet UE, retrouvée par l'adresse IP attribuée
    #    (PDU address de « PDU session establishment accept » = UE IP address de la requête PFCP)
    ue_ip = next((e["ue_ip"] for e in ev if e["ran_ue_id"] == ue and e["ue_ip"]), None)
    req = [(float(t), seid) for t, seid in tshark(
        d / "smf-v2x.pcap", f"pfcp.msg_type == 50 && pfcp.ue_ip_addr_ipv4 == {ue_ip}", ["frame.time_epoch", "pfcp.seqno"])]
    pf = []
    for t, seqno in req[:1]:
        pf.append((t, f"PFCP Session Establishment Request (UE {ue_ip})"))
        for t2, _ in tshark(d / "smf-v2x.pcap", f"pfcp.msg_type == 51 && pfcp.seqno == {seqno}",
                            ["frame.time_epoch", "pfcp.seqno"])[:1]:
            pf.append((float(t2), "PFCP Session Establishment Response"))
    for t, info in pf:
        seq.append({"t": t, "interface": "N4", "protocole": "PFCP", "message": info, "capture": "smf-v2x"})
    # 4. GTP-U (N3) : premier paquet ICMP encapsulé vu par l'UPF après l'établissement
    gt = [g for g in tshark(d / "upf-v2x.pcap", "gtp && icmp", ["frame.time_epoch", "gtp.teid", "_ws.col.Info"])
          if float(g[0]) > t_end]   # premiers paquets du plan utilisateur après l'établissement de la session
    for t, teid, info in gt[:2]:
        seq.append({"t": float(t), "interface": "N3", "protocole": "GTP-U",
                    "message": f"TEID {teid.split('|')[0]} : {info} (UE de uesimtun0)", "capture": "upf-v2x"})
    seq.sort(key=lambda x: x["t"])
    with (out_dir / "sequence_ue.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["t_ms", "interface", "protocole", "message", "capture"], lineterminator="\n")
        w.writeheader()
        for x in seq:
            w.writerow({"t_ms": round((x["t"] - t_start) * 1000, 3), **{k: x[k] for k in ("interface", "protocole",
                                                                                         "message", "capture")}})

    # 5. Résumé : messages par protocole et par type, toutes captures
    count: Counter = Counter()
    for name, flt, field in (("amf", "ngap", "_ws.col.Info"), ("smf-v2x", "pfcp", "pfcp.msg_type"),
                             ("upf-v2x", "gtp", "gtp.message"), ("gnb", "gtp", "gtp.message")):
        for (val,) in tshark(d / f"{name}.pcap", flt, [field]):
            if flt == "ngap":
                for m in val.split(","):
                    m = m.strip().split(" [")[0]
                    if m and not m.startswith(("SACK", "Ack=", "Arwnd")):
                        count[(name, "NGAP/NAS", m)] += 1
            else:
                code = val.split("|")[0]
                count[(name, flt.upper(), NAMES[flt.upper()].get(code, code))] += 1
    with (out_dir / "resume.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["capture", "protocole", "message", "nombre"])
        for (cap, proto, msg), n in sorted(count.items()):
            w.writerow([cap, proto, msg, n])
    figure(seq, t_start)
    print(f"UE RAN_UE_NGAP_ID={ue} : {len(seq)} messages en {round((t_end - t_start) * 1000, 1)} ms ; "
          f"résumé : {sum(count.values())} messages")


def figure(seq: list[dict], t0: float) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    lanes = {"N1": 0, "N2": 1, "SBI": 2, "N4": 3, "N3": 4}
    colors = {"NGAP": "#7b4fa8", "NAS-5GS": "#b5473a", "HTTP/2": "#4a6fa5", "PFCP": "#c98a1b", "GTP-U": "#5b8c3a"}
    shown = [x for x in seq if x["interface"] != "SBI"] + [x for x in seq if x["interface"] == "SBI"][:12]
    shown.sort(key=lambda x: x["t"])
    fig, ax = plt.subplots(figsize=(11, max(5, 0.28 * len(shown) + 1)))
    for k, x in enumerate(shown):
        y = -k
        lane = lanes[x["interface"]]
        ax.scatter(lane, y, color=colors.get(x["protocole"], "grey"), s=25, zorder=3)
        ax.text(4.6, y, f"{(x['t'] - t0) * 1000:7.1f} ms  {x['protocole']:8s} {x['message'][:70]}", fontsize=7,
                va="center", family="monospace")
    ax.set_xticks(list(lanes.values()), [f"{k}\n" for k in lanes], fontsize=8)
    ax.set_xlim(-0.5, 11)
    ax.set_yticks([])
    for v in lanes.values():
        ax.axvline(v, color="#dddddd", zorder=1)
    ax.set_title("Enregistrement et session PDU d'un UE v2x (captures amf, smf-v2x, upf-v2x) — ÉMULÉ", fontsize=9)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()
    (HERE / "figures").mkdir(exist_ok=True)
    fig.savefig(HERE / "figures" / "sequence_enregistrement.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
