# Outils d'attaque du laboratoire isolé (M11) : hping3 (inondation UDP), nmap (balayage), tcpdump (captures).
# Utilisé uniquement dans le réseau b6g-lab (internal: true), partageant l'espace réseau d'un conteneur d'UE.
FROM ubuntu:24.04
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends hping3 nmap tcpdump iproute2 iputils-ping \
 && rm -rf /var/lib/apt/lists/*
ENTRYPOINT ["sleep", "infinity"]
