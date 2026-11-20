"""I-08 : événements b6g.event.v1 et empreinte SHA-256 du JSON canonique."""
from __future__ import annotations

import hashlib
import json
import uuid

from .schemas import validate
from .timeutil import now_iso


def canonical_json(obj) -> str:
    """JSON canonique : clés triées, sans espaces, UTF-8."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(obj) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def make(source: str, type_: str, payload: dict, severity: str = "info", ts: str | None = None) -> dict:
    evt = {"schema": "b6g.event.v1", "event_id": str(uuid.uuid4()), "ts": ts or now_iso(), "source": source,
           "type": type_, "severity": severity, "payload": payload, "payload_sha256": sha256_hex(payload)}
    return validate(evt, "event")


def payload_ok(evt: dict) -> bool:
    return sha256_hex(evt.get("payload", {})) == evt.get("payload_sha256")
