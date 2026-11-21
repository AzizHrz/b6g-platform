"""Génère le schéma d'architecture B6G (T02.1) à partir de config/scenario.yaml.

    .venv/bin/python docs/architecture/make_architecture.py

Produit docs/architecture/b6g-architecture.drawio (modifiable dans draw.io / diagrams.net) et b6g-architecture.png.
Couches et répartition physique : plan maître § 4.1. Chaque NF, slice, niveau et lien du scénario apparaît.
Les calques IA / sécurité (T02.2) et jumeau / ISAC (T02.3) sont complétés par l'équipe 2.
"""
from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from b6g_common import scenario as scn

OUT = Path(__file__).resolve().parent
W, H = 1400, 980

# Couleurs par couche (remplissage, contour)
C = {"intel": ("#e8f0fe", "#4a6fa5"), "sim": ("#eef7e8", "#5b8c3a"), "obs": ("#fff4e0", "#c98a1b"),
     "core": ("#fde9e7", "#b5473a"), "ran": ("#f3e8fd", "#7b4fa8"), "infra": ("#eceff1", "#607d8b"),
     "shared": ("#ffffff", "#333333"), "layer": ("#fafafa", "#9e9e9e")}


def boxes(sc: dict) -> tuple[list[dict], list[tuple]]:
    """Liste des blocs (id, texte, x, y, w, h, couleur) et des liens (source, cible, étiquette)."""
    b: list[dict] = []
    e: list[tuple] = []  # (source, cible, étiquette[, position de l'étiquette entre 0 et 1])

    def add(i, label, x, y, w=120, h=44, col="core", layer=False):
        b.append({"id": i, "label": label, "x": x, "y": y, "w": w, "h": h, "col": col, "layer": layer})

    p = sc["ports"]
    # Cadres de machines et de couches
    add("m2", "M2 « b6g-intel » — équipe 2", 20, 20, W - 40, 250, "layer", True)
    add("l4", "Couche 4 — Intelligence (modélisé)", 40, 55, W - 80, 95, "intel", True)
    add("l3", "Couche 3 — Simulation (simulé, hors ligne)", 40, 160, W - 80, 95, "sim", True)
    add("m1", "M1 « b6g-plat » — équipe 1", 20, 300, W - 40, 600, "layer", True)
    add("l2", "Couche 2 — Observabilité", 40, 335, W - 80, 85, "obs", True)
    add("l1", "Couche 1 — Émulation (Open5GS + UERANSIM, Docker, KVM, k3d)", 40, 430, W - 80, 455, "core", True)
    # Couche 4
    for k, (i, lab) in enumerate([("decision", f"API Décision :{p['decision']}"), ("twin", f"API Jumeau :{p['twin']}"),
                                  ("pulp", "Optimisation PuLP"), ("qiskit", "Qiskit"),
                                  ("ollama", f"LLM Ollama :{p['ollama']}"), ("secml", "security-ml"),
                                  ("datasets", "Jeux D1–D8")]):
        add(i, lab, 60 + k * 185, 90, 165, 44, "intel")
    # Couche 3
    for k, (i, lab) in enumerate([("sumo", "SUMO + ns-3 (mobilité)"), ("v2x", "VaN3Twin (V2X)"), ("ntn", "NTN"),
                                  ("isac", "ISAC"), ("ric", "RIC simulé")]):
        add(i, lab, 60 + k * 255, 195, 230, 44, "sim")
    # Couche 2
    for k, (i, lab) in enumerate([("prom", f"Prometheus :{p['prometheus']}"), ("graf", f"Grafana :{p['grafana']}"),
                                  ("push", f"Pushgateway :{p['pushgateway']}"), ("probes", "Sondes trafficgen\n(latence, perte)"),
                                  ("cadv", "cAdvisor")]):
        add(i, lab, 60 + k * 255, 365, 230, 44, "obs")
    # Couche 1 : services B6G
    add("ledger", f"Registre (Fabric) :{p['ledger']}", 60, 465, 200, 52, "infra")
    add("act", f"Actionneur :{p['actuator']}\ntc · docker · kubectl", 290, 465, 200, 52, "infra")
    add("loop", "Boucle MAPE-K\n(slice-autoscaler v0)", 520, 465, 200, 52, "infra")
    add("energy", "Exporteur énergie", 740, 465, 170, 52, "infra")
    add("registry", f"Registre d'images :{p['registry']}", 930, 465, 200, 52, "infra")
    add("attack", "Labo isolé b6g-lab", 1150, 465, 190, 52, "infra")
    # Cœur 5G : NF communes
    common = [nf for nf in sc["nfs"] if nf not in ("smf", "upf", "gnb")]
    for k, nf in enumerate(common):
        add(f"nf-{nf}", nf.upper(), 60 + k * 120, 545, 105, 40, "core")
    # SMF / UPF par slice + gNB + UEs + lien N6
    ues = sc["ues"]["count_per_slice"]
    for k, s in enumerate(sc["slices"]):
        x = 60 + k * 300
        add(s["smf"], f"{s['smf'].upper()}\nS-NSSAI {s['sst']}-{s['sd']}", x, 610, 140, 46, "core")
        add(s["upf"], f"{s['upf'].upper()}\n{s['subnet']}", x + 150, 610, 140, 46, "core")
        add(f"ue-{s['id']}", f"{ues} UEs {s['id']}\n(5QI {s['five_qi']})", x + 75, 765, 140, 46, "ran")
        add(f"n6-{s['id']}", f"lien n6-{s['id']}\n→ réseau de données", x + 150, 690, 140, 40, "shared")
        e += [(s["smf"], s["upf"], "N4 PFCP"), (s["upf"], f"n6-{s['id']}", "N6"),
              ("gnb", s["upf"], "N3 GTP-U", 0.8), (f"ue-{s['id']}", "gnb", "Uu (émulé)")]
    add("gnb", "gNB UERANSIM\n(lien n2n3-gnb1)", 1120, 680, 170, 46, "ran")
    add("mongo", "MongoDB (abonnés)", 1120, 610, 170, 40, "core")
    e += [("gnb", "nf-amf", "N2 NGAP / SCTP", 0.9), ("nf-udr", "mongo", "")]
    # Niveaux Edge / Fog / Cloud (k3d) et VM
    for k, (tier, t) in enumerate(sc["tiers"].items()):
        add(f"tier-{tier}", f"{tier.capitalize()} — {t['k8s_node']}\n+{t['added_rtt_ms']} ms (lien tier-{tier})",
            930 + (k % 2) * 210, 765 + (k // 2) * 55, 200, 46, "infra")
    add("vm", "VM QEMU/KVM\n(UPF miot, atelier 7)", 60, 835, 200, 40, "infra")
    add("deploys", "Déploiements k3d : " + ", ".join(sc.get("deployments", [])), 300, 835, 420, 40, "infra")
    # Flux principaux entre couches (interfaces I-xx)
    e += [("prom", "nf-amf", ""), ("act", "prom", "I-02", 0.6), ("probes", "push", ""),
          ("push", "prom", ""), ("cadv", "prom", ""), ("prom", "graf", ""),
          ("loop", "act", "I-04"), ("loop", "prom", ""),
          ("decision", "prom", "I-02 / I-03", 0.3), ("decision", "act", "I-04", 0.35), ("act", "ledger", "I-07"),
          ("loop", "decision", "I-05", 0.35), ("loop", "twin", "I-06", 0.35), ("act", "upf-embb", "")]
    return b, e


def drawio(b: list[dict], e: list[tuple]) -> str:
    cells = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    for x in b:
        fill, stroke = C[x["col"]]
        style = (f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};"
                 + ("verticalAlign=top;align=left;spacingLeft=8;fontStyle=1;dashed=1;" if x["layer"] else "fontSize=11;"))
        cells.append(f'<mxCell id="{x["id"]}" value="{escape(x["label"]).replace(chr(10), "&lt;br&gt;")}" '
                     f'style="{style}" vertex="1" parent="1"><mxGeometry x="{x["x"]}" y="{x["y"]}" '
                     f'width="{x["w"]}" height="{x["h"]}" as="geometry"/></mxCell>')
    for k, (s, t, lab, *_) in enumerate(e):
        cells.append(f'<mxCell id="e{k}" value="{escape(lab)}" style="endArrow=classic;html=1;fontSize=9;" edge="1" '
                     f'parent="1" source="{s}" target="{t}"><mxGeometry relative="1" as="geometry"/></mxCell>')
    return ('<mxfile host="b6g"><diagram name="Architecture B6G"><mxGraphModel dx="1400" dy="980" grid="1" '
            f'gridSize="10" pageWidth="{W}" pageHeight="{H}"><root>' + "".join(cells) + "</root></mxGraphModel>"
            "</diagram></mxfile>\n")


def png(b: list[dict], e: list[tuple], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    fig, ax = plt.subplots(figsize=(W / 100, H / 100), dpi=110)
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis("off")
    pos = {}
    for x in b:
        fill, stroke = C[x["col"]]
        ax.add_patch(FancyBboxPatch((x["x"], x["y"]), x["w"], x["h"], boxstyle="round,pad=0,rounding_size=6",
                                    fc=fill, ec=stroke, lw=1.2, ls="--" if x["layer"] else "-", zorder=1 if x["layer"] else 3))
        if x["layer"]:
            ax.text(x["x"] + 8, x["y"] + 14, x["label"], fontsize=9, weight="bold", color=stroke, zorder=2)
        else:
            ax.text(x["x"] + x["w"] / 2, x["y"] + x["h"] / 2, x["label"], fontsize=7.2, ha="center", va="center",
                    zorder=4)
        pos[x["id"]] = (x["x"] + x["w"] / 2, x["y"] + x["h"] / 2)
    for s, t, lab, *frac in e:
        f = frac[0] if frac else 0.5
        (x1, y1), (x2, y2) = pos[s], pos[t]
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1), zorder=2,
                    arrowprops={"arrowstyle": "->", "color": "#555555", "lw": 0.8, "shrinkA": 14, "shrinkB": 14})
        if lab:
            ax.text(x1 + (x2 - x1) * f, y1 + (y2 - y1) * f, lab, fontsize=6, color="#333333", ha="center", zorder=5,
                    bbox={"fc": "white", "ec": "none", "pad": 0.5, "alpha": 0.85})
    ax.set_title("Architecture B6G — couches et répartition M1 / M2 (généré depuis config/scenario.yaml)", fontsize=10)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def main() -> None:
    sc = scn.load()
    b, e = boxes(sc)
    (OUT / "b6g-architecture.drawio").write_text(drawio(b, e), encoding="utf-8")
    png(b, e, OUT / "b6g-architecture.png")
    print(f"{len([x for x in b if not x['layer']])} blocs, {len(e)} flux : docs/architecture/b6g-architecture.drawio / .png")


if __name__ == "__main__":
    main()
