"""Exporteur de consommation énergétique (M09, T25.2). Réalisme : SIMULÉ.

Toutes les `period` secondes, lit la charge CPU de chaque composant (`b6g_nf_cpu_ratio`, I-02) dans Prometheus et
calcule une puissance P = P_idle + (P_max - P_idle) × charge (platform/energy/power_model.yaml), puis intègre l'énergie.
Publie les métriques I-02 :
    b6g_energy_power_watts{component}     (gauge)
    b6g_energy_joules_total{component}    (counter, cumulé depuis le démarrage)

    uvicorn energy_exporter:app --port 9105      (make up-energy)
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import httpx
import yaml
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

HERE = Path(__file__).resolve().parent
PROM = os.environ.get("B6G_PROM_URL", "http://127.0.0.1:9090")


def load_model(path: Path | None = None) -> dict:
    return yaml.safe_load((path or HERE / "power_model.yaml").read_text(encoding="utf-8"))


def power_params(component: str, model: dict) -> tuple[float, float]:
    for prefix, p in model.get("classes", {}).items():
        if component == prefix or component.startswith(prefix):
            return p["p_idle_w"], p["p_max_w"]
    d = model["default"]
    return d["p_idle_w"], d["p_max_w"]


def cpu_by_component(prom: str, client: httpx.Client) -> dict[str, float]:
    r = client.get(f"{prom}/api/v1/query", params={"query": "b6g_nf_cpu_ratio"}, timeout=5)
    r.raise_for_status()
    out = {}
    for item in r.json()["data"]["result"]:
        nf = item["metric"].get("nf")
        if nf:
            out[nf] = max(0.0, min(float(item["value"][1]), 1.0))
    return out


class EnergyModel:
    def __init__(self, model: dict, prom: str = PROM):
        self.model, self.prom = model, prom
        self.power: dict[str, float] = {}
        self.joules: dict[str, float] = {}
        self.lock = threading.Lock()
        self.last = time.monotonic()

    def step(self, client: httpx.Client) -> None:
        now = time.monotonic()
        dt = now - self.last
        self.last = now
        cpu = cpu_by_component(self.prom, client)
        with self.lock:
            # Un composant qui ne publie plus de CPU est arrêté (mis en veille) : puissance nulle, énergie figée
            for comp in list(self.power):
                if comp not in cpu:
                    self.power[comp] = 0.0
            for comp, load in cpu.items():
                p_idle, p_max = power_params(comp, self.model)
                watts = p_idle + (p_max - p_idle) * load
                self.power[comp] = watts
                self.joules[comp] = self.joules.get(comp, 0.0) + watts * dt

    def exposition(self) -> str:
        with self.lock:
            lines = ["# TYPE b6g_energy_power_watts gauge"]
            lines += [f'b6g_energy_power_watts{{component="{c}"}} {w:.3f}' for c, w in sorted(self.power.items())]
            lines.append("# TYPE b6g_energy_joules_total counter")
            lines += [f'b6g_energy_joules_total{{component="{c}"}} {j:.3f}' for c, j in sorted(self.joules.items())]
            total = sum(self.power.values())
            lines += ["# TYPE b6g_energy_total_power_watts gauge", f"b6g_energy_total_power_watts {total:.3f}"]
        return "\n".join(lines) + "\n"


def create_app(period: float = 5, prom: str = PROM, model: dict | None = None) -> FastAPI:
    app = FastAPI(title="B6G exporteur énergie (M09)", version="1.0.0")
    app.state.model = EnergyModel(model or load_model(), prom)

    def loop() -> None:
        with httpx.Client() as c:
            while True:
                try:
                    app.state.model.step(c)
                except httpx.HTTPError:
                    pass
                time.sleep(period)

    threading.Thread(target=loop, daemon=True, name="energy").start()

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        return app.state.model.exposition()

    @app.get("/v1/health")
    def health() -> dict:
        return {"status": "ok", "components": len(app.state.model.power)}

    return app


app = create_app()
