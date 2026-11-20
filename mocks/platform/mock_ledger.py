"""Mock I-07 : registre d'événements sur un journal JSONL chaîné par SHA-256 (MAQUETTE de Hyperledger Fabric).

Chaque bloc contient un événement b6g.event.v1 : tx_id = SHA-256(prev_tx_id + JSON canonique de l'événement).
Les endossements Org1MSP/Org2MSP sont représentés, pas calculés (étiquette MAQUETTE).

    B6G_LEDGER_FILE=data/ledger.jsonl uvicorn mocks.platform.mock_ledger:app --port 8082
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from b6g_common import errors
from b6g_common.events import canonical_json, payload_ok
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

GENESIS = "0" * 64
ENDORSERS = ["Org1MSP", "Org2MSP"]


def problem(status: int, title: str, detail: str = "") -> JSONResponse:
    return JSONResponse({"type": f"https://b6g.local/problems/{status}", "title": title, "status": status,
                         "detail": detail}, status_code=status, media_type="application/problem+json")


class ChainedLedger:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.blocks: list[dict] = []
        self.index: dict[str, int] = {}
        if self.path and self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    b = json.loads(line)
                    self.index[b["event"]["event_id"]] = len(self.blocks)
                    self.blocks.append(b)

    @staticmethod
    def tx_hash(prev: str, event: dict) -> str:
        return hashlib.sha256((prev + canonical_json(event)).encode("utf-8")).hexdigest()

    def append(self, event: dict, caller: str) -> dict:
        prev = self.blocks[-1]["tx_id"] if self.blocks else GENESIS
        block = {"block_number": len(self.blocks), "prev_tx_id": prev, "tx_id": self.tx_hash(prev, event),
                 "caller": caller, "event": event}
        self.blocks.append(block)
        self.index[event["event_id"]] = block["block_number"]
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(block, ensure_ascii=False) + "\n")
        return block

    def chain_ok(self, upto: int | None = None) -> bool:
        prev = GENESIS
        for b in self.blocks[: (upto + 1) if upto is not None else None]:
            if b["prev_tx_id"] != prev or self.tx_hash(prev, b["event"]) != b["tx_id"]:
                return False
            prev = b["tx_id"]
        return True


def create_app(path: str | None = None) -> FastAPI:
    app = FastAPI(title="B6G mock_ledger (I-07, MAQUETTE)", version="1.0.0")
    led = ChainedLedger(path if path is not None else os.environ.get("B6G_LEDGER_FILE"))
    app.state.ledger = led

    @app.get("/v1/health")
    def health():
        return {"status": "ok", "backend": "chained-sha256", "blocks": len(led.blocks)}

    @app.post("/v1/events")
    async def post_event(request: Request, x_b6g_caller: str | None = Header(None)):
        if not x_b6g_caller:
            return problem(400, "En-tête X-B6G-Caller manquant")
        try:
            evt = await request.json()
        except ValueError:
            return problem(400, "JSON invalide")
        errs = errors(evt, "event")
        if errs:
            return problem(400, "Événement invalide", " ; ".join(errs[:5]))
        if not payload_ok(evt):
            return problem(400, "payload_sha256 ne correspond pas au payload")
        if evt["event_id"] in led.index:
            return problem(409, "event_id déjà inscrit", evt["event_id"])
        b = led.append(evt, x_b6g_caller)
        return {"event_id": evt["event_id"], "tx_id": b["tx_id"], "block_number": b["block_number"],
                "status": "committed"}

    @app.get("/v1/events")
    def list_events(type: str | None = None, since: str | None = None, limit: int = 100):
        items = [dict(b["event"], tx_id=b["tx_id"], block_number=b["block_number"]) for b in led.blocks
                 if (type is None or b["event"]["type"] == type) and (since is None or b["event"]["ts"] >= since)]
        return {"items": items[-max(1, min(limit, 1000)):], "total": len(items)}

    @app.get("/v1/events/{event_id}")
    def get_event(event_id: str):
        if event_id not in led.index:
            return problem(404, "Événement inconnu", event_id)
        b = led.blocks[led.index[event_id]]
        return dict(b["event"], tx_id=b["tx_id"], block_number=b["block_number"])

    @app.get("/v1/verify/{event_id}")
    def verify(event_id: str):
        if event_id not in led.index:
            return problem(404, "Événement inconnu", event_id)
        n = led.index[event_id]
        b = led.blocks[n]
        ok_chain = led.chain_ok(n)
        return {"hash_match": payload_ok(b["event"]) and ok_chain, "chain_ok": ok_chain,
                "endorsements": ENDORSERS, "block_number": n}

    return app


app = create_app()
