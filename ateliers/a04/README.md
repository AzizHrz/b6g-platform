# Atelier 4 — Gestion de plusieurs UEs et services B6G

| Rubrique | Contenu |
| --- | --- |
| Objectif | Faire fonctionner 30 UEs et 3 services simultanément, mesurer les performances par UE et par slice sous 3 niveaux de charge, identifier la congestion et adapter les ressources par l'Actionneur. |
| Étiquette de réalisme | **ÉMULÉ** (Open5GS et UERANSIM réels, trafic iperf3 et ping réels ; pas de couche radio) |
| Ce qui est réel | 30 sessions PDU, trafic à travers gNB, GTP-U et l'UPF de chaque slice, limitation HTB, métriques Prometheus et cAdvisor, action `slice.bandwidth` |
| Ce qui est simulé et pourquoi | Interface radio absente (UERANSIM) ; les profils d'application sont reproduits par iperf3 (débit, taille de paquet, fréquence) |
| Interfaces utilisées | I-01 (profils, UEs), I-02 (métriques), I-04 (Actionneur), D2 measure.v1 (`results/measures.csv`) |
| Comment lancer | `make up-core up-obs up-actuator up-probes` puis `.venv/bin/python ateliers/a04/run_a04.py` |
| Résultat attendu | Vision globale du comportement d'un réseau multi-utilisateurs et multi-services |
| Résultat obtenu (source, date) | `results/*.csv`, `figures/*.png`, mesures du 2026-11-21 sur M1 (Debian 13, Open5GS 2.7.7, UERANSIM 3.2.8) |

## E01–E03 — UEs, profils et applications (T04.1)

30 UEs (10 par slice, IMSI 001010000000001 à 030) et 3 profils définis dans `config/scenario.yaml` § `profiles` :

| Profil | Slice | Application | Protocole | Sens | Débit / taille / fréquence par UE |
| --- | --- | --- | --- | --- | --- |
| `embb-video` | embb | flux vidéo | TCP | descendant | 8 Mbit/s |
| `v2x-cam` | v2x | messages CAM | UDP | montant | 300 octets à 10 Hz (24 kbit/s) |
| `miot-sensor` | miot | capteur | UDP | montant | 100 octets à 1 Hz (0,8 kbit/s) |

## E04–E05 — Trafics simultanés et mesures (T04.2)

Les 30 UEs émettent en même temps pendant 20 s, à trois niveaux de charge (× 0,5, × 1, × 2 des profils) ;
un `ping` par UE vers la passerelle de son UPF mesure le RTT sous charge. 360 mesures au format measure.v1
(`results/measures.csv`), synthèse dans `results/summary.csv` :

| Niveau | Slice | Offert (Mbit/s) | Servi (Mbit/s) | RTT médian | Perte | CPU UPF | CPU gNB |
| --- | --- | --- | --- | --- | --- | --- | --- |
| faible | embb | 40,0 | 40,37 | 0,61 ms | 0 | 1,6 % | 1,9 % |
| faible | v2x | 0,12 | 0,12 | 0,34 ms | 0 | 0,8 % | |
| faible | miot | 0,004 | 0,004 | 0,29 ms | 0 | 0,7 % | |
| nominale | embb | 80,0 | 80,21 | 15,7 ms | 0 | 3,8 % | 4,3 % |
| nominale | v2x | 0,24 | 0,24 | 0,48 ms | 0 | 0,8 % | |
| nominale | miot | 0,008 | 0,008 | 0,38 ms | 0 | 0,8 % | |
| **forte** | **embb** | **160,0** | **96,26** | **91,5 ms** | 0,9 % | 7,4 % | 12,5 % |
| forte | v2x | 0,48 | 0,48 | 0,38 ms | 0 | 0,9 % | |
| forte | miot | 0,016 | 0,016 | 0,39 ms | 0 | 0,7 % | |

CPU : fraction d'un cœur, moyenne sur la durée du niveau (cAdvisor). Les octets d'en-tête ne sont pas comptés.

## E06–E07 — Congestions et utilisation des ressources (T04.3)

Tableau de bord Grafana « B6G — Multi-UE et congestion (atelier 4) »
(`platform/observability/grafana/dashboards/b6g-multiue.json`) : débit servi contre `rate`, latence p95 contre le SLA,
perte contre le SLA, CPU et mémoire du gNB et des UPF. Figures de l'expérience : `figures/debit_par_slice.png`,
`figures/latence_p95_par_slice.png`, `figures/cpu_nf.png`.

- **Point de congestion** : slice embb au niveau fort. 160 Mbit/s offerts, 96,3 Mbit/s servis (plafond `ceil` de
  100 Mbit/s, −2 % d'en-têtes), RTT médian multiplié par 150 (0,61 → 91,5 ms) : la file HTB de l'UPF embb est pleine.
- Déjà au niveau nominal (80 % du plafond), le RTT embb atteint 15,7 ms : les 10 flux TCP remplissent la file.
- **Isolation** : v2x et miot restent sous 0,6 ms à tous les niveaux. Chaque slice a sa propre UPF et sa propre
  limitation : la congestion embb ne se propage pas.
- **Ressources** : la congestion n'est pas due au calcul. Le gNB UERANSIM consomme 12,5 % d'un cœur et l'UPF embb
  7,4 % au niveau fort ; la limite est la consigne de débit de la slice.

## E08 — Adaptation des ressources (T04.4)

Action `slice.bandwidth` sur la slice congestionnée par l'API Actionneur, en respectant la capacité totale
(somme des `rate` ≤ 150 Mbit/s, `ceil` ≤ 150 Mbit/s), puis même charge forte (`results/adapt.csv`) :

| Phase | rate / ceil embb | Offert | Servi | RTT médian | Perte |
| --- | --- | --- | --- | --- | --- |
| Avant | 60 / 100 | 160 | 96,26 Mbit/s | 91,5 ms | 0,9 % |
| Après | 125 / 150 | 160 | **143,86 Mbit/s (+49 %)** | 82,9 ms | 0,6 % |

Le débit servi suit le nouveau plafond (143,9 pour 150). La demande (160 Mbit/s) dépasse encore la capacité totale
de la plateforme : la file reste pleine et le RTT reste élevé. L'adaptation ne peut pas créer de la capacité ;
elle la redistribue entre slices. La valeur de 60 / 100 est rétablie à la fin de l'expérience.

## Résultat (A04-R)

- 30 UEs et 3 services fonctionnent simultanément ; les mesures par UE et par slice sont disponibles pour 3 niveaux.
- La congestion est localisée (slice embb, file HTB de son UPF), chiffrée et visible dans Grafana.
- L'Actionneur augmente le débit servi de 49 % sur la slice congestionnée, dans la limite de la capacité totale.

## Problèmes rencontrés

- **Rupture de lien radio simulée** : lors d'un essai sous forte charge, un UE embb (IMSI …007) a perdu son lien
  avec le gNB (« Radio link failure detected ») : UERANSIM simule le lien radio par des messages UDP entre UE et gNB,
  perdus sous charge. Le tunnel de cet UE est resté inutilisable ; redémarrage du conteneur `ue-embb`
  (`docker restart ue-embb`), puis nouvelle série complète (aucune rupture pendant la série retenue).
- **Client iperf3 bloqué** sur sa connexion de contrôle : délai de connexion de 5 s, arrêt des clients bloqués et mesure
  comptée en échec au lieu d'interrompre l'expérience (`platform/trafficgen/load.py`).
