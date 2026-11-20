"""Backends d'application des actions.

- MemoryBackend (INT0) : met à jour l'état en mémoire, n'exécute aucune commande système.
- TcBackend (INT1, à écrire en T06.x) : tc HTB / netem dans les conteneurs UPF, kubectl pour k3d.
"""
from __future__ import annotations


class MemoryBackend:
    name = "memory"

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


def get_backend(name: str):
    if name == "memory":
        return MemoryBackend()
    raise ValueError(f"Backend inconnu ou pas encore écrit : {name} (INT0 : memory)")
