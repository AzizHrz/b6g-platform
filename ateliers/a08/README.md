# Atelier 8 — Cloud-Native et orchestration B6G

| Rubrique | Contenu |
| --- | --- |
| Objectif | Décomposer la plateforme en microservices, identifier leurs dépendances, déployer les fonctions B6G dans Kubernetes, observer leurs ressources et étudier la mise à l'échelle automatique. |
| Étiquette de réalisme | **ÉMULÉ** (k3s réel dans des conteneurs Docker : k3d ; Open5GS et UERANSIM réels) |
| Ce qui est réel | Cluster Kubernetes 1.30 (1 serveur, 3 agents), charts Helm, ordonnancement, HPA, metrics-server, kube-state-metrics, enregistrement d'un UE et trafic à travers le cœur déployé dans le cluster |
| Ce qui est simulé et pourquoi | Les nœuds du cluster sont des conteneurs d'une seule machine (M1) : pas de réseau physique entre nœuds |
| Interfaces utilisées | I-01 (niveaux, valeurs Helm), I-02 (`b6g_k8s_replicas`, `b6g_app_request_latency_ms`, CPU des niveaux), I-11 (déploiement), I-12 (registre `b6g-plat:5000`) |
| Comment lancer | `make up-k8s`, `kubectl apply -k platform/k8s/apps/echo-app`, `make k8s-core`, `make k8s-obs`, puis `.venv/bin/python ateliers/a08/run_a08.py` |
| Résultat attendu | Comprendre les mécanismes d'orchestration Cloud-Native |
| Résultat obtenu (source, date) | `results/`, `figures/hpa.png`, tableau de bord Grafana « B6G — Kubernetes k3d », mesures du 2026-11-21 sur M1 |

## E01–E03 — Microservices et dépendances (T08.1)

Graphe complet et ordre de démarrage : [docs/architecture/dependencies.md](../../docs/architecture/dependencies.md).
Chaque fonction Open5GS, chaque composant UERANSIM et chaque service B6G est un microservice joint par le réseau ;
le NRF est le point de départ (toutes les fonctions s'y enregistrent), l'AMF le dernier du cœur, puis gNB et UEs.

## E04–E05 — Kubernetes et déploiement des services (T08.2)

| Élément | Réalisation |
| --- | --- |
| Cluster | [platform/k8s/cluster.yaml](../../platform/k8s/cluster.yaml) : k3d 5.7.4, k3s v1.30.4 ; nœuds `k3d-b6g-agent-0/1/2` étiquetés `b6g/tier=edge/fog/cloud` (noms du scénario) ; API sur le port 6443 ; registre `b6g-plat:5000` relayé vers le registre local |
| Outils | k3d 5.7.4, kubectl 1.30.6, Helm 3.16.2 dans `~/b6g-ext/bin` (sommes de contrôle vérifiées) |
| Cœur 5G | Charts Gradiant `open5gs` 2.2.5 (Open5GS 2.7.2) et `ueransim-gnb` 0.2.6, espace de noms `b6g-5gc`, valeurs générées depuis le scénario (`platform/k8s/values/render.py`) : PLMN 001/01, slice embb (S-NSSAI 1-000001, DNN embb), fonctions 4G désactivées |
| Résultat | 13 fonctions réparties par l'ordonnanceur sur les 4 nœuds ; UE IMSI 001010000000001 enregistré, session PDU établie (`uesimtun0` = 10.45.0.3), RTT 2,1 ms vers l'UPF et 36 ms vers Internet, sans perte |

Problèmes rencontrés lors du déploiement Helm (détail dans `docs/setup/SETUP_LOG.md`) :

| Symptôme | Cause | Correction |
| --- | --- | --- |
| MongoDB en `ImagePullBackOff` | image `bitnami/mongodb:5.0.10-debian-11-r3` retirée de docker.io/bitnami (2025) | même version depuis `bitnamilegacy/mongodb` |
| UPF en `Init:CrashLoopBackOff` (« Net device already exists ») | clé `dev: ogstun` absente de `subnetList` | clé ajoutée |
| Fonctions 4G (HSS, MME, PCRF, SGW) déployées | valeurs par défaut du chart (EPC + 5GC) | désactivées dans les valeurs générées |
| Enregistrement rejeté (cause 95), SCP : « No SEPP », « NF-Discover failed [400] » | NRF resté sur le PLMN par défaut du chart (999/70) : l'UE (001/01) était traité comme itinérant | `nrf.config.servingList` au PLMN du scénario, redémarrage des fonctions |
| Tunnel de l'UE vers une adresse disparue | gNB et UE redémarrés ensemble : l'UE s'est attaché à l'ancien pod gNB | redémarrage de l'UE seul, une fois le gNB stable |

## E06 — Observation des ressources (T08.3)

`make k8s-obs` : kube-state-metrics (chart 5.25.1), compte de service en lecture seule (`platform/k8s/prometheus-reader.yaml`),
collecte par le proxy de l'API Kubernetes (`platform/k8s/render_obs.py`) : CPU et mémoire de chaque pod (cAdvisor du
kubelet), répliques des déploiements, métriques applicatives des pods annotés. Nouvelles métriques I-02 disponibles :
`b6g_k8s_replicas{deployment, tier}`, `b6g_app_request_latency_ms{app, tier, quantile}` et le CPU de chaque niveau
(`b6g_nf_cpu_ratio{nf="k3d-b6g-agent-N"}`, rapporté à la capacité du niveau dans le scénario).
Tableau de bord : « B6G — Kubernetes k3d (atelier 8) » (`platform/observability/grafana/dashboards/b6g-k8s.json`).

## E07–E08 — Mise à l'échelle manuelle et automatique (T08.4)

Application `b6g-echo-app` (atelier 9) dans `b6g-cloud`, sur le nœud Cloud, requête CPU 200m ; HPA de 1 à 10 répliques,
cible 50 % de la requête ([platform/k8s/apps/echo-app/](../../platform/k8s/apps/echo-app/)).

Mise à l'échelle manuelle (`results/scaling_manual.csv`) : 1 → 3 répliques disponibles en 2,0 s ; 3 → 1 en 0,2 s.

Auto-scaling (`results/hpa.csv`, `figures/hpa.png`) : paliers de 1, 2, 4 et 8 clients concurrents sur `/work`
(40 ms de calcul par requête, 200 ms de pause par client), puis arrêt de la charge.

| Clients | Répliques stabilisées | Requêtes servies / s | Latence p50 | Latence p95 |
| --- | --- | --- | --- | --- |
| 1 | 2 | 4,2 | 42,9 ms | 43,2 ms |
| 2 | 4 | 8,4 | 42,8 ms | 43,1 ms |
| 4 | 7 | 16,8 | 41,4 ms | 54–57 ms |
| 8 | 10 (maximum) | 33,6 | 41,2 ms | 51–56 ms |
| 0 | 10 puis 1 après ≈ 80 s | 0 | — | — |

- Le nombre de répliques suit la charge à chaque palier, avec un décalage de 15 à 30 s (fenêtre de metrics-server et
  période de l'HPA) ; la latence médiane reste égale au temps de calcul (≈ 41 ms) : le service n'est jamais saturé.
- La réduction attend la fenêtre de stabilisation de 60 s (`behavior.scaleDown`), puis passe directement de 10 à 1.
- Un premier essai avec une requête CPU de 100m a fait passer l'HPA de 1 à 10 répliques dès 2 clients (CPU à 456 % de la
  requête) : le dimensionnement de la requête CPU fixe la sensibilité de l'auto-scaling.

## Résultat (A08-R)

Le cluster place les services selon les étiquettes de niveau, redémarre les fonctions en échec, et adapte le nombre
d'instances à la charge sans intervention ; le cœur 5G complet fonctionne dans Kubernetes, avec ses dépendances
gérées par les redémarrages automatiques (PCF et UDR ont redémarré 7 fois en attendant MongoDB).
