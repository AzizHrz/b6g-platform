"""Politique de sobriété énergétique (M09, T25.3) : met en veille les fonctions sous-utilisées par l'API Actionneur.

    .venv/bin/python platform/energy/green_policy.py [--once]      (make up-green / stop-green)

Toutes les `period` secondes, pour chaque cible de green_policy.yaml :
  - inactive (métrique < idle_below) depuis la période de garde -> mise en veille :
    deployment.replicas 0 (scale-to-zero) ou slice.state active=false ;
  - active (métrique > busy_above) alors qu'elle est en veille -> réveil (répliques=1 ou slice.state active=true).
Toute action passe par l'Actionneur (I-04). Décisions en JSON sur la sortie standard. Réalisme : ÉMULÉ.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx
import yaml
from b6g_common import now_iso

HERE = Path(__file__).resolve().parent


class GreenPolicy:
    def __init__(self, cfg: dict, prom: str, actuator: str, client: httpx.Client | None = None):
        self.cfg, self.prom, self.act = cfg, prom.rstrip("/"), actuator.rstrip("/")
        self.http = client or httpx.Client(timeout=40)
        self.asleep: dict[str, bool] = {}
        self.last_action: dict[str, float] = {}

    def _query(self, expr: str) -> float | None:
        r = self.http.get(f"{self.prom}/api/v1/query", params={"query": expr})
        res = r.json()["data"]["result"]
        return float(res[0]["value"][1]) if res else None

    def _act(self, type_: str, target: str, params: dict, reason: str) -> dict:
        body = {"type": type_, "target": target, "params": params, "reason": reason}
        return self.http.post(f"{self.act}/v1/actions", json=body, headers={"X-B6G-Caller": "green-policy"}).json()

    def decide(self, now: float) -> list[tuple[dict, str]]:
        """(ActionRequest, raison) à appliquer pour l'instant courant, sans effet de bord."""
        out = []
        for t in self.cfg["targets"]:
            key = t["name"]
            # Métrique absente = aucun trafic observé = inactif (le compteur de requêtes n'existe pas tant que
            # l'application n'a jamais été sollicitée) ; pour le réveil, une valeur absente n'est jamais « active »
            value = self._query(t["idle_metric"])
            value = 0.0 if value is None else value
            asleep = self.asleep.get(key, False)
            if now - self.last_action.get(key, 0) < self.cfg["cooldown_s"]:
                continue
            if not asleep and value < t["idle_below"]:
                action = ({"type": "deployment.replicas", "target": t["name"], "params": {"replicas": 0}}
                          if t["kind"] == "deployment"
                          else {"type": "slice.state", "target": t["name"], "params": {"active": False}})
                out.append(({**action, "reason": f"green-policy : {key} inactif ({value:.3f} < {t['idle_below']})"}, key))
            elif asleep and value > t["busy_above"]:
                action = ({"type": "deployment.replicas", "target": t["name"], "params": {"replicas": 1}}
                          if t["kind"] == "deployment"
                          else {"type": "slice.state", "target": t["name"], "params": {"active": True}})
                reason = f"green-policy : {key} de nouveau actif ({value:.3f} > {t['busy_above']})"
                out.append(({**action, "reason": reason}, key))
        return out

    def step(self) -> list[dict]:
        now = time.time()
        results = []
        for action, key in self.decide(now):
            res = self._act(action["type"], action["target"], action["params"], action["reason"])
            self.asleep[key] = action["params"].get("replicas") == 0 or action["params"].get("active") is False
            self.last_action[key] = now
            results.append({"ts": now_iso(), "target": key, "action": action["type"], "params": action["params"],
                            "status": res.get("status"), "reason": action["reason"]})
        return results

    def run(self, once: bool = False) -> None:
        while True:
            t0 = time.monotonic()
            try:
                for r in self.step():
                    print(json.dumps(r, ensure_ascii=False), flush=True)
            except httpx.HTTPError as e:
                print(json.dumps({"ts": now_iso(), "error": str(e)}), flush=True)
            if once:
                return
            time.sleep(max(0.0, self.cfg["period_s"] - (time.monotonic() - t0)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prom", default="http://127.0.0.1:9090")
    ap.add_argument("--actuator", default="http://127.0.0.1:8081")
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    cfg = yaml.safe_load((HERE / "green_policy.yaml").read_text(encoding="utf-8"))
    GreenPolicy(cfg, args.prom, args.actuator).run(args.once)


if __name__ == "__main__":
    main()
