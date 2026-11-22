# Atelier 10 — Edge, Fog et Cloud Computing

| Rubrique | Contenu |
| --- | --- |
| Objectif | Définir les niveaux Edge, Fog et Cloud, déployer une application, mesurer sa latence depuis un UE selon le niveau d'exécution, analyser les ressources et déterminer l'emplacement optimal. |
| Étiquette de réalisme | **ÉMULÉ** (trafic réel UE → gNB → UPF → nœud k3d → pod ; distance des niveaux reproduite par netem) |
| Ce qui est réel | Chemin 5G complet, application `b6g-echo-app` dans Kubernetes, déplacement par l'Actionneur, 1 000 requêtes HTTP par niveau |
| Ce qui est simulé et pourquoi | Les trois niveaux sont trois nœuds k3d d'une même machine : leur éloignement est ajouté par `tc netem` (2, 10 et 40 ms aller-retour, scénario § tiers) ; leurs capacités CPU (2, 4, 8 cœurs) ne sont pas imposées aux nœuds |
| Interfaces utilisées | I-01 (`tiers`), I-04 (`link.netem`, `deployment.placement`), I-02 (`b6g_k8s_replicas`, `b6g_app_request_latency_ms`) |
| Comment lancer | `make up-k8s k8s-connect` puis `.venv/bin/python ateliers/a10/run_a10.py` |
| Résultat attendu | Comprendre l'influence de la localisation du calcul sur les performances |
| Résultat obtenu (source, date) | `results/latency_cloud.csv`, `results/latency_tiers.csv`, `figures/latency_tiers.png`, mesures du 2026-11-21 sur M1 |

## E01 — Définition des niveaux (T10.1)

| Niveau | Nœud k3d | Délai aller-retour ajouté | Capacité (scénario) | RTT mesuré UPF → nœud (ping) |
| --- | --- | --- | --- | --- |
| Edge | `k3d-b6g-agent-0` | 2 ms | 2 cœurs, 2 Go | 2,6 ms |
| Fog | `k3d-b6g-agent-1` | 10 ms | 4 cœurs, 4 Go | 12,2 ms |
| Cloud | `k3d-b6g-agent-2` | 40 ms | 8 cœurs, 8 Go | 40,1 ms |

Délais appliqués par l'Actionneur v2 (`link.netem` sur `tier-edge`, `tier-fog`, `tier-cloud` : netem en sortie de
l'interface du nœud) et vérifiés par ping. Les UPF sont reliées au réseau du cluster (`make k8s-connect`) : le trafic
des UEs atteint les nœuds par la sortie N6 de leur UPF.

## E02–E05 — Latence selon l'emplacement (T10.2, T10.3)

`b6g-echo-app` déplacée successivement sur chaque niveau par l'Actionneur (`deployment.placement`, nodeSelector
`b6g/tier`) ; service en `externalTrafficPolicy: Local` (requête servie par le nœud qui héberge le pod, sans détour par
un autre niveau). 1 000 requêtes HTTP séquentielles depuis un UE embb (`curl --interface uesimtun0`).

| Niveau | Requêtes (échecs) | RTT p50 | RTT p95 | RTT moyen | Déplacement du pod |
| --- | --- | --- | --- | --- | --- |
| Edge | 1 000 (0) | **6,27 ms** | 7,13 ms | 6,29 ms | 2,3 s |
| Fog | 1 000 (0) | 23,95 ms | 25,63 ms | 23,83 ms | 2,8 s |
| Cloud | 1 000 (0) | 85,27 ms | 87,08 ms | 85,02 ms | — (déjà sur place) |

Chaque requête coûte deux allers-retours (établissement de la connexion TCP, puis requête et réponse) : le RTT
applicatif vaut environ deux fois le délai du niveau, plus 2 à 5 ms de traversée du chemin 5G (UE, gNB, UPF).
Le passage du Cloud à l'Edge divise la latence par 13,6.

## E06–E07 — Analyse et emplacement optimal (T10.4)

| Slice | SLA de latence p95 | Edge (7,1 ms) | Fog (25,6 ms) | Cloud (87,1 ms) | Emplacement retenu |
| --- | --- | --- | --- | --- | --- |
| v2x | 20 ms | conforme | **non conforme** | non conforme | **Edge** |
| embb | 100 ms | conforme | conforme | conforme (marge de 13 ms) | Fog ou Cloud |
| miot | 500 ms | conforme | conforme | conforme | **Cloud** |

Règle de placement déduite des mesures :

1. une application dont le SLA de latence est inférieur à 4 × le délai du Fog (≈ 40 ms) va à l'Edge : seul l'Edge tient
   le SLA v2x de 20 ms ;
2. sinon, la placer au niveau le plus capacitaire qui respecte son SLA (Cloud pour miot, Cloud ou Fog pour embb),
   pour garder la capacité limitée de l'Edge (2 cœurs) aux services critiques ;
3. un déplacement coûte 2 à 3 s (création du pod sur le nouveau nœud, sonde de disponibilité) : c'est le délai minimal
   d'une décision de placement par la boucle autonome (atelier 26).

Ressources : le CPU des niveaux est publié (`b6g_nf_cpu_ratio{nf="k3d-b6g-agent-N"}`, rapporté à la capacité du niveau)
et visible dans le tableau de bord « B6G — Kubernetes k3d ». Limite : les nœuds k3d partagent le processeur de M1 ;
la capacité de chaque niveau (2, 4, 8 cœurs) est une valeur du scénario, non imposée au nœud. Les effets de saturation
d'un niveau ne sont donc pas reproduits ; seuls les effets de distance le sont.
