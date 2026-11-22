# Atelier 9 — Conteneurisation des fonctions B6G

| Rubrique | Contenu |
| --- | --- |
| Objectif | Construire une image et un conteneur, déployer une fonction réseau conteneurisée reliée à d'autres conteneurs, mesurer ses ressources et la comparer à la même fonction en machine virtuelle. |
| Étiquette de réalisme | **ÉMULÉ** (Docker Engine 29.9.3, Open5GS, UERANSIM et trafic réels sur M1) |
| Ce qui est réel | Image construite et publiée dans le registre local, UPF Open5GS conteneurisée sur le chemin GTP-U des UEs, mesures cgroup et libvirt |
| Ce qui est simulé et pourquoi | Couche radio (UERANSIM) |
| Interfaces utilisées | I-12 (registre `b6g-plat:5000`), I-02 (`b6g_app_request_latency_ms`), N3 / N4 / N6 |
| Comment lancer | `docker build -t b6g/echo-app:0.1.0 platform/apps/echo-app` ; `make up-core` ; `.venv/bin/python ateliers/a09/run_a09.py` (VM créée par `make up-vm`) |
| Résultat attendu | Être capable de déployer une fonction B6G conteneurisée |
| Résultat obtenu (source, date) | `results/vm_vs_container.csv`, mesures du 2026-11-21 sur M1 |

## E01–E03 — Docker, image et conteneur (T09.1)

Docker Engine 29.9.3 et Compose 5.7.0 installés à l'atelier 1. Application `b6g-echo-app`
([platform/apps/echo-app](../../platform/apps/echo-app)) : écho, charge CPU (`/work`), métrique
`b6g_app_request_latency_ms{app, tier, quantile}` ; bibliothèque standard Python uniquement.

| Critère | Résultat |
| --- | --- |
| Dockerfile multi-étapes | étape de compilation (vérification du code), puis image d'exécution `python:3.12-alpine`, utilisateur non privilégié (uid 10001), contrôle de santé |
| Taille de l'image | **74 Mo** (objectif < 150 Mo) |
| Publication | `127.0.0.1:5000/b6g/echo-app:0.1.0`, tirée par le cluster k3d sous `b6g-plat:5000/b6g/echo-app:0.1.0` (atelier 8) |
| Conteneur | `/health`, `/work`, `/echo` et `/metrics` vérifiés |

## E04–E05 — Fonction réseau conteneurisée et connexion de conteneurs (T09.2)

Le cœur de la plateforme est lui-même conteneurisé (fichier Compose généré par `platform/core/render.py`) : chaque
slice a son UPF dans un conteneur (`upf-embb`, `upf-v2x`, `upf-miot`), reliée par le réseau Docker `b6g-core` à sa SMF
(PFCP, N4), au gNB (GTP-U, N3) et au serveur de l'application (`iperf`, N6, après NAT). Le trafic d'un UE traverse
ainsi trois conteneurs : `ue-<slice>` → `gnb` → `upf-<slice>` → `iperf` (vérifié aux ateliers 3, 4 et 6).

Particularités de l'UPF conteneurisée : exécution en `root` avec la capacité `NET_ADMIN` et le périphérique
`/dev/net/tun` (création de `ogstun` et de la NAT), limitation de débit par l'Actionneur (`tc` dans le conteneur).

## E06–E07 — Conteneur contre machine virtuelle (T09.3)

Même fonction (Open5GS UPF de la slice miot), même adresse N4 / N3, même trafic : 10 UEs miot en TCP descendant sans
limitation, 3 répétitions de 15 s. Démarrage mesuré jusqu'à la réponse du point de métriques de l'UPF ; CPU par
cgroup (conteneur) ou temps CPU du domaine (VM) ; mémoire : cgroup `memory.current` ou RSS du processus QEMU.

| Indicateur | Machine virtuelle (1 vCPU, 1 Gio) | Conteneur | Rapport |
| --- | --- | --- | --- |
| Démarrage jusqu'à l'UPF prête | 21,8 s | **0,2 s** | ≈ 100 × |
| Débit moyen (min – max) | 1 012 Mbit/s (845 – 1 126) | 875 Mbit/s (804 – 999) | comparable (dispersion ± 15 %) |
| CPU consommé | 1,73 cœur | **0,98 cœur** | 1,8 × |
| Mémoire | 732 Mo | **30 Mo** | 24 × |

- Débit : du même ordre dans les deux cas ; il est limité par le gNB UERANSIM (2,3 cœurs mesurés) et non par l'UPF.
- Ressources : le conteneur partage le noyau de l'hôte ; la VM paie un noyau invité, l'émulation des périphériques et
  les fils d'entrées-sorties de QEMU (1,73 cœur pour un seul vCPU).
- Démarrage : un processus contre l'amorçage d'un système complet ; la réassociation PFCP de la SMF s'ajoute ensuite
  dans les deux cas (réattachement des UEs avec reprise).
- La VM apporte en échange une isolation plus forte et la migration à chaud (atelier 7).

## Résultat (A09-R)

Une fonction B6G conteneurisée (image de 74 Mo publiée dans le registre local, UPF dans le chemin des données) se
déploie en 0,2 s et consomme 24 fois moins de mémoire que la même fonction en VM, pour un débit équivalent.
L'état nominal de la plateforme est rétabli après la mesure : UPF miot conteneurisée, limitation 5 / 10 Mbit/s
réappliquée par l'Actionneur, VM arrêtée.
