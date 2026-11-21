#!/usr/bin/env bash
# Prépare l'interface ogstun de l'UPF (sous-réseau de la slice) puis lance open5gs-upfd.
# Variables : UE_SUBNET (ex. 10.45.0.0/16), UE_GATEWAY (ex. 10.45.0.1/16).
set -euo pipefail

if ! ip link show ogstun >/dev/null 2>&1; then
  ip tuntap add name ogstun mode tun
fi
ip addr replace "${UE_GATEWAY}" dev ogstun
ip link set ogstun up
# Sortie N6 : traduction d'adresse des UEs vers le réseau Docker
iptables -t nat -C POSTROUTING -s "${UE_SUBNET}" ! -o ogstun -j MASQUERADE 2>/dev/null \
  || iptables -t nat -A POSTROUTING -s "${UE_SUBNET}" ! -o ogstun -j MASQUERADE

exec "$@"
