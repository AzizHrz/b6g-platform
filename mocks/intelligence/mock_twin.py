"""Mock I-06 : jumeau naïf (latence ∝ charge / débit), réponses conformes au contrat.

    uvicorn mocks.intelligence.mock_twin:app --port 8091
"""
from __future__ import annotations

import copy

from b6g_common import errors, now_iso
from b6g_common import scenario as scn
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse


def whatif(snapshot: dict, actions: list[dict], horizon_s: int = 60, sc: dict | None = None) -> dict:
    sc = sc or scn.default()
    pred = {}
    for s in sc["slices"]:
        sid = s["id"]
        m = snapshot["slices"][sid]
        p = {"latency_ms_p95": m["latency_ms_p95"], "throughput_mbps": m["throughput_mbps"], "loss_ratio": m["loss_ratio"]}
        old = m["bw_limit_mbps"] or s["bandwidth"]["rate_mbps"]
        new = old
        for a in actions:
            if a["type"] == "slice.bandwidth" and a["target"] == sid:
                new = a["params"]["rate_mbps"]
            if a["type"] == "slice.state" and a["target"] == sid and not a["params"]["active"]:
                new = 0.0
        if new != old:
            ratio = old / new if new > 0 else None
            if p["latency_ms_p95"] is not None:
                p["latency_ms_p95"] = None if ratio is None else round(p["latency_ms_p95"] * ratio, 2)
            if p["throughput_mbps"] is not None:
                p["throughput_mbps"] = round(min(p["throughput_mbps"] * (1 if new > old else new / old), new), 3)
            if p["loss_ratio"] is not None and ratio is not None:
                p["loss_ratio"] = round(min(p["loss_ratio"] * ratio, 1.0), 5)
        pred[sid] = p
    violations = []
    for s in sc["slices"]:
        p, sla = pred[s["id"]], s["sla"]
        if p["latency_ms_p95"] is not None and p["latency_ms_p95"] > sla["latency_ms_p95_max"]:
            violations.append({"slice": s["id"], "metric": "latency_ms_p95", "value": p["latency_ms_p95"],
                               "limit": sla["latency_ms_p95_max"]})
        if p["loss_ratio"] is not None and p["loss_ratio"] > sla["loss_ratio_max"]:
            violations.append({"slice": s["id"], "metric": "loss_ratio", "value": p["loss_ratio"],
                               "limit": sla["loss_ratio_max"]})
    conf = 0.6 if horizon_s > 120 else 0.8
    return {"predicted": {"slices": copy.deepcopy(pred)}, "sla_ok": not violations, "violations": violations,
            "confidence": conf}


def create_app() -> FastAPI:
    sc = scn.default()
    app = FastAPI(title="B6G mock_twin (I-06)", version="1.0.0")

    @app.get("/v1/health")
    def health():
        return {"status": "ok"}

    @app.get("/v1/state")
    def state():
        return {"synced_at": now_iso(), "calibration_error_pct": None, "mode": "mock"}

    @app.post("/v1/whatif")
    async def whatif_ep(request: Request, x_b6g_caller: str | None = Header(None)):
        try:
            body = await request.json()
        except ValueError:
            body = None
        errs = errors(body, "whatif-request") if body is not None else ["JSON invalide"]
        if errs:
            return JSONResponse({"type": "https://b6g.local/problems/400", "title": "WhatIfRequest invalide",
                                 "status": 400, "detail": " ; ".join(errs[:5])}, status_code=400,
                                media_type="application/problem+json")
        return whatif(body["snapshot"], body["actions"], body.get("horizon_s", 60), sc)

    return app


app = create_app()
