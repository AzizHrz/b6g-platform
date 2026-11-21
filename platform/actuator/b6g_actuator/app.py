"""API Actionneur v1 (contracts/openapi/actuator.yaml).

    uvicorn b6g_actuator.app:app --port 8081
    B6G_ACTUATOR_BACKEND=memory   (INT0 ; tc à partir d'INT1)
    B6G_LEDGER_URL=http://127.0.0.1:8082   (sinon les événements restent dans la file locale)
"""
from __future__ import annotations

import copy
import os
import uuid
from collections import Counter

import httpx
from b6g_common import events, now_iso
from b6g_common import scenario as scn
from b6g_common.actions import ActionError, check
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from . import __version__
from .backends import get_backend

EVENT_TYPE = {"slice.bandwidth": "slice.resized", "slice.state": "slice.state", "link.netem": "link.netem",
              "deployment.replicas": "deployment.scaled", "deployment.placement": "deployment.moved",
              "ue.isolate": "ue.isolated", "ue.release": "ue.released"}


def problem(err: ActionError) -> JSONResponse:
    return JSONResponse(err.problem(), status_code=err.status, media_type="application/problem+json")


def initial_state(sc: dict) -> dict:
    return {
        "slices": {s["id"]: {"rate_mbps": s["bandwidth"]["rate_mbps"], "ceil_mbps": s["bandwidth"]["ceil_mbps"],
                             "active": True} for s in sc["slices"]},
        "links": {lk: {"delay_ms": 0, "jitter_ms": 0, "loss_pct": 0} for lk in sc["links"]},
        "deployments": {d: {"replicas": 1, "tier": "edge"} for d in sc.get("deployments", [])},
        "isolated_ues": [],
    }


def _view(state: dict, action: dict) -> dict:
    t, target = action["type"], action["target"]
    if t.startswith("slice."):
        return copy.deepcopy(state["slices"][target])
    if t == "link.netem":
        return copy.deepcopy(state["links"][target])
    if t.startswith("deployment."):
        return copy.deepcopy(state["deployments"][target])
    if t.startswith("ue."):
        return {"isolated": target in state["isolated_ues"]}
    return {}


def create_app(sc: dict | None = None, backend: str | None = None, ledger_url: str | None = None) -> FastAPI:
    sc = sc or scn.default()
    app = FastAPI(title="B6G Actionneur (I-04)", version=__version__)
    app.state.sc = sc
    app.state.state = initial_state(sc)
    app.state.backend = get_backend(backend or os.environ.get("B6G_ACTUATOR_BACKEND", "memory"), sc)
    try:
        app.state.backend.setup(app.state.state)
        app.state.setup_error = None
    except Exception as e:  # noqa: BLE001 - plateforme absente : l'API reste disponible, l'erreur est exposée
        app.state.setup_error = str(e)
    app.state.ledger_url = ledger_url if ledger_url is not None else os.environ.get("B6G_LEDGER_URL")
    app.state.outbox: list[dict] = []          # événements non encore remis au registre
    app.state.counter: Counter = Counter()     # b6g_actions_total{type,status}

    def emit(action: dict, result: dict, caller: str) -> None:
        payload = {"action_id": result["action_id"], "caller": caller, "type": action["type"],
                   "target": action["target"], "params": action["params"], "reason": action["reason"],
                   "previous": result["previous"], "current": result["current"]}
        evts = [events.make("actuator", "actuator.applied", payload)]
        if action["type"] in EVENT_TYPE:
            evts.append(events.make("actuator", EVENT_TYPE[action["type"]],
                                    {"target": action["target"], **action["params"]}))
        for e in evts:
            delivered = False
            if app.state.ledger_url:
                try:
                    r = httpx.post(f"{app.state.ledger_url.rstrip('/')}/v1/events", json=e,
                                   headers={"X-B6G-Caller": "actuator"}, timeout=5)
                    delivered = r.status_code == 200
                except httpx.HTTPError:
                    delivered = False
            if not delivered:
                app.state.outbox.append(e)

    def run(action: dict, dry_run: bool, caller: str) -> dict:
        bw = {k: {"rate_mbps": v["rate_mbps"], "ceil_mbps": v["ceil_mbps"]} for k, v in app.state.state["slices"].items()}
        check(action, sc, bw)
        previous = _view(app.state.state, action)
        if dry_run:
            sim = copy.deepcopy(app.state.state)
            app.state.backend.apply(action, sim)
            current, status = _view(sim, action), "dry_run"
            msg = "validé, rien appliqué (dry_run)"
        else:
            try:
                app.state.backend.apply(action, app.state.state)
            except Exception as e:  # noqa: BLE001
                app.state.counter[(action["type"], "failed")] += 1
                raise ActionError(503, "Échec du backend", str(e)) from e
            current, status = _view(app.state.state, action), "applied"
            msg = f"appliqué (backend={app.state.backend.name})"
        res = {"action_id": str(uuid.uuid4()), "status": status, "applied_at": now_iso(), "previous": previous,
               "current": current, "message": msg, "request": action}
        app.state.counter[(action["type"], status)] += 1
        if status == "applied":
            emit(action, res, caller)
        return res

    @app.get("/v1/health")
    def health():
        body = {"status": "ok", "version": __version__, "backend": app.state.backend.name}
        if app.state.setup_error:
            body["setup_error"] = app.state.setup_error
        return body

    @app.get("/v1/state")
    def state(x_b6g_caller: str | None = Header(None)):
        return app.state.state

    async def _body(request: Request):
        try:
            return await request.json()
        except ValueError:
            raise ActionError(400, "JSON invalide", "corps illisible") from None

    @app.post("/v1/actions")
    async def actions(request: Request, dry_run: bool = False, x_b6g_caller: str | None = Header(None)):
        try:
            if not x_b6g_caller:
                raise ActionError(400, "En-tête X-B6G-Caller manquant", "obligatoire (§ 6.2)")
            return run(await _body(request), dry_run, x_b6g_caller)
        except ActionError as e:
            return problem(e)

    @app.post("/v1/actions/batch")
    async def batch(request: Request, dry_run: bool = False, x_b6g_caller: str | None = Header(None)):
        try:
            if not x_b6g_caller:
                raise ActionError(400, "En-tête X-B6G-Caller manquant", "obligatoire (§ 6.2)")
            body = await _body(request)
            acts = body.get("actions") if isinstance(body, dict) else None
            if not isinstance(acts, list) or len(acts) > 10:
                raise ActionError(400, "Lot invalide", "actions : liste de 10 éléments au plus")
        except ActionError as e:
            return problem(e)
        results = []
        for a in acts:
            try:
                results.append(run(a, dry_run, x_b6g_caller))
            except ActionError as e:
                results.append({"action_id": str(uuid.uuid4()), "status": "rejected", "applied_at": now_iso(),
                                "previous": {}, "current": {}, "message": f"{e.status} {e.title} : {e.detail}"})
                break
        return {"results": results}

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics():
        lines = ["# TYPE b6g_actions_total counter"]
        for (t, s), n in sorted(app.state.counter.items()):
            lines.append(f'b6g_actions_total{{type="{t}",status="{s}"}} {n}')
        for sid, v in app.state.state["slices"].items():
            lines.append(f'b6g_slice_bw_limit_mbps{{slice="{sid}"}} {v["rate_mbps"]}')
        for lk, v in app.state.state["links"].items():
            lines.append(f'b6g_link_delay_ms{{link="{lk}"}} {v["delay_ms"]}')
        lines.extend(app.state.backend.metrics())
        return "\n".join(lines) + "\n"

    return app


app = create_app()
