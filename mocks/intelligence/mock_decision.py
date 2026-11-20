"""Mock I-05 : service Décision à règles de seuils, réponses conformes au contrat.

Le module expose aussi `decide(snapshot)` (interface « politique » du plan MVP) : la boucle peut
l'appeler directement sans HTTP. Les vraies politiques (arbre scikit-learn, etc.) prendront sa place
dans intelligence/policies/ avec la même signature.

    uvicorn mocks.intelligence.mock_decision:app --port 8090
"""
from __future__ import annotations

import time
import uuid

from b6g_common import errors
from b6g_common import scenario as scn
from b6g_common.actions import ActionError, check
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

MODEL_VERSION = "mock-threshold-1.0.0"
POLICIES = {
    "qos-tree": "Seuils SLA par slice → slice.bandwidth (remplacé par l'arbre de décision en S2)",
    "placement": "Latence edge-infer → deployment.replicas sur l'Edge",
    "anomaly-reaction": "Taux de perte anormal → ue.isolate (cible fictive tant que D7 n'existe pas)",
}


def _bw(snapshot: dict, sc: dict) -> dict[str, dict]:
    bw = {}
    for s in sc["slices"]:
        cur = snapshot["slices"][s["id"]]["bw_limit_mbps"]
        rate = cur if cur is not None else s["bandwidth"]["rate_mbps"]
        bw[s["id"]] = {"rate_mbps": rate, "ceil_mbps": max(rate, s["bandwidth"]["ceil_mbps"])}
    return bw


def qos_tree(snapshot: dict, sc: dict, max_actions: int = 3) -> tuple[list[dict], str]:
    """Slice en violation de latence → +50 % de débit garanti, pris sur embb si la capacité manque."""
    bw = _bw(snapshot, sc)
    cap = sc["capacity"]["total_rate_mbps_max"]
    actions, why = [], []
    for s in sc["slices"]:
        sid, m = s["id"], snapshot["slices"][s["id"]]
        p95, lim = m["latency_ms_p95"], s["sla"]["latency_ms_p95_max"]
        if p95 is None or p95 <= lim or sid == "embb":
            continue
        new_rate = round(min(bw[sid]["rate_mbps"] * 1.5, 1000), 1)
        free = cap - sum(v["rate_mbps"] for k, v in bw.items() if k != sid)
        if new_rate > free:   # prendre sur embb, sans descendre sous son SLA de débit
            need = new_rate - free
            floor = scn.slice_by_id(sc, "embb")["sla"]["throughput_mbps_min"]
            give = round(min(need, bw["embb"]["rate_mbps"] - floor), 1)
            if give > 0:
                bw["embb"]["rate_mbps"] = round(bw["embb"]["rate_mbps"] - give, 1)
                actions.append({"type": "slice.bandwidth", "target": "embb",
                                "params": {"rate_mbps": bw["embb"]["rate_mbps"], "ceil_mbps": bw["embb"]["ceil_mbps"]},
                                "reason": f"libère {give:.1f} Mbit/s pour {sid}"})
                free += give
            new_rate = round(min(new_rate, free), 1)
        if new_rate <= bw[sid]["rate_mbps"]:
            continue
        bw[sid]["rate_mbps"] = new_rate
        actions.append({"type": "slice.bandwidth", "target": sid,
                        "params": {"rate_mbps": new_rate, "ceil_mbps": max(new_rate, bw[sid]["ceil_mbps"])},
                        "reason": f"latence p95 {sid} {p95:.1f} ms > {lim} ms"})
        why.append(f"latence p95 {sid} > seuil")
    return actions[:max_actions], (" ; ".join(why) or "SLA respectés")


def placement(snapshot: dict, sc: dict, max_actions: int = 3) -> tuple[list[dict], str]:
    edge = snapshot["tiers"]["edge"]
    cpu = edge["cpu_ratio"]
    dep = "b6g-edge-infer"
    reps = edge["replicas"].get(dep)
    if cpu is None or reps is None or dep not in sc.get("deployments", []):
        return [], "données Edge absentes"
    if cpu > 0.7 and reps < 10:
        return [{"type": "deployment.replicas", "target": dep, "params": {"replicas": reps + 1},
                 "reason": f"CPU Edge {cpu:.2f} > 0.70"}][:max_actions], "Edge chargé"
    if cpu < 0.2 and reps > 1:
        return [{"type": "deployment.replicas", "target": dep, "params": {"replicas": reps - 1},
                 "reason": f"CPU Edge {cpu:.2f} < 0.20"}][:max_actions], "Edge peu chargé"
    return [], "placement stable"


def anomaly_reaction(snapshot: dict, sc: dict, max_actions: int = 3) -> tuple[list[dict], str]:
    acts = []
    for s in sc["slices"]:
        loss = snapshot["slices"][s["id"]]["loss_ratio"]
        if loss is not None and loss > 5 * s["sla"]["loss_ratio_max"]:
            acts.append({"type": "ue.isolate", "target": f"ue-{s['id']}-01", "params": {"duration_s": 300},
                         "reason": f"perte {loss:.3f} anormale sur {s['id']} (mock : UE suspect fictif)"})
    return acts[:max_actions], ("anomalie de perte" if acts else "aucune anomalie")


IMPL = {"qos-tree": qos_tree, "placement": placement, "anomaly-reaction": anomaly_reaction}


def decide(snapshot: dict, policy: str = "qos-tree", max_actions: int = 3, sc: dict | None = None) -> dict:
    sc = sc or scn.default()
    t0 = time.perf_counter()
    actions, explanation = IMPL[policy](snapshot, sc, max_actions)
    return {"decision_id": str(uuid.uuid4()), "policy": policy, "actions": actions,
            "confidence": 0.9 if actions else 1.0, "explanation": explanation,
            "model_version": f"{policy}-{MODEL_VERSION}", "latency_ms": round((time.perf_counter() - t0) * 1000, 3)}


def _problem(status, title, detail=""):
    return JSONResponse({"type": f"https://b6g.local/problems/{status}", "title": title, "status": status,
                         "detail": detail}, status_code=status, media_type="application/problem+json")


def create_app() -> FastAPI:
    sc = scn.default()
    app = FastAPI(title="B6G mock_decision (I-05)", version="1.0.0")

    @app.get("/v1/health")
    def health():
        return {"status": "ok"}

    @app.get("/v1/policies")
    def policies():
        return [{"name": n, "version": "1.0.0", "model_version": f"{n}-{MODEL_VERSION}", "inputs": ["snapshot"],
                 "description": d} for n, d in POLICIES.items()]

    @app.post("/v1/decide")
    async def decide_ep(request: Request, x_b6g_caller: str | None = Header(None)):
        try:
            body = await request.json()
        except ValueError:
            return _problem(400, "JSON invalide")
        errs = errors(body, "decide-request")
        if errs:
            return _problem(400, "DecideRequest invalide", " ; ".join(errs[:5]))
        if body["policy"] not in IMPL:
            return _problem(422, "Politique inconnue", body["policy"])
        d = decide(body["snapshot"], body["policy"], body.get("constraints", {}).get("max_actions", 3), sc)
        for a in d["actions"]:
            try:
                check(a, sc, _bw(body["snapshot"], sc))
            except ActionError as e:
                return _problem(422, "La politique a produit une action invalide", e.detail)
        return d

    return app


app = create_app()
