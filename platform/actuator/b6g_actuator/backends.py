"""Backends d'application des actions.

- MemoryBackend (INT0) : met à jour l'état en mémoire, n'exécute aucune commande système.
- TcBackend (INT1, Actionneur v1) : `slice.bandwidth` appliqué par tc dans le conteneur UPF de la slice.
    * sens descendant : classe HTB 1:10 (rate / ceil) en sortie de ogstun ;
    * sens montant : policer en entrée de ogstun, plafonné à ceil (pas de file HTB possible en entrée).
  Les autres types (link.netem, deployment.*, ue.*, slice.state) arrivent avec l'Actionneur v2 (INT3) :
  ils sont refusés explicitement au lieu d'être simulés.
"""
from __future__ import annotations

import subprocess

TUN = "ogstun"


class MemoryBackend:
    name = "memory"

    def setup(self, state: dict) -> None:  # rien à préparer
        return None

    def metrics(self) -> list[str]:
        return []

    def apply(self, action: dict, state: dict) -> None:  # noqa: D401 - modifie `state` sur place
        t, target, p = action["type"], action["target"], action["params"]
        if t == "slice.bandwidth":
            cur = state["slices"][target]
            cur["rate_mbps"] = p["rate_mbps"]
            cur["ceil_mbps"] = p.get("ceil_mbps", max(p["rate_mbps"], cur["ceil_mbps"]))
        elif t == "slice.state":
            state["slices"][target]["active"] = p["active"]
        elif t == "link.netem":
            state["links"][target] = {"delay_ms": p.get("delay_ms", 0), "jitter_ms": p.get("jitter_ms", 0),
                                      "loss_pct": p.get("loss_pct", 0)}
        elif t == "deployment.replicas":
            state["deployments"][target]["replicas"] = p["replicas"]
        elif t == "deployment.placement":
            state["deployments"][target]["tier"] = p["tier"]
        elif t == "ue.isolate":
            if target not in state["isolated_ues"]:
                state["isolated_ues"].append(target)
        elif t == "ue.release":
            if target in state["isolated_ues"]:
                state["isolated_ues"].remove(target)


class TcBackend(MemoryBackend):
    """Actionneur v1 : tc HTB / policer dans les conteneurs UPF (docker exec)."""

    name = "tc"
    SUPPORTED = {"slice.bandwidth", "noop"}

    def __init__(self, sc: dict, runner=None):
        self.upf = {s["id"]: s["upf"] for s in sc["slices"]}
        self.run = runner or self._docker_exec

    @staticmethod
    def _docker_exec(container: str, *cmd: str) -> str:
        res = subprocess.run(["docker", "exec", "-u", "0", container, *cmd], capture_output=True, text=True, timeout=10)
        if res.returncode != 0:
            raise RuntimeError(f"{container}: {' '.join(cmd)} -> {res.stderr.strip() or res.returncode}")
        return res.stdout

    def _shape(self, slice_id: str, rate: float, ceil: float) -> None:
        c = self.upf[slice_id]
        # « qdisc replace » échoue sur une racine HTB existante : la créer seulement si elle manque
        if "htb 1:" not in self.run(c, "tc", "qdisc", "show", "dev", TUN):
            self.run(c, "tc", "qdisc", "add", "dev", TUN, "root", "handle", "1:", "htb", "default", "10")
        # Classe parente 1:1 au plafond, classe de la slice 1:10 garantie à rate et empruntant jusqu'à ceil
        self.run(c, "tc", "class", "replace", "dev", TUN, "parent", "1:", "classid", "1:1", "htb",
                 "rate", f"{ceil}mbit", "ceil", f"{ceil}mbit")
        self.run(c, "tc", "class", "replace", "dev", TUN, "parent", "1:1", "classid", "1:10", "htb",
                 "rate", f"{rate}mbit", "ceil", f"{ceil}mbit")
        self.run(c, "tc", "qdisc", "replace", "dev", TUN, "ingress")
        self.run(c, "sh", "-c", f"tc filter del dev {TUN} parent ffff: 2>/dev/null; true")
        self.run(c, "tc", "filter", "add", "dev", TUN, "parent", "ffff:", "protocol", "ip", "prio", "1", "u32",
                 "match", "u32", "0", "0", "police", "rate", f"{ceil}mbit", "burst", "256k", "drop", "flowid", ":1")

    def setup(self, state: dict) -> None:
        """Applique l'état initial du scénario (rate / ceil de chaque slice)."""
        for sid, v in state["slices"].items():
            self._shape(sid, v["rate_mbps"], v["ceil_mbps"])

    def apply(self, action: dict, state: dict) -> None:
        t, target, p = action["type"], action["target"], action["params"]
        if t not in self.SUPPORTED:
            raise RuntimeError(f"{t} : non disponible dans l'Actionneur v1 (prévu en v2, INT3)")
        if t == "slice.bandwidth":
            cur = state["slices"][target]
            ceil = p.get("ceil_mbps", max(p["rate_mbps"], cur["ceil_mbps"]))
            self._shape(target, p["rate_mbps"], ceil)
        super().apply(action, state)

    def metrics(self) -> list[str]:
        """Compteurs d'octets de ogstun par slice : tx = descendant (vers les UEs), rx = montant."""
        lines = ["# TYPE b6g_slice_tun_bytes_total counter"]
        for sid, c in self.upf.items():
            try:
                out = self.run(c, "cat", f"/sys/class/net/{TUN}/statistics/tx_bytes",
                               f"/sys/class/net/{TUN}/statistics/rx_bytes").split()
            except (RuntimeError, subprocess.TimeoutExpired):
                continue
            if len(out) == 2:
                lines.append(f'b6g_slice_tun_bytes_total{{slice="{sid}",direction="dl"}} {out[0]}')
                lines.append(f'b6g_slice_tun_bytes_total{{slice="{sid}",direction="ul"}} {out[1]}')
        return lines


def get_backend(name: str, sc: dict | None = None):
    if name == "memory":
        return MemoryBackend()
    if name == "tc":
        if sc is None:
            raise ValueError("le backend tc a besoin du scénario")
        return TcBackend(sc)
    raise ValueError(f"Backend inconnu : {name} (memory | tc)")
