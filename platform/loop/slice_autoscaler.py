"""slice-autoscaler (M10 v0, T06.4) : règle à seuils, boucle de 5 s, actions par l'API Actionneur uniquement.

Toutes les `period` secondes :
  1. lit l'état réseau par b6g_common.snapshot.build() (I-03) et les plafonds courants par GET /v1/state (I-04) ;
  2. une slice est **congestionnée** si sa latence p95 dépasse son SLA (`sla.latency_ms_p95_max`) ou si son débit
     atteint `busy_ratio` × ceil ;
  3. pour une slice congestionnée hors période de garde : ceil × `step` (borné par la capacité totale) et rate
     relevé dans la capacité restante (somme des rate ≤ capacity.total_rate_mbps_max) ;
  4. une slice relevée dont le débit retombe sous `idle_ratio` × rate initial revient aux valeurs du scénario.

    .venv/bin/python platform/loop/slice_autoscaler.py [--period 5] [--once]

Chaque décision est écrite en JSON sur la sortie standard (journal .run/autoscaler.log avec make up-autoscaler).
"""
from __future__ import annotations

import argparse
import json
import time

import httpx
from b6g_common import now_iso, snapshot
from b6g_common import scenario as scn


class SliceAutoscaler:
    def __init__(self, sc: dict, prom: str, actuator: str, window_s: int = 10, busy_ratio: float = 0.9,
                 idle_ratio: float = 0.3, step: float = 1.5, cooldown_s: float = 10, client: httpx.Client | None = None):
        self.sc, self.prom, self.act = sc, prom, actuator.rstrip("/")
        self.window_s, self.busy, self.idle, self.step, self.cooldown = window_s, busy_ratio, idle_ratio, step, cooldown_s
        self.cap = sc["capacity"]["total_rate_mbps_max"]
        self.init = {s["id"]: dict(s["bandwidth"]) for s in sc["slices"]}
        self.sla = {s["id"]: s["sla"] for s in sc["slices"]}
        self.last_action: dict[str, float] = {}
        self.http = client or httpx.Client(timeout=5)

    def _state(self) -> dict[str, dict]:
        return self.http.get(f"{self.act}/v1/state", headers={"X-B6G-Caller": "slice-autoscaler"}).json()["slices"]

    def _apply(self, slice_id: str, rate: float, ceil: float, reason: str) -> dict:
        body = {"type": "slice.bandwidth", "target": slice_id, "params": {"rate_mbps": rate, "ceil_mbps": ceil},
                "reason": reason}
        return self.http.post(f"{self.act}/v1/actions", json=body, headers={"X-B6G-Caller": "slice-autoscaler"}).json()

    def decide(self, snap: dict, state: dict[str, dict], now: float) -> list[tuple[str, float, float, str]]:
        """Décisions (slice, rate, ceil, raison) pour un instantané et un état d'Actionneur donnés."""
        out = []
        rates = {k: v["rate_mbps"] for k, v in state.items()}
        for sid, m in snap["slices"].items():
            cur = state[sid]
            lat, thr = m["latency_ms_p95"], m["throughput_mbps"]
            sla_lat = self.sla[sid]["latency_ms_p95_max"]
            causes = []
            if lat is not None and lat > sla_lat:
                causes.append(f"latence p95 {lat:.1f} ms > SLA {sla_lat} ms")
            if thr is not None and thr >= self.busy * cur["ceil_mbps"]:
                causes.append(f"débit {thr:.1f} Mbit/s ≥ {self.busy:.0%} du plafond {cur['ceil_mbps']}")
            if causes:
                if now - self.last_action.get(sid, 0) < self.cooldown:
                    continue
                others = sum(r for k, r in rates.items() if k != sid)
                ceil = round(min(self.cap, cur["ceil_mbps"] * self.step), 1)
                rate = round(min(ceil, max(cur["rate_mbps"], cur["rate_mbps"] * self.step), self.cap - others), 1)
                if ceil <= cur["ceil_mbps"] and rate <= cur["rate_mbps"]:
                    continue  # déjà au maximum possible
                out.append((sid, rate, ceil, "slice-autoscaler : " + " ; ".join(causes)))
                rates[sid] = rate
            elif (thr is not None and cur["rate_mbps"] > self.init[sid]["rate_mbps"]
                  and thr < self.idle * self.init[sid]["rate_mbps"]
                  and now - self.last_action.get(sid, 0) >= self.cooldown):
                ini = self.init[sid]
                out.append((sid, ini["rate_mbps"], ini["ceil_mbps"],
                            f"slice-autoscaler : charge retombée ({thr:.2f} Mbit/s), retour aux valeurs du scénario"))
                rates[sid] = ini["rate_mbps"]
        return out

    def step_once(self) -> list[dict]:
        snap = snapshot.build(self.prom, window_s=self.window_s, sc=self.sc)
        now = time.time()
        results = []
        for sid, rate, ceil, reason in self.decide(snap, self._state(), now):
            res = self._apply(sid, rate, ceil, reason)
            self.last_action[sid] = now
            results.append({"ts": now_iso(), "slice": sid, "rate_mbps": rate, "ceil_mbps": ceil, "reason": reason,
                            "status": res.get("status"), "previous": res.get("previous")})
        return results

    def run(self, period: float = 5, once: bool = False) -> None:
        while True:
            t0 = time.monotonic()
            try:
                for r in self.step_once():
                    print(json.dumps(r, ensure_ascii=False), flush=True)
            except httpx.HTTPError as e:
                print(json.dumps({"ts": now_iso(), "error": str(e)}), flush=True)
            if once:
                return
            time.sleep(max(0.0, period - (time.monotonic() - t0)))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prom", default="http://127.0.0.1:9090")
    ap.add_argument("--actuator", default="http://127.0.0.1:8081")
    ap.add_argument("--period", type=float, default=5)
    ap.add_argument("--window", type=int, default=10)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()
    SliceAutoscaler(scn.load(), args.prom, args.actuator, window_s=args.window).run(args.period, args.once)


if __name__ == "__main__":
    main()
