"""Boucle autonome MAPE-K — Decide (M10, T26.3) : décision par l'API Décision, validée par l'API Jumeau.

Appelle l'API Décision (I-05, `POST /v1/decide`) pour obtenir des actions à partir de l'instantané ; au plus 3, et
`noop` si pas de réponse en 2 s. Chaque action candidate est validée par l'API Jumeau (I-06, `POST /v1/whatif`) :
le jumeau joue un rôle de **sécurité** — une action n'est retenue que si elle **n'introduit aucune nouvelle violation
de SLA** (par exemple prélever trop de capacité sur une autre slice). Une action qui améliore la situation sans en
créer d'autre est appliquée, même si elle ne rétablit pas le SLA en une seule étape : la boucle converge en plusieurs
itérations. Jusqu'à INT5, Décision et Jumeau sont les mocks de l'équipe 2 (`mock_decision`, `mock_twin`).
"""
from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze import sla_violations  # noqa: E402


class Decider:
    def __init__(self, decision_url: str, twin_url: str, max_actions: int = 3, decide_timeout_s: float = 2.0,
                 client: httpx.Client | None = None):
        self.decision = decision_url.rstrip("/")
        self.twin = twin_url.rstrip("/")
        self.max_actions = max_actions
        self.decide_timeout = decide_timeout_s
        self.http = client or httpx.Client()

    def _decide(self, snap: dict, policy: str) -> dict:
        body = {"policy": policy, "snapshot": snap, "constraints": {"max_actions": self.max_actions}}
        r = self.http.post(f"{self.decision}/v1/decide", json=body, headers={"X-B6G-Caller": "loop"},
                           timeout=self.decide_timeout)
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _violation_keys(snap_slices: dict, sc: dict) -> set[tuple[str, str]]:
        return {(v["slice"], v["metric"]) for v in sla_violations({"slices": snap_slices}, sc)}

    def _whatif(self, snap: dict, action: dict) -> dict | None:
        try:
            r = self.http.post(f"{self.twin}/v1/whatif", json={"snapshot": snap, "actions": [action]},
                               headers={"X-B6G-Caller": "loop"}, timeout=5)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError:
            return None

    def _safe(self, snap: dict, action: dict, sc: dict) -> bool:
        """L'action n'introduit-elle aucune nouvelle violation de SLA selon le jumeau (rôle de sécurité) ?"""
        pred = self._whatif(snap, action)
        if pred is None:
            return False
        if pred.get("sla_ok"):
            return True
        before = self._violation_keys(snap["slices"], sc)
        after = {(v["slice"], v["metric"]) for v in pred.get("violations", [])}
        return not (after - before)   # aucune violation nouvelle (slice, indicateur) par rapport à l'état courant

    def decide(self, snap: dict, sc: dict, policy: str = "qos-tree") -> dict:
        """Renvoie {decision_id, actions (jugées sûres par le jumeau), rejected, source}. `noop` si pas de décision à temps."""
        try:
            decision = self._decide(snap, policy)
        except httpx.HTTPError:
            return {"decision_id": None, "actions": [], "rejected": [], "source": "noop (décision indisponible < 2 s)"}
        actions, rejected = [], []
        for a in decision.get("actions", [])[: self.max_actions]:
            (actions if self._safe(snap, a, sc) else rejected).append(a)
        return {"decision_id": decision.get("decision_id"), "actions": actions, "rejected": rejected,
                "source": decision.get("model_version", policy)}
