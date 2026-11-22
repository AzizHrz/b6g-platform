# Atelier 26 — Optimisation dynamique et réseau B6G autonome (boucle MAPE-K)

| Rubrique | Contenu |
| --- | --- |
| Objectif | Construire une boucle autonome Monitor → Analyze → Decide → Act → Learn et démontrer son fonctionnement. |
| Étiquette de réalisme | **ÉMULÉ** (plateforme et actions réelles) ; Décision et Jumeau sont les **mocks** de l'équipe 2 (réels à INT5) |
| Ce qui est réel | Instantané Prometheus, détection de violation, appel aux API Décision et Jumeau, application par l'Actionneur, journal D8, événements au registre Fabric, compteur de boucle |
| Ce qui est simulé et pourquoi | L'intelligence (Décision `mock_decision`, Jumeau `mock_twin`) n'est pas encore livrée par l'équipe 2 |
| Interfaces utilisées | I-03 (snapshot), I-05 (Décision), I-06 (Jumeau), I-04 (Actionneur), I-07 (événements `loop.iteration`), D8 (`actions_log`) |
| Comment lancer | `make up-core up-obs up-actuator up-probes up-ledger up-mocks-ia` puis `.venv/bin/python ateliers/a26/run_a26.py` |
| Résultat attendu | Une boucle MAPE-K fonctionnelle, démontrée sur une dégradation contrôlée |
| Résultat obtenu (source, date) | `results/loop.csv`, `datasets/raw/actions_log.csv` (D8), mesures du 2026-11-22 sur M1 |

## La boucle MAPE-K (`platform/loop/`)

| Phase | Module | Rôle |
| --- | --- | --- |
| **Monitor** | `monitor.py` | Instantané de l'état réseau toutes les 5 s (`snapshot.build`, I-03) |
| **Analyze** | `analyze.py` | Détection des violations de SLA (latence p95, débit minimal, perte) |
| **Decide** | `decide.py` | Actions obtenues de l'API Décision (I-05), **validées par le Jumeau (I-06)** comme rôle de sécurité : une action n'est retenue que si le jumeau ne prévoit **aucune nouvelle violation** (elle peut améliorer sans tout résoudre en une étape) |
| **Act** | `act_learn.py` | Application par l'Actionneur (I-04), au plus 3 actions par itération |
| **Learn** | `act_learn.py` | Mesure du SLA avant/après, ligne D8, événement `loop.iteration` au registre, compteur `b6g_loop_iterations_total` poussé à la Pushgateway |

Issue de chaque itération : `no_action` (pas de violation), `resolved` (SLA rétabli), `rejected` (action refusée par le
jumeau, ou appliquée sans rétablir le SLA dans la fenêtre).

## Démonstration (T26.4)

Dégradation contrôlée de la slice v2x (plafond abaissé + charge TCP descendante qui le sature), puis 10 itérations de la
boucle, sans intervention (`results/loop.csv`, `datasets/raw/actions_log.csv`).

**Mécanisme vérifié de bout en bout :**

- la boucle tourne **10 itérations consécutives sans intervention** (critère A26-R) ;
- Monitor/Analyze détectent la violation (latence p95 v2x > 20 ms) à chaque itération ;
- Decide obtient une décision de l'API Décision (un `decision_id` par itération) ;
- le Jumeau valide l'action (aucune nouvelle violation prévue) ;
- Act applique une action `slice.bandwidth` réelle (journal D8 : débit v2x relevé 6 → 9 → 13,5 Mbit/s…) ;
- Learn journalise : lignes D8 avec `sla_ok_before`/`sla_ok_after`, événements `loop.iteration` inscrits dans Fabric,
  compteur `b6g_loop_iterations_total{outcome}` dans Prometheus.

**Résultat et limite (honnête) :** la boucle corrige à chaque itération mais ne ramène pas le SLA strict de la slice
v2x (p95 ≤ 20 ms) à zéro violation dans cette configuration. Raison : la politique de décision disponible est le
**mock `qos-tree`**, qui augmente le **débit garanti** (`rate`) sans relever le **plafond** (`ceil`) ; or, sous charge,
la latence de la slice est dominée par le remplissage de la file HTB (effet « bufferbloat » documenté aux ateliers 3,
4 et 6), que seul un relèvement du plafond fait baisser. Le Jumeau, dont le modèle suppose latence ∝ 1/débit, ne
reflète pas ce comportement de file.

Ce que cela montre : **la boucle MAPE-K fonctionne ; son efficacité dépend de la qualité de la politique de décision et
du jumeau.** La restauration autonome effective du SLA est déjà démontrée à l'**atelier 6** (slice-autoscaler relevant le
plafond : latence p95 v2x 137 ms → 0,38 ms, T06.4) ; la boucle complète avec Décision et Jumeau **réels** sera validée à
**INT5** (services livrés par l'équipe 2). La version mock sert ici à éprouver la chaîne Monitor → Analyze → Decide →
Act → Learn et ses enregistrements, indépendamment de la qualité du modèle.

## Journaux produits

- **D8** `datasets/raw/actions_log.csv` : une ligne par action (type, cible, params, `decision_id`, SLA avant/après).
- **Registre** : un événement `b6g.event.v1` de type `loop.iteration` par itération, inscrit dans Fabric (I-07).
- **Métrique** : `b6g_loop_iterations_total{outcome}` (Pushgateway → Prometheus).
