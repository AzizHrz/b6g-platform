# Matériel et configuration des machines (T01.6)

Relevés du 2026-11-21. Commande de contrôle : `make env-check` (`tools/env_check.py`) ; installation pas à pas :
`docs/setup/ENVIRONMENT.md` ; journal : `docs/setup/SETUP_LOG.md` ; versions : `docs/versions.lock`.

## M1 `b6g-plat` — plateforme (équipe 1)

| Élément | Valeur | Exigence du plan (§ 4.2) |
| --- | --- | --- |
| Système | Debian 13.7 (trixie), natif ; noyau 6.12.115+deb13.1-amd64 | Ubuntu 22.04 de préférence natif (Debian 13 retenue, mêmes paquets) |
| CPU | Intel Core i7-13800H, 14 cœurs / 20 threads, VT-x | 8 cœurs |
| RAM | 30 Gio + 24 Gio de swap | 32 Go (16 minimum) |
| Disque | SSD NVMe, 444 Go, ≈ 105 Go libres | 150 Go SSD (60 Go libres minimum) |
| GPU | NVIDIA RTX 2000 Ada, 8 Gio (pilote 550.163.01, CUDA 12.4) | aucun (utile pour l'atelier 23) |
| Virtualisation | `/dev/kvm`, QEMU 10.0.13, libvirt 11.3.0, utilisateur dans `kvm` et `libvirt` | KVM disponible |
| Module SCTP | chargé, persistant (`/etc/modules-load.d/sctp.conf`) | requis (N2) |
| Horloge | synchronisée par NTP (`timedatectl`) | `chrony`, écart M1/M2 < 50 ms |
| Pare-feu | UFW actif ; port 8081 ouvert aux réseaux Docker (172.16.0.0/12) | ports 9090, 3000, 8081, 8082, 5000, 6443, 30092 ouverts vers M2 |

## M2 `b6g-intel` — simulation et IA (équipe 2)

À compléter par l'équipe 2 avec `make env-check` lancé sur M2 (même dépôt, mêmes cibles).

## Réseau entre M1 et M2

| Élément | Configuration |
| --- | --- |
| Résolution de noms | `/etc/hosts` sur chaque machine : `b6g-plat` et `b6g-intel`. Sur une seule machine : `127.0.0.1 b6g-plat b6g-intel` |
| Ports M2 → M1 | 9090 (Prometheus), 3000 (Grafana), 8081 (Actionneur), 8082 (registre), 5000 (images), 6443 (API k3d), 30092 (edge-infer) |
| Ports M1 → M2 | 8090 (Décision), 8091 (Jumeau) |
| Ouverture UFW sur M1 (exemple, réseau local 192.168.1.0/24) | `sudo ufw allow from 192.168.1.0/24 to any port 9090,3000,8081,8082,5000,6443,30092 proto tcp` |

## Réseaux internes de la plateforme (M1)

| Réseau | Plage | Usage |
| --- | --- | --- |
| `b6g-core` (pont Docker) | 172.22.0.0/24 | Fonctions Open5GS, gNB, UEs, serveur iperf3 (adresses fixes, `platform/core/render.py`) |
| `b6g-obs` (pont Docker) | attribuée par Docker | Prometheus, Pushgateway, cAdvisor, Grafana |
| Sous-réseaux UE | embb 10.45.0.0/16, v2x 10.46.0.0/16, miot 10.47.0.0/16 | Interfaces `ogstun` des UPF, `uesimtunN` des UEs |
| libvirt `default` | 192.168.122.0/24 (NAT) | VM de l'atelier 7 |
