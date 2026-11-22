"""Boucle autonome MAPE-K — Monitor (M10, T26.1) : observation de l'état du réseau.

Construit un MetricSnapshot (I-03) à partir de Prometheus (`b6g_common.snapshot.build`). Aucune action.
"""
from __future__ import annotations

from b6g_common import scenario as scn
from b6g_common import snapshot


class Monitor:
    def __init__(self, prom_url: str, window_s: int = 10, sc: dict | None = None):
        self.prom_url = prom_url
        self.window_s = window_s
        self.sc = sc or scn.default()

    def snapshot(self) -> dict:
        """État courant du réseau, conforme à metric-snapshot.schema.json."""
        return snapshot.build(self.prom_url, window_s=self.window_s, sc=self.sc)
