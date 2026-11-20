"""I-04 : contrôle d'un ActionRequest (schéma, cible, capacité) partagé par l'Actionneur et les politiques."""
from __future__ import annotations

from dataclasses import dataclass

from . import scenario as scn
from .schemas import errors

# Version de l'API Actionneur qui introduit chaque type (§ 6.6).
TYPE_VERSION = {"slice.bandwidth": 1, "noop": 1, "slice.state": 2, "link.netem": 2, "deployment.replicas": 2,
                "deployment.placement": 2, "ue.isolate": 2, "ue.release": 2}


@dataclass
class ActionError(Exception):
    status: int          # 400 validation, 404 cible inconnue, 409 conflit de capacité
    title: str
    detail: str

    def problem(self) -> dict:
        return {"type": f"https://b6g.local/problems/{self.status}", "title": self.title,
                "status": self.status, "detail": self.detail}


def check(action: dict, sc: dict, bandwidth: dict[str, dict] | None = None) -> None:
    """Lève ActionError si l'action est invalide. `bandwidth` = état courant {slice: {rate_mbps, ceil_mbps}}."""
    errs = errors(action, "action-request")
    if errs:
        raise ActionError(400, "ActionRequest invalide", " ; ".join(errs[:5]))
    t, target, params = action["type"], action["target"], action["params"]
    if t.startswith("slice."):
        if target not in scn.slice_ids(sc):
            raise ActionError(404, "Slice inconnue", target)
    elif t == "link.netem":
        if target not in sc["links"]:
            raise ActionError(404, "Lien inconnu", target)
    elif t.startswith("deployment."):
        if target not in sc.get("deployments", []):
            raise ActionError(404, "Déploiement inconnu", target)
    elif t.startswith("ue."):
        if target not in scn.ue_ids(sc):
            raise ActionError(404, "UE inconnu", target)
    if t == "slice.bandwidth":
        bw = {s["id"]: dict(s["bandwidth"]) for s in sc["slices"]}
        if bandwidth:
            bw.update({k: dict(v) for k, v in bandwidth.items()})
        rate = params["rate_mbps"]
        ceil = params.get("ceil_mbps", max(rate, bw[target]["ceil_mbps"]))
        if ceil < rate:
            raise ActionError(400, "ceil_mbps < rate_mbps", f"rate={rate} ceil={ceil}")
        bw[target] = {"rate_mbps": rate, "ceil_mbps": ceil}
        total = sum(v["rate_mbps"] for v in bw.values())
        cap = sc["capacity"]["total_rate_mbps_max"]
        if total > cap:
            raise ActionError(409, "Capacité dépassée", f"somme des rate_mbps = {total} > {cap}")
