"""Kubeconfig restreint de l'équipe 2 (M06, INT3) : jeton du compte b6g-equipe2 (droits limités à b6g-edge|fog|cloud).

    .venv/bin/python platform/k8s/team2_kubeconfig.py [--server https://b6g-plat:6443] [--days 30]   (make k8s-team2-kubeconfig)

Écrit platform/k8s/generated/kubeconfig-equipe2 (non versionné, droits 600), à transmettre hors Git.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
KUBECTL = str(Path.home() / "b6g-ext" / "bin" / "kubectl")


def kubectl(*args: str) -> str:
    return subprocess.run([KUBECTL, *args], capture_output=True, text=True, check=True).stdout


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default="https://b6g-plat:6443")
    ap.add_argument("--days", type=int, default=30)
    args = ap.parse_args()
    kubectl("apply", "-f", str(ROOT / "platform" / "k8s" / "namespaces.yaml"))
    kubectl("apply", "-f", str(ROOT / "platform" / "k8s" / "team2-access.yaml"))
    token = kubectl("-n", "b6g-core", "create", "token", "b6g-equipe2", f"--duration={args.days * 24}h").strip()
    ca = json.loads(kubectl("config", "view", "--raw", "--minify", "-o", "json"))["clusters"][0]["cluster"][
        "certificate-authority-data"]
    cfg = {"apiVersion": "v1", "kind": "Config", "current-context": "equipe2",
           "clusters": [{"name": "b6g", "cluster": {"server": args.server, "certificate-authority-data": ca}}],
           "users": [{"name": "equipe2", "user": {"token": token}}],
           "contexts": [{"name": "equipe2", "context": {"cluster": "b6g", "user": "equipe2", "namespace": "b6g-edge"}}]}
    out = ROOT / "platform" / "k8s" / "generated" / "kubeconfig-equipe2"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    os.chmod(out, 0o600)
    print(f"kubeconfig restreint : {out.relative_to(ROOT)} (serveur {args.server}, valable {args.days} jours)")


if __name__ == "__main__":
    main()
