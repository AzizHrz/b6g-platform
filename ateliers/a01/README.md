# Atelier 1 — Introduction et installation de l'environnement B6G

| Rubrique | Contenu |
| --- | --- |
| Objectif | Présenter le concept Beyond 6G, identifier ses évolutions par rapport à la 6G, installer et tester l'environnement expérimental. |
| Étiquette de réalisme | **DOCUMENTAIRE** (E01, E02) et **RÉEL** (installation et tests de l'environnement, E06 à E09) |
| Ce qui est réel | Machine M1, Docker, QEMU/KVM, libvirt, plateforme Open5GS / UERANSIM / Prometheus en fonctionnement |
| Ce qui est simulé et pourquoi | Rien pour l'environnement ; les étapes E03 à E05 (Python commun, simulation ns-3 / SUMO) relèvent de l'équipe 2 |
| Interfaces utilisées | I-01 (scénario), I-12 (registre d'images) |
| Comment lancer | `make setup && make env-check && make vm-check` ; Docker : `bash platform/install_docker.sh` |
| Résultat attendu | Disposer d'un environnement expérimental fonctionnel pour les ateliers B6G |
| Résultat obtenu (source, date) | `make env-check` et `make vm-check` verts sur M1 le 2026-11-21 ; détail dans `docs/setup/SETUP_LOG.md` |

## Étapes

| Étape | Tâche | Contenu | Livrable | État |
| --- | --- | --- | --- | --- |
| E01, E02 | T01.1 | Concept B6G et 12 évolutions 6G → B6G sourcées | [docs/b6g-concepts.md](../../docs/b6g-concepts.md) | fait (inventaire des acquis du projet 6G à compléter) |
| E03, E04 | T01.2 | Python et bibliothèques communes (équipe 2) | `requirements.lock`, `tools/check_python.py` | équipe 2 ; Python 3.13.5 et `.venv` du dépôt déjà opérationnels sur M1 |
| E05 | T01.3 | Environnement de simulation ns-3 / SUMO (équipe 2) | `intelligence/sim/` | équipe 2 |
| E06 | T01.4 | Outils de virtualisation QEMU/KVM, libvirt | [platform/vm/install_vm_tools.sh](../../platform/vm/install_vm_tools.sh), `make vm-check` | fait ; VM de test à l'atelier 7 |
| E07 | T01.5 | Docker Engine, Compose v2, registre local :5000 | [platform/install_docker.sh](../../platform/install_docker.sh), `make up-registry registry-check` | fait |
| E08, E09 | T01.6 | Test global et documentation de la configuration | [tools/env_check.py](../../tools/env_check.py) (`make env-check`), [docs/hardware.md](../../docs/hardware.md), [docs/versions.lock](../../docs/versions.lock) | fait sur M1 ; M2 à vérifier par l'équipe 2 |

## Résultat de `make env-check` sur M1 (2026-11-21)

| Bloc | Résultat |
| --- | --- |
| INT0 (obligatoire) | Python 3.13.5, 7 modules, scénario valide (3 slices, 30 UEs) : tout OK |
| Matériel | 31 Gio de RAM, 20 cœurs logiques, 108 Go libres, `/dev/kvm` : conforme au plan § 4.2 |
| Plateforme | Docker 29.9.3, Compose 5.7.0, tc, iperf3, tcpdump, QEMU, virsh, virt-install, SCTP chargé, horloge NTP synchronisée ; Prometheus, Grafana, Actionneur et registre joignables |
| Indicatif (jalons suivants) | k3d, kubectl, Helm (atelier 8) ; tshark (atelier 3) ; noms `b6g-plat` / `b6g-intel` (raccordement de M2) |

## Écarts au plan

- Système : Debian 13 au lieu d'Ubuntu 22.04 (mêmes paquets ; dépôt Docker `debian`).
- `tools/env_check.sh` du plan est réalisé en Python (`tools/env_check.py`), appelé par `make check` et `make env-check`.
- `kvm-ok` (paquet Ubuntu `cpu-checker`) n'existe pas sous Debian : contrôle équivalent par `lscpu` et `/dev/kvm`.
