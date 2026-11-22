# Guide de démonstration B6G — corridor urbain connecté

Ce guide enchaîne la démonstration de la plateforme Équipe 1, segment par segment. Chaque segment indique **les commandes
à lancer**, **ce que la démonstration montre**, **l'étiquette de réalisme** et **où c'est documenté**. Il suit le fil
rouge du projet : un *corridor urbain connecté* à trois slices — `embb` (vidéo passagers, SST 1), `v2x` (messages
coopératifs des véhicules, SST 4), `miot` (capteurs et drones de bord de route, SST 3) — et 30 UEs (10 par slice).

> **Mémoire limitée.** Ne pas tout lancer en même temps. Les segments 1 à 5 partagent la
> plateforme de base (segment 1) et s'ajoutent les uns aux autres. Le **segment 6 (laboratoire de sécurité)** embarque
> son **propre** cœur 5G isolé : le lancer **seul**, plateforme principale arrêtée. Nettoyer entre deux blocs avec les
> cibles `down-*` (section « Nettoyage »).

---

## 0. Prérequis (une fois)

```bash
make setup      # crée .venv et installe les dépendances
make check      # vérifie RAM, CPU, KVM, SCTP, Docker, outils ; doit être vert
make test       # lint + 106 tests (contrats + unitaires + intégration hors plateforme)
```

| Élément | Où c'est documenté |
| --- | --- |
| Mise en place de l'environnement, versions installées | `docs/setup/ENVIRONMENT.md`, `docs/setup/SETUP_LOG.md`, `docs/versions.lock` |
| Matériel de la machine M1 | `docs/hardware.md` |
| Contrats et scénario (source unique de vérité) | `config/scenario.yaml`, `contracts/`, jalon `docs/INT0.md` |
| Concepts 5G/B6G (slice, 5QI, PFCP, GTP-U…) | `docs/b6g-concepts.md` |
| Architecture et flux | `docs/architecture/b6g-architecture.png`, `docs/architecture/flows.md` |

---

## Carte des segments

| # | Segment | Commandes clés | Ce que ça montre | Réalisme | Documentation |
| --- | --- | --- | --- | --- | --- |
| 1 | Plateforme 5G + slicing | `make up-core up-obs up-actuator up-probes` | 30 UEs enregistrés, 3 slices, limitation de débit réelle | ÉMULÉ | `docs/INT1.md`, `ateliers/a04`, `ateliers/a06` |
| 2 | Observabilité | Grafana `:3000`, Prometheus `:9090` | Métriques `b6g_*` en direct, tableaux par slice | ÉMULÉ | `docs/INT1.md` (W1.3) |
| 3 | Virtualisation + Kubernetes | `make up-vm` · `make up-k8s k8s-connect k8s-obs` + edge-infer | UPF en VM, cluster 3 niveaux, Actionneur v2 | ÉMULÉ (edge-infer MAQUETTE) | `docs/INT3.md`, `ateliers/a07`–`a10` |
| 4 | Registre Fabric | `make up-ledger` + Actionneur avec `B6G_LEDGER_URL` | Événements inscrits, endossés, vérifiables | ÉMULÉ | `ateliers/a21`, `docs/INT4.md` |
| 5 | Énergie + boucle autonome | `make up-energy up-green` · `make up-mocks-ia` + `run_a26.py` | Consommation modélisée, boucle MAPE-K | ÉMULÉ (IA = mocks) | `ateliers/a25`, `ateliers/a26` |
| 6 | Laboratoire de sécurité + D7 | `make up-lab` puis `make lab-run` (**seul**) | Attaques routées par le tunnel, jeu étiqueté | ÉMULÉ | `ateliers/a27`, `docs/INT4.md` |
| 7 | Export de données D1 | `make export-d1` | Jeu `kpi_timeseries` depuis Prometheus | ÉMULÉ | `docs/INT1.md` (W1.4) |

Le détail de chaque jalon de validation (tests, critères de passage) est dans `docs/INT0.md`, `INT1.md`, `INT3.md`,
`INT4.md`. Les cibles `make` et leur module sont dans `mk/<module>.mk` (voir `mk/README.md`).

---

## 1. Plateforme 5G et slicing (INT1)

```bash
make up-core          # Open5GS 2.7.7 + UERANSIM 3.2.8 : cœur, gNB, 30 UEs       (mk/core.mk)
make up-obs           # Prometheus, Pushgateway, cAdvisor, Grafana               (mk/observability.mk)
make up-actuator      # Actionneur v1/v2, backend tc (POST :8081/v1/actions)     (mk/observability.mk)
make up-probes        # sondes de latence et de perte par slice                 (mk/trafficgen.mk)
make core-status      # table des conteneurs + nombre de tunnels par UE (attendu : 10 / 10 / 10)
```

**Démonstration d'une action réelle** — limiter puis rétablir le débit d'une slice par l'Actionneur :

```bash
curl -s -X POST http://127.0.0.1:8081/v1/actions \
  -H 'content-type: application/json' \
  -d '{"type":"slice.bandwidth","target":"miot","params":{"rate_mbps":8},"reason":"démonstration"}'
# état courant de la plateforme :
curl -s http://127.0.0.1:8081/v1/state
```

Les ateliers associés rejouent la scène de bout en bout (charges simultanées, congestion, bascule statique → dynamique) :

```bash
.venv/bin/python ateliers/a04/run_a04.py          # plusieurs UEs et services         (ateliers/a04)
.venv/bin/python ateliers/a06/run_a06.py          # slicing dynamique, slice-autoscaler (ateliers/a06)
```

- **Ce que ça montre** : 30 UEs enregistrés, une SMF et une UPF par slice, limitation de débit appliquée dans l'UPF par
  `tc` HTB (descendant) / policer (montant), SLA par slice (`config/scenario.yaml`).
- **Validation chiffrée** : `B6G_PROM_URL=http://127.0.0.1:9090 B6G_ACTUATOR_URL=http://127.0.0.1:8081 .venv/bin/pytest -m int tests/integration/test_int1.py`
- **Documenté** : `docs/INT1.md` (démarrage, contenu, tests, limites), `ateliers/a04/README.md`, `ateliers/a06/README.md`.

## 2. Observabilité

- **Grafana** : http://127.0.0.1:3000 (lecture anonyme) — tableaux par slice (débit, latence p95, sessions, perte).
- **Prometheus** : http://127.0.0.1:9090 — métriques `b6g_*`, cibles de collecte à l'état `up`.
- **Pushgateway** : http://127.0.0.1:9091 — métriques poussées (sondes, boucle).
- **Documenté** : `docs/INT1.md` (brique W1.3), règles d'enregistrement dans `platform/observability/`.

## 3. Virtualisation et Kubernetes (ateliers 7 à 10, INT3)

```bash
# (a) UPF miot en machine virtuelle KVM (le conteneur upf-miot est arrêté, la VM prend sa place)
make up-vm            # (mk/vm.mk)   ;   make vm-status   ;   make down-vm pour revenir au conteneur

# (b) cluster k3d à trois niveaux Edge / Fog / Cloud, UPF raccordées, collecte k8s
make up-k8s k8s-namespaces k8s-connect k8s-obs            # (mk/k8s.mk)
kubectl apply -k platform/k8s/apps/echo-app
kubectl apply -k platform/k8s/apps/edge-infer-edge        # service d'inférence au bord (NodePort 30092)
make k8s-status
```

- **Ce que ça montre** : portabilité de l'UPF (conteneur ↔ VM), orchestration par niveaux, Actionneur **v2**
  (`slice.state`, `link.netem`, `deployment.replicas`, `deployment.placement`, `ue.isolate`, `ue.release`),
  déploiement par le gabarit I-11.
- **Validation** : `.venv/bin/pytest -m int tests/integration/test_int3.py` (12 réussis, 1 ignoré).
- **Documenté** : `docs/INT3.md`, `ateliers/a07` (VM UPF + migration à chaud), `ateliers/a08` (k3d + Helm),
  `ateliers/a09` (conteneur vs VM), `ateliers/a10` (Edge / Fog / Cloud).
- **Avant d'arrêter le cluster** : `make k8s-obs-off` puis `make down-k8s`.

## 4. Registre Hyperledger Fabric (atelier 21, INT4)

```bash
make up-ledger        # réseau Fabric (Org1, Org2, ordonnanceur), canal b6g, chaincode eventlog, passerelle I-07 :8082
# raccorder l'Actionneur au registre (émission asynchrone de ses actions) :
make stop-actuator ; B6G_LEDGER_URL=http://127.0.0.1:8082 make up-actuator
.venv/bin/python ateliers/a21/run_a21.py          # inscrit et vérifie 100 événements, mesure le coût
```

**Vérifier un événement** (empreinte recalculée côté chaincode, organisations endossantes) :

```bash
curl -s http://127.0.0.1:8082/v1/health
# GET /v1/verify/<event_id> → hash_match, chain_ok, endorsements
```

- **Ce que ça montre** : trace infalsifiable et partagée des décisions ; endossement `AND(Org1MSP, Org2MSP)` ; coût
  (latence de l'ordre de la seconde) qui réserve le registre à l'audit, hors de la boucle temps réel.
- **Validation** : `.venv/bin/pytest -m int tests/integration/test_int4.py` (5 réussis).
- **Documenté** : `ateliers/a21/README.md`, `docs/INT4.md`. Arrêt : `make down-ledger`.

## 5. Énergie et boucle autonome (ateliers 25 et 26)

```bash
# (a) Énergie : exporteur de consommation (conteneur energy sur le réseau b6g-obs) + politique de sobriété
make up-energy        # (mk/energy.mk)
make up-green         # éteint les composants inutiles via l'Actionneur ; journal .run/green.log

# (b) Boucle MAPE-K complète (nécessite registre + mocks d'intelligence de l'équipe 2)
make up-mocks-ia      # Décision :8090, Jumeau :8091 (mk/loop.mk)
.venv/bin/python ateliers/a26/run_a26.py          # dégradation contrôlée puis 10 itérations autonomes
```

- **Ce que ça montre** : modèle de puissance `P = P_idle + (P_max − P_idle) × charge` ; boucle Monitor → Analyze →
  Decide → Act → Learn qui détecte une violation, décide, applique une action réelle et journalise (D8 + registre).
- **Limite honnête** : avec les **mocks** `qos-tree` / jumeau linéaire, la boucle corrige sans toujours ramener le SLA
  v2x strict à zéro violation (effet file HTB / bufferbloat). La restauration autonome effective est déjà démontrée à
  l'**atelier 6**. La boucle avec IA **réelle** sera validée à **INT5** (livrables équipe 2).
- **Documenté** : `ateliers/a25/README.md` (énergie), `ateliers/a26/README.md` (boucle, mécanisme et limite détaillés).
- Arrêt : `make stop-green stop-energy stop-loop stop-mocks-ia`.

## 6. Laboratoire de sécurité isolé et jeu D7 (atelier 27, INT4)

> **À lancer seul** (son propre cœur 5G isolé). Arrêter d'abord la plateforme principale : voir « Nettoyage ».

```bash
make up-lab           # cœur + RAN + outils d'attaque sur le réseau Docker « b6g-lab » (internal, sans route externe)
make lab-status       # conteneurs du laboratoire + tunnels par UE
make lab-run          # campagne étiquetée → datasets/raw/security/ (hors Git)
make down-lab         # arrêt du laboratoire
```

- **Ce que ça montre** : attaques rejouées **à travers le tunnel 5G** (inondation UDP, tempête de ré-enregistrements),
  captures tcpdump par UPF/AMF, étiquetage par UE et par fenêtre. Garde-fou d'honnêteté : rien n'est étiqueté comme
  attaque si le trafic n'a pas traversé la liaison 5G.
- **Limite connue (non corrigée, sur décision)** : le scénario de **balayage de ports (`scan`)** n'est **pas** capturé à
  travers le tunnel (il sort par l'interface directe du conteneur). Les classes `udp_flood` et `reg_storm` sont
  exploitables, `scan` ne l'est pas. Cause et correctif prévu : `ateliers/a27/README.md`, section « Limite connue ».
  **Le tag `int4` reste en attente** tant que ce point n'est pas résolu.
- **Documenté** : `ateliers/a27/README.md`, `docs/INT4.md`, contrat D7 dans `contracts/datasets.yaml`.

## 7. Export du jeu de données D1 (W1.4)

```bash
make export-d1 RUN_ID=demo SINCE=30m FORMAT=csv     # Prometheus → datasets/raw/kpi_timeseries-demo.* (+ validation)
```

- **Ce que ça montre** : production d'un jeu `kpi_timeseries` (D1) daté et vérifié par manifeste à partir des métriques
  réelles, livrable pour l'équipe 2.
- **Documenté** : `docs/INT1.md` (brique W1.4), `contracts/datasets.yaml`.

---

## Nettoyage

```bash
# dans l'ordre inverse, selon ce qui a été lancé :
make stop-green stop-energy stop-loop stop-mocks-ia stop-probes stop-actuator
make k8s-obs-off ; make down-k8s
make down-vm            # si l'UPF a été passée en VM
make down-ledger
make down-obs down-core
make down-lab           # laboratoire de sécurité
make down-registry
```

## Rappel des limites présentées honnêtement

| Point | État | Où c'est documenté |
| --- | --- | --- |
| Mesures de latence/débit | **ÉMULÉ** (pas de couche radio réelle) | `docs/INT1.md` § Limites |
| edge-infer | **MAQUETTE** (image équipe 2 non livrée) | `docs/INT3.md` § Écarts |
| Boucle MAPE-K autonome | corrige mais ne résout pas le SLA v2x strict avec les **mocks** | `ateliers/a26/README.md` |
| Rejeu NTN | profil **SYNTHÉTIQUE** (outil équipe 2 non livré) | `docs/INT4.md` |
| Jeu D7 — balayage `scan` | **non capturé** à travers le tunnel ; `int4` en attente | `ateliers/a27/README.md`, `docs/INT4.md` |
| INT2 / INT5 / INT6 | dépendent des livrables de l'équipe 2 | plan maître § 9.3 |

## Ports exposés (rappel, `config/scenario.yaml`)

| Service | Port | Service | Port |
| --- | --- | --- | --- |
| Prometheus | 9090 | Actionneur | 8081 |
| Grafana | 3000 | Registre (passerelle I-07) | 8082 |
| Pushgateway | 9091 | Décision (mock) | 8090 |
| Registre d'images | 5000 | Jumeau (mock) | 8091 |
| edge-infer (NodePort) | 30092 | — | — |

---

**Où trouver quoi, en un coup d'œil**

- Jalons et critères de passage : `docs/INT0.md`, `INT1.md`, `INT3.md`, `INT4.md`.
- Ateliers (objectif, réalisme, lancement, résultat) : `ateliers/aXX/README.md` (gabarit `ateliers/_template/`).
- Cibles `make` par module : `mk/<module>.mk` (index `mk/README.md`).
- Contrats et scénario : `contracts/`, `config/scenario.yaml`.
- État et historique de l'environnement : `docs/setup/SETUP_LOG.md`, `docs/versions.lock`.
