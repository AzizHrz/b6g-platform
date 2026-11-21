# Laboratoire QEMU (T07.4) : deux hyperviseurs QEMU/KVM dans un même conteneur privilégié, reliés par un pont
# interne, pour mesurer la migration à chaud d'une VM de l'un vers l'autre. Aucun accès réseau externe requis.
FROM ubuntu:24.04
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      qemu-system-x86 qemu-utils iproute2 iputils-ping xorriso python3 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /lab
ENTRYPOINT ["sleep", "infinity"]
