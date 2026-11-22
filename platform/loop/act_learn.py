"""Boucle autonome MAPE-K — Act + Learn et orchestration (M10, T26.4).

Boucle Monitor → Analyze → Decide → Act → Learn, toutes les `period` secondes :
  - Monitor : instantané (I-03) ;
  - Analyze : violations de SLA ;
  - Decide : si violation, actions par l'API Décision validées par l'API Jumeau (`platform/loop/decide.py`) ;
  - Act : application par l'Actionneur (I-04) ;
  - Learn : mesure du SLA avant/après, ligne D8 (actions_log), événement `loop.iteration` (I-07),
    compteur `b6g_loop_iterations_total{outcome}` poussé à la Pushgateway.

    .venv/bin/python platform/loop/act_learn.py --iterations 10      (make up-loop)

Issue de chaque itération (`outcome`) : `resolved` (SLA rétabli), `rejected` (action refusée par le jumeau ou échec),
`no_action` (pas de violation). Réalisme : ÉMULÉ.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import httpx
from b6g_common import events, now_iso
from b6g_common import scenario as scn

HERE = Path(__file__).resolve().parent
import sys  # noqa: E402

sys.path.insert(0, str(HERE))
from analyze import sla_ok, sla_violations  # noqa: E402
from decide import Decider  # noqa: E402
from monitor import Monitor  # noqa: E402


class MapeK:
    def __init__(self, prom: str, actuator: str, decision: str, twin: str, ledger: str | None,
                 pushgateway: str | None, sc: dict, d8_path: Path, client: httpx.Client | None = None):
        self.monitor = Monitor(prom, sc=sc)
        self.decider = Decider(decision, twin)
        self.actuator = actuator.rstrip("/")
        self.ledger = ledger.rstrip("/") if ledger else None
        self.pushgateway = pushgateway.rstrip("/") if pushgateway else None
        self.sc = sc
        self.http = client or httpx.Client(timeout=10)
        self.d8_path = d8_path
        self.counts = {"resolved": 0, "rejected": 0, "no_action": 0}
        self._d8_header()

    def _d8_header(self) -> None:
        if not self.d8_path.exists():
            self.d8_path.parent.mkdir(parents=True, exist_ok=True)
            self.d8_path.write_text("ts,action_id,caller,type,target,params_json,status,decision_id,"
                                    "sla_ok_before,sla_ok_after\n", encoding="utf-8")

    def _apply(self, action: dict) -> dict:
        r = self.http.post(f"{self.actuator}/v1/actions", json=action, headers={"X-B6G-Caller": "loop"})
        return r.json()

    def _d8_row(self, res: dict, action: dict, decision_id: str | None, before: bool, after: bool) -> None:
        params = json.dumps(action.get("params", {}), ensure_ascii=False).replace('"', '""')
        self.d8_path.open("a", encoding="utf-8").write(
            f'{now_iso()},{res.get("action_id", "")},loop,{action["type"]},{action["target"]},'
            f'"{params}",{res.get("status", "failed")},{decision_id or ""},'
            f'{str(before).lower()},{str(after).lower()}\n')

    def _emit(self, outcome: str, decision_id: str | None, n_actions: int) -> None:
        if not self.ledger:
            return
        evt = events.make("loop", "loop.iteration",
                          {"outcome": outcome, "decision_id": decision_id, "actions": n_actions})
        try:
            self.http.post(f"{self.ledger}/v1/events", content=json.dumps(evt, ensure_ascii=False).encode(),
                           headers={"X-B6G-Caller": "loop", "Content-Type": "application/json"}, timeout=30)
        except httpx.HTTPError:
            pass

    def _push_counter(self) -> None:
        if not self.pushgateway:
            return
        body = "# TYPE b6g_loop_iterations_total counter\n" + "".join(
            f'b6g_loop_iterations_total{{outcome="{o}"}} {n}\n' for o, n in self.counts.items())
        try:
            self.http.put(f"{self.pushgateway}/metrics/job/loop", content=body.encode(), timeout=5)
        except httpx.HTTPError:
            pass

    def iteration(self) -> dict:
        snap = self.monitor.snapshot()
        violations = sla_violations(snap, self.sc)
        before = not violations
        if before:
            self.counts["no_action"] += 1
            self._emit("no_action", None, 0)
            self._push_counter()
            return {"ts": now_iso(), "outcome": "no_action", "violations": 0, "actions": 0, "decision_id": None}
        decision = self.decider.decide(snap, self.sc)
        applied = []
        for action in decision["actions"]:
            res = self._apply(action)
            applied.append(res.get("status"))
            self._d8_row(res, action, decision["decision_id"], before, False)
        time.sleep(8)   # laisser l'effet se propager (chaîne de mesure ≈ fenêtre de collecte)
        after = sla_ok(self.monitor.snapshot(), self.sc)
        outcome = "resolved" if after else "rejected"
        if not decision["actions"]:
            outcome = "rejected"
        self.counts[outcome] += 1
        self._emit(outcome, decision["decision_id"], len(decision["actions"]))
        self._push_counter()
        return {"ts": now_iso(), "outcome": outcome, "violations": len(violations), "actions": len(decision["actions"]),
                "decision_id": decision["decision_id"], "rejected": len(decision["rejected"]),
                "sla_ok_before": before, "sla_ok_after": after, "statuts": applied}

    def run(self, iterations: int, period: float = 5) -> list[dict]:
        rows = []
        for _ in range(iterations):
            t0 = time.monotonic()
            try:
                row = self.iteration()
            except httpx.HTTPError as e:
                row = {"ts": now_iso(), "outcome": "error", "error": str(e)}
            rows.append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            time.sleep(max(0.0, period - (time.monotonic() - t0)))
        return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prom", default="http://127.0.0.1:9090")
    ap.add_argument("--actuator", default="http://127.0.0.1:8081")
    ap.add_argument("--decision", default="http://127.0.0.1:8090")
    ap.add_argument("--twin", default="http://127.0.0.1:8091")
    ap.add_argument("--ledger", default="http://127.0.0.1:8082")
    ap.add_argument("--pushgateway", default="http://127.0.0.1:9091")
    ap.add_argument("--iterations", type=int, default=10)
    ap.add_argument("--d8", default=str(HERE.parents[1] / "datasets" / "raw" / "actions_log.csv"))
    args = ap.parse_args()
    loop = MapeK(args.prom, args.actuator, args.decision, args.twin, args.ledger, args.pushgateway,
                 scn.load(), Path(args.d8))
    loop.run(args.iterations)
    print("compteurs:", loop.counts, flush=True)


if __name__ == "__main__":
    main()
