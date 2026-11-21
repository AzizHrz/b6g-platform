"""Backends d'application des actions.

- MemoryBackend (INT0) : met à jour l'état en mémoire, n'exécute aucune commande système.
- TcBackend (Actionneur v1 à INT1, v2 à INT3) : actions appliquées sur la plateforme réelle.
    * slice.bandwidth : classe HTB 1:10 (rate / ceil) en sortie de ogstun, policer en entrée plafonné à ceil ;
    * slice.state, link.netem, deployment.*, ue.* (v2) : voir la docstring de la classe.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path

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
    """Actionneur v2 sur la plateforme réelle (nom de backend « tc », conservé depuis la v1).

    - slice.bandwidth : HTB / policer dans l'UPF de la slice (v1) ;
    - slice.state : arrêt / redémarrage de smf-<slice> et upf-<slice> (docker), limitation réappliquée ;
    - link.netem : netem sur le lien : tier-<niveau> = sortie du nœud k3d du niveau (conteneur d'appoint dans son
      espace réseau, l'image k3s n'ayant pas tc) ; n6-<slice> = file de la classe HTB de la slice (sens descendant) ;
      n2n3-gnb1 = sortie du gNB ; {} supprime le netem ;
    - deployment.replicas / deployment.placement : kubectl scale / nodeSelector b6g/tier ;
    - ue.isolate / ue.release : filtres tc de rejet de l'adresse IP de l'UE dans son UPF (descendant et montant).
    """

    name = "tc"
    SUPPORTED = {"slice.bandwidth", "slice.state", "link.netem", "deployment.replicas", "deployment.placement",
                 "ue.isolate", "ue.release", "noop"}
    POLICE_PRIO = "100"          # policer montant : après les filtres d'isolement des UEs (prio 1 à 30)
    HELPER_IMAGE = "gradiant/open5gs:2.7.7"   # image disposant de tc, pour les nœuds k3d

    def __init__(self, sc: dict, runner=None, host=None):
        self.sc = sc
        self.upf = {s["id"]: s["upf"] for s in sc["slices"]}
        self.smf = {s["id"]: s["smf"] for s in sc["slices"]}
        self.run = runner or self._docker_exec
        self.host = host or self._host
        self.kubectl = os.environ.get("B6G_KUBECTL", str(Path.home() / "b6g-ext" / "bin" / "kubectl"))
        self.timers: dict[str, threading.Timer] = {}

    @staticmethod
    def _docker_exec(container: str, *cmd: str) -> str:
        res = subprocess.run(["docker", "exec", "-u", "0", container, *cmd], capture_output=True, text=True, timeout=10)
        if res.returncode != 0:
            raise RuntimeError(f"{container}: {' '.join(cmd)} -> {res.stderr.strip() or res.returncode}")
        return res.stdout

    @staticmethod
    def _host(*cmd: str) -> str:
        res = subprocess.run(list(cmd), capture_output=True, text=True, timeout=60)
        if res.returncode != 0:
            raise RuntimeError(f"{' '.join(cmd[:4])} … -> {res.stderr.strip()[-300:] or res.returncode}")
        return res.stdout

    # ---- link.netem -------------------------------------------------------------------------------------------
    @staticmethod
    def _netem_args(p: dict) -> list[str]:
        args = ["netem", "delay", f"{p.get('delay_ms', 0)}ms"]
        if p.get("jitter_ms"):
            args.append(f"{p['jitter_ms']}ms")
        if p.get("loss_pct"):
            args += ["loss", f"{p['loss_pct']}%"]
        return args

    def _netem(self, link: str, p: dict) -> None:
        clear = not p
        if link.startswith("tier-") or link == "n2n3-gnb1":
            # Nœud k3d (pas de tc dans l'image) ou gNB (conteneur sans NET_ADMIN) : conteneur d'appoint dans son espace réseau
            node = "gnb" if link == "n2n3-gnb1" else self.sc["tiers"][link.removeprefix("tier-")]["k8s_node"]
            tc = (["tc", "qdisc", "del", "dev", "eth0", "root"] if clear
                  else ["tc", "qdisc", "replace", "dev", "eth0", "root", *self._netem_args(p)])
            try:
                self.host("docker", "run", "--rm", "--net", f"container:{node}", "--cap-add", "NET_ADMIN", "-u", "0",
                          "--entrypoint", "tc", self.HELPER_IMAGE, *tc[1:])
            except RuntimeError as e:
                if not (clear and "No such file" in str(e) or clear and "Cannot delete" in str(e)):
                    raise
        else:  # n6-<slice> : file de la classe HTB de la slice dans son UPF (sens descendant)
            c = self.upf[link.removeprefix("n6-")]
            if clear:
                self.run(c, "sh", "-c", f"tc qdisc del dev {TUN} parent 1:10 2>/dev/null; true")
            else:
                self.run(c, "tc", "qdisc", "replace", "dev", TUN, "parent", "1:10", "handle", "10:", *self._netem_args(p))

    # ---- deployment.* -----------------------------------------------------------------------------------------
    def _namespace(self, deployment: str) -> str:
        out = self.host(self.kubectl, "get", "deploy", "-A", "--field-selector", f"metadata.name={deployment}",
                        "-o", "jsonpath={.items[0].metadata.namespace}")
        if not out.strip():
            raise RuntimeError(f"déploiement {deployment} absent du cluster")
        return out.strip()

    # ---- ue.* -------------------------------------------------------------------------------------------------
    def _ue(self, ue_id: str) -> tuple[str, str, int]:
        """(slice, adresse IP, priorité de filtre) d'un UE « ue-<slice>-<nn> »."""
        sid, nn = ue_id.removeprefix("ue-").rsplit("-", 1)
        out = self.run(f"ue-{sid}", "ip", "-o", "-4", "addr", "show", f"uesimtun{int(nn) - 1}")
        ip = out.split("inet ")[1].split("/")[0]
        index = [s["id"] for s in self.sc["slices"]].index(sid) * self.sc["ues"]["count_per_slice"] + int(nn)
        return sid, ip, index

    def _isolate(self, ue_id: str, on: bool) -> None:
        sid, ip, prio = self._ue(ue_id)
        c = self.upf[sid]
        for parent, field in (("1:", "dst"), ("ffff:", "src")):
            self.run(c, "sh", "-c", f"tc filter del dev {TUN} parent {parent} prio {prio} 2>/dev/null; true")
            if on:
                self.run(c, "tc", "filter", "add", "dev", TUN, "parent", parent, "protocol", "ip", "prio", str(prio),
                         "u32", "match", "ip", field, f"{ip}/32", "action", "drop")

    # ---- slice.state ------------------------------------------------------------------------------------------
    def _slice_state(self, sid: str, active: bool, state: dict) -> None:
        if not active:
            self.host("docker", "stop", self.smf[sid], self.upf[sid])
            return
        self.host("docker", "start", self.upf[sid])
        self.host("docker", "start", self.smf[sid])
        cur = state["slices"][sid]
        self._shape(sid, cur["rate_mbps"], cur["ceil_mbps"])

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
        # Seul le policer est remplacé : les filtres d'isolement d'UE (prio 1 à 30) sont conservés
        self.run(c, "sh", "-c", f"tc filter del dev {TUN} parent ffff: prio {self.POLICE_PRIO} 2>/dev/null; true")
        self.run(c, "tc", "filter", "add", "dev", TUN, "parent", "ffff:", "protocol", "ip", "prio", self.POLICE_PRIO,
                 "u32", "match", "u32", "0", "0", "police", "rate", f"{ceil}mbit", "burst", "256k", "drop",
                 "flowid", ":1")

    def setup(self, state: dict) -> None:
        """Applique l'état initial du scénario (rate / ceil de chaque slice)."""
        for sid, v in state["slices"].items():
            self._shape(sid, v["rate_mbps"], v["ceil_mbps"])

    def apply(self, action: dict, state: dict) -> None:
        t, target, p = action["type"], action["target"], action["params"]
        if t not in self.SUPPORTED:
            raise RuntimeError(f"{t} : type non pris en charge")
        if t == "slice.bandwidth":
            cur = state["slices"][target]
            ceil = p.get("ceil_mbps", max(p["rate_mbps"], cur["ceil_mbps"]))
            self._shape(target, p["rate_mbps"], ceil)
        elif t == "slice.state":
            self._slice_state(target, p["active"], state)
        elif t == "link.netem":
            self._netem(target, p)
        elif t == "deployment.replicas":
            self.host(self.kubectl, "-n", self._namespace(target), "scale", "deploy", target, f"--replicas={p['replicas']}")
        elif t == "deployment.placement":
            patch = json.dumps({"spec": {"template": {"spec": {"nodeSelector": {"b6g/tier": p["tier"]}}}}})
            self.host(self.kubectl, "-n", self._namespace(target), "patch", "deploy", target, "--type=strategic",
                      "-p", patch)
        elif t in ("ue.isolate", "ue.release"):
            self._isolate(target, t == "ue.isolate")
            old = self.timers.pop(target, None)
            if old:
                old.cancel()
            if t == "ue.isolate" and p.get("duration_s"):
                # Libération automatique à l'échéance (état mis à jour par le même chemin que ue.release)
                timer = threading.Timer(p["duration_s"], self._auto_release, args=(target, state))
                timer.daemon = True
                self.timers[target] = timer
                timer.start()
        super().apply(action, state)

    def _auto_release(self, ue_id: str, state: dict) -> None:
        self._isolate(ue_id, False)
        if ue_id in state["isolated_ues"]:
            state["isolated_ues"].remove(ue_id)
        self.timers.pop(ue_id, None)

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
