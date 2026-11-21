# Atelier 6 — Network Slicing dynamique et intelligent

| Rubrique | Contenu |
| --- | --- |
| Objectif | Définir des services et leurs exigences, créer et dimensionner trois slices, observer leur charge, puis adapter automatiquement les ressources et comparer slicing statique et dynamique. |
| Étiquette de réalisme | **ÉMULÉ** (cœur Open5GS et UERANSIM réels, paquets réels, limitation tc réelle ; pas de couche radio) |
| Ce qui est réel | Slices S-NSSAI, SMF et UPF dédiées par slice, limitation HTB dans chaque UPF, trafic iperf3 et ping à travers gNB / GTP-U / UPF, métriques Prometheus, actions de l'Actionneur |
| Ce qui est simulé et pourquoi | Aucune radio (UERANSIM) : la contention modélisée est celle du débit attribué à chaque slice dans son UPF, pas celle de l'interface air |
| Interfaces utilisées | I-01 (scénario : SLA, débits), I-02 (métriques `b6g_*`), I-03 (snapshot), I-04 (`slice.bandwidth`) |
| Comment lancer | `make up-core up-obs up-actuator up-probes` puis `.venv/bin/python ateliers/a06/run_a06.py` ; boucle seule : `make up-autoscaler` |
| Résultat attendu | Démontrer l'intérêt d'un slicing dynamique : SLA de la slice v2x tenu sous surcharge, contrairement au slicing statique |
| Résultat obtenu (source, date) | `results/*.csv`, `figures/*.png`, mesures du 2026-11-21 sur M1 (Debian 13, Open5GS 2.7.7, UERANSIM 3.2.8) |

## E01–E02 — Services et exigences (T06.1)

Définis dans `config/scenario.yaml` (contrats 1.0.0), section `slices` :

| Slice | S-NSSAI | Service | Latence p95 max | Débit min | Perte max | rate / ceil initiaux |
| --- | --- | --- | --- | --- | --- | --- |
| embb | 1-000001 | vidéo et services aux passagers | 100 ms | 20 Mbit/s | 1 % | 60 / 100 Mbit/s |
| v2x | 4-000004 | messages coopératifs des véhicules | 20 ms | 2 Mbit/s | 0,1 % | 20 / 40 Mbit/s |
| miot | 3-000003 | capteurs de bord de route et drones | 500 ms | 0,5 Mbit/s | 5 % | 5 / 10 Mbit/s |

## E03–E04 — Création des slices et affectation des ressources (T06.2)

Chaque slice dispose de sa SMF et de son UPF (`platform/core/`) ; l'Actionneur v1 applique `rate` / `ceil` par HTB
dans l'UPF (sens descendant) et un policer à `ceil` (sens montant). Critère : débit plafonné mesuré à ± 10 % de la
consigne. Méthode de référence : 1 UE en UDP descendant à 1,5 × ceil (`results/slicing.csv`).

| Slice | Consigne ceil | Débit UDP reçu | Écart | ± 10 % | Goodput TCP, 10 UEs |
| --- | --- | --- | --- | --- | --- |
| embb | 100 | 97,71 | −2,3 % | oui | 96,25 (−3,8 %) |
| embb | 50 | 48,86 | −2,3 % | oui | 48,02 (−4,0 %) |
| v2x | 40 | 39,09 | −2,3 % | oui | 38,27 (−4,3 %) |
| v2x | 20 | 19,54 | −2,3 % | oui | 18,98 (−5,1 %) |
| miot | 10 | 9,77 | −2,3 % | oui | 8,70 (−13,0 %) |
| miot | 5 | 4,89 | −2,3 % | oui | 4,19 (−16,1 %) |

L'écart constant de −2,3 % correspond aux en-têtes IP et UDP (28 octets sur des paquets de 1 228 octets) : HTB
limite des paquets IP, iperf3 compte la charge utile. Le goodput de 10 flux TCP simultanés à faible débit est plus
bas (pertes dans la file HTB et retransmissions) : c'est une propriété de TCP, pas une erreur de limitation.

## E05–E06 — Trafics différenciés et charge par slice (T06.3)

Profils nominaux du scénario pendant 60 s, les 30 UEs ensemble (`results/load.csv`, figure `figures/charge_par_slice.png`,
tableau de bord Grafana « B6G — Multi-UE et congestion ») :

| Slice | Profil | Débit médian | Latence p95 médiane |
| --- | --- | --- | --- |
| embb | vidéo TCP descendante, 8 Mbit/s par UE | 83,7 Mbit/s | 20,2 ms |
| v2x | CAM UDP montant, 300 o à 10 Hz | 0,33 Mbit/s | 5,2 ms |
| miot | capteur UDP montant, 100 o à 1 Hz | 0,08 Mbit/s | 3,4 ms |

Le premier échantillon miot (1 450 ms) est un résidu de la saturation TCP de l'étape précédente.

## E07–E08 — Adaptation et décision automatique (T06.4)

`platform/loop/slice_autoscaler.py`, boucle de 5 s, uniquement par l'API Actionneur :

- entrée : `snapshot.build()` (moyenne sur 10 s) et `GET /v1/state` ;
- déclencheur : latence p95 > SLA de la slice, ou débit ≥ 90 % de `ceil` ;
- action : `ceil` × 1,5 (au plus la capacité totale, 150 Mbit/s), `rate` relevé dans la capacité restante
  (somme des `rate` ≤ 150, sinon l'Actionneur répond 409) ; période de garde de 10 s par slice ;
- retour aux valeurs du scénario quand le débit retombe sous 30 % du `rate` initial.

Décisions observées pendant la surcharge v2x (`results/autoscaler.log`) :

| Instant (UTC) | Décision | Cause |
| --- | --- | --- |
| 15:08:56 | v2x 20 / 40 → 30 / 60 | latence p95 69,3 ms > 20 ms |
| 15:09:06 | v2x 30 / 60 → 45 / 90 | latence p95 136,7 ms > 20 ms |
| 15:09:21 | v2x 45 / 90 → 67,5 / 135 | latence p95 45,5 ms > 20 ms (moyenne sur 10 s encore dégradée) |
| 15:10:31 | v2x 67,5 / 135 → 20 / 40 | charge retombée à 3,2 Mbit/s |

## E09 — Statique contre dynamique (T06.5)

Surcharge de la slice v2x : 10 UEs en UDP descendant à 6 Mbit/s chacun (60 Mbit/s offerts pour un plafond de 40),
pendant 90 s, sans puis avec le slice-autoscaler (`results/compare.csv`, `results/compare_series.csv`,
`figures/statique_vs_dynamique_v2x.png`).

| Indicateur (régime établi) | Statique | Dynamique |
| --- | --- | --- |
| Latence p95 v2x, médiane | 137 ms | **0,38 ms** |
| Échantillons respectant le SLA de 20 ms | 5,9 % | **70,6 %** |
| Débit v2x moyen | 39,0 Mbit/s | **54,8 Mbit/s** |
| Perte de la sonde | 38,2 % | 12,1 % |
| Actions | 0 | 3 |

Délais de réaction mesurés :

- 0,7 s entre le premier échantillon Prometheus hors SLA et la première action appliquée (critère T06.4 : < 10 s) ;
- 15,7 s entre le début de la surcharge et la première action : la chaîne de mesure (ping toutes les 5 s,
  Pushgateway, collecte toutes les 5 s) met environ 15 s à rendre la dégradation visible.

## Analyse et limites

- Le slicing dynamique tient le SLA v2x là où le slicing statique le viole en permanence (file HTB pleine,
  latence × 40) ; le coût est une part plus grande de la capacité attribuée à v2x pendant la surcharge.
- Les slices sont isolées : chacune a sa propre UPF, la surcharge v2x n'affecte ni embb ni miot.
- La troisième augmentation (vers 135 Mbit/s) est excessive : la moyenne sur 10 s retarde le retour à la normale.
  Pistes : période de garde plus longue que la fenêtre de mesure, ou pas proportionnel à l'écart au SLA.
- La sonde mesure un seul UE par slice ; le délai de détection (≈ 15 s) est dominé par la chaîne de mesure.
- Pas de couche radio : seule la contention de débit dans l'UPF est représentée.
