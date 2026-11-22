# Atelier 25 — Green B6G et optimisation énergétique

| Rubrique | Contenu |
| --- | --- |
| Objectif | Identifier les sources de consommation, définir des indicateurs énergétiques, mesurer la consommation, mettre en veille les fonctions sous-utilisées et étudier le compromis énergie / QoS. |
| Étiquette de réalisme | **ÉMULÉ** (plateforme réelle, actions réelles) ; la **puissance est SIMULÉE** par un modèle (aucune mesure électrique) |
| Ce qui est réel | Charge CPU de chaque composant (cAdvisor), mise en veille par l'Actionneur (arrêt de fonctions, scale-to-zero), latence des slices |
| Ce qui est simulé et pourquoi | La puissance : P = P_idle + (P_max − P_idle) × charge CPU (`power_model.yaml`), faute de wattmètre sur M1 |
| Interfaces utilisées | I-02 (`b6g_nf_cpu_ratio`, `b6g_energy_power_watts`, `b6g_energy_joules_total`), I-04 (`deployment.replicas`, `slice.state`) |
| Comment lancer | `make up-energy up-green` ; `.venv/bin/python ateliers/a25/run_a25.py` |
| Résultat attendu | Proposer une stratégie de gestion énergétique |
| Résultat obtenu (source, date) | `results/tradeoff.csv`, `figures/tradeoff.png`, mesures du 2026-11-21 sur M1 |

## E01–E02 — Sources et indicateurs (T25.1)

| Indicateur | Définition |
| --- | --- |
| Puissance instantanée | `b6g_energy_power_watts{component}` (W) : P_idle + (P_max − P_idle) × charge CPU |
| Énergie cumulée | `b6g_energy_joules_total{component}` (J) : intégrale de la puissance dans le temps |
| Puissance totale | `b6g_energy_total_power_watts` (W) : somme de tous les composants |
| Efficacité | joules par bit servi (dérivable de l'énergie et de `b6g_slice_throughput_mbps`) |

Sources de consommation modélisées : fonctions réseau (AMF, SMF, UPF…), gNB, nœuds k3d des niveaux. Valeurs de
`power_model.yaml` choisies pour rendre les écarts mesurables : un nœud Cloud (25–150 W) coûte plus qu'une fonction
réseau (2–8 W) ; le gNB (5–25 W) est le poste le plus coûteux de la couche émulation.

## E03 — Mesure de la consommation (T25.2)

Exporteur `platform/energy/energy_exporter.py` (conteneur `energy` sur le réseau d'observabilité) : toutes les 5 s,
lit la charge CPU de chaque composant et publie puissance et énergie. Tableau de bord Grafana existant + requêtes
Prometheus. Répartition observée à vide (≈ 90 W au total) :

| Composant | Puissance |
| --- | --- |
| Nœud Cloud (k3d-agent-2) | 25,9 W |
| Nœud Fog (k3d-agent-1) | 16,2 W |
| Nœud Edge (k3d-agent-0) | 11,6 W |
| gNB | 5,1 W |
| Chaque UPF | ≈ 3,1 W |

L'infrastructure toujours active (3 nœuds + gNB ≈ 59 W) domine ; les fonctions réseau d'une slice pèsent quelques watts.

## E04–E06 — Ressources sous-utilisées et mise en veille (T25.3)

Politique `platform/energy/green_policy.py` (seuils dans `green_policy.yaml`), toutes les 10 s, **uniquement par
l'Actionneur** :

| Cible | Déclencheur de veille | Action | Réveil |
| --- | --- | --- | --- |
| `b6g-edge-infer` (Cloud) | < 0,1 requête/s | `deployment.replicas 0` (scale-to-zero) | > 0,5 requête/s |
| slice `miot` | débit < 0,05 Mbit/s | `slice.state active=false` (arrêt SMF + UPF) | débit > 0,2 Mbit/s |

Une métrique absente (compteur de requêtes jamais créé) est traitée comme « inactif ». Période de garde de 20 s par
cible pour éviter les oscillations.

## E07–E08 — Compromis énergie / QoS (T25.4)

Deux régimes, 35 s chacun, la slice v2x restant chargée (`results/tradeoff.csv`, `figures/tradeoff.png`) :

| Régime | Puissance totale | Puissance UPF miot | Latence p95 v2x | SLA v2x (20 ms) |
| --- | --- | --- | --- | --- |
| Sans sobriété | 89,9 W | 3,1 W | 2,15 ms | tenu |
| Avec sobriété | **85,1 W** | **0 W** | 2,14 ms | tenu |

- **Économie : 4,8 W (5,3 %)** sans dégradation de la QoS des slices actives : la mise en veille porte sur des
  fonctions inactives (slice miot, edge-infer), la slice v2x n'est pas touchée.
- L'économie est modeste parce que l'infrastructure toujours active (nœuds, gNB) représente les deux tiers de la
  consommation : seule la part « fonctions de slice » est récupérable à la demande.
- Le réveil (reprise de la slice, réattachement des UEs) coûte quelques secondes : la mise en veille convient à des
  services à activité intermittente (IoT la nuit, inférence Edge sans requêtes), pas à un trafic continu.

## Stratégie proposée (A25-R)

Piloter l'énergie comme une ressource, via l'Actionneur : mettre en veille les slices et les applications dont
l'activité tombe sous un seuil, les réveiller dès que la charge revient, et garder intactes les slices sous SLA strict
(v2x). Gain mesuré de 5 % de la puissance modélisée sans impact QoS ; gain potentiel plus élevé si l'infrastructure
elle-même (nœuds) peut être consolidée aux heures creuses.
