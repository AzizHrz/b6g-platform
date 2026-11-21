# Flux entre composants (T02.4)

Schéma associé : [b6g-architecture.png](b6g-architecture.png) (source modifiable : `b6g-architecture.drawio`,
régénérable par `make_architecture.py` depuis `config/scenario.yaml`).

## 1. Flux entre modules B6G (interfaces I-01 à I-12)

Chaque flux entre modules passe par une interface versionnée de `contracts/` (plan maître § 6.1).

| # | Source → destination | Contenu | Interface | Protocole / format | Point de connexion | État au 2026-11-21 |
| --- | --- | --- | --- | --- | --- | --- |
| F01 | `config/scenario.yaml` → tous les modules | slices, UEs, profils, niveaux, liens, ports, SLA | **I-01** | fichier YAML, `scenario.schema.json` | P1 | en service (render.py, Actionneur, sondes, autoscaler) |
| F02 | NF Open5GS, cAdvisor, Actionneur, sondes → Prometheus | métriques natives, converties en `b6g_*` | **I-02** | HTTP, texte Prometheus | P2 | en service (10 métriques sur 16) |
| F03 | Prometheus → boucle, Décision, Jumeau, LLM | état réseau courant | **I-02 / I-03** | HTTP `/api/v1/query` ; objet `b6g.snapshot.v1` | P3 | en service (`snapshot.build()`) |
| F04 | Boucle, Décision, LLM, sécurité → Actionneur | ActionRequest | **I-04** | HTTP REST JSON `POST /v1/actions` | P4 | en service (v1 : `slice.bandwidth`, `noop`) |
| F05 | Actionneur → UPF (tc), conteneurs, k3d | application technique de l'action | **I-04** (côté fournisseur) | `docker exec … tc`, `kubectl` | P4 | en service (tc HTB / policer) |
| F06 | Boucle → API Décision | DecideRequest → Decision | **I-05** | HTTP REST JSON `POST /v1/decide` | P5 | sur mock (`mock_decision`) ; réel à INT2 |
| F07 | Boucle → API Jumeau | WhatIfRequest → WhatIfResponse | **I-06** | HTTP REST JSON `POST /v1/whatif` | P5 | sur mock (`mock_twin`) ; réel à INT5 |
| F08 | Actionneur, boucle, sécurité → registre | événements `actuator.applied`, `slice.resized`… | **I-07 / I-08** | HTTP REST JSON `POST /v1/events`, `b6g.event.v1` | P6 | sur mock (`mock_ledger`) ; Fabric à INT4 |
| F09 | Producteurs → consommateurs de données | jeux D1 à D8 et manifestes | **I-09** | CSV / Parquet + YAML | P7 | échantillons ; D2 réel (ateliers 4 et 6) ; D1 réel avec W1.4 |
| F10 | Générateur de requêtes → edge-infer | requête d'inférence | **I-10** | HTTP REST JSON | P8 | à INT3 |
| F11 | Équipe 2 → cluster k3d | manifeste de déploiement | **I-11** | Kustomize | P8 | à INT3 |
| F12 | Propriétaire d'un module → registre d'images → k3d | images `b6g/<module>:<semver>` | **I-12** | registre Docker `b6g-plat:5000` | P8 | registre en service (`make registry-check`) |
| F13 | Simulation NTN → Actionneur | profil de lien rejoué (`link.netem`) | **I-04** | HTTP REST JSON | P9 | Actionneur v2 (INT3), rejeu à INT4 |

## 2. Flux internes au cœur 5G (module M01, normes 3GPP)

Ces flux ne traversent pas une interface du projet : ils sont internes au module M01 et observés dans les captures
de l'atelier 3 (`ateliers/a03/`).

| Point de référence | Source → destination | Protocole | Transport | Rôle |
| --- | --- | --- | --- | --- |
| Uu (émulé) | UE → gNB | RRC / NAS sur liaison UERANSIM | UDP 4997 (simulation radio UERANSIM) | Accès radio simulé |
| N1 | UE → AMF (via gNB) | NAS-5GS | encapsulé dans NGAP | Enregistrement, authentification, demande de session PDU |
| N2 | gNB → AMF | NGAP | SCTP 38412 | Signalisation du RAN vers le cœur |
| N3 | gNB → UPF de la slice | GTP-U | UDP 2152 | Plan utilisateur |
| N4 | SMF → UPF | PFCP | UDP 8805 | Création et modification des sessions dans l'UPF |
| N6 | UPF → réseau de données | IP (NAT vers le réseau `b6g-core`) | — | Sortie du trafic des UEs |
| SBI | NF ↔ NF (AMF, SMF, AUSF, UDM, UDR, PCF, NSSF, BSF, NRF) | HTTP/2, JSON | TCP 7777 | Interfaces de services 5G |
| — | UDR, PCF → MongoDB | protocole MongoDB | TCP 27017 | Données d'abonnés et de politiques |
