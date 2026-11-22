#!/usr/bin/env bash
# Atelier 7 (T07.4) : lance le laboratoire QEMU (deux hyperviseurs) et la mesure de 3 migrations à chaud.
# Prérequis : image de base ~/b6g-data/vm/jammy-server-cloudimg-amd64.img ; image b6g/qemu-lab:0.1.0
#   docker build -t b6g/qemu-lab:0.1.0 platform/vm/qemu-lab
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$here/results"
docker rm -f b6g-qemu-lab >/dev/null 2>&1 || true
docker run -d --name b6g-qemu-lab --privileged --device /dev/kvm --network none \
  -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" \
  -v "$HOME/b6g-data/vm:/vm:ro" -v "$here/migrate_lab.py:/migrate_lab.py:ro" -v "$here/results:/out" \
  b6g/qemu-lab:0.1.0 >/dev/null
docker exec b6g-qemu-lab python3 /migrate_lab.py
docker rm -f b6g-qemu-lab >/dev/null
