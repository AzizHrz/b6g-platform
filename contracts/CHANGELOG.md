# Contrats B6G — journal des versions

Règles (§ 6.14 du plan maître) : toute modification de `contracts/` ou de `config/scenario.yaml` passe par une
branche `common/<sujet>` et une *pull request*, avec une entrée ici. Ajout compatible = version mineure ;
changement incompatible = version majeure, annoncée 48 h avant, ancienne version servie une semaine.
Tag Git correspondant : `contracts-<version>`.

## À paraître

<!-- Une ligne par pull request : « - <interface> : <changement> (#PR) ». En cas de conflit, garder toutes les lignes. -->

## 1.0.0 — 2026-11-17 (INT0)

Première version gelée.

| Interface | Fichier | Contenu |
| --- | --- | --- |
| I-01 Scénario | `scenario.schema.json`, `../config/scenario.yaml` | PLMN 001/01, 3 slices (embb SST 1, v2x SST 4, miot SST 3), 30 UEs, profils de trafic, niveaux Edge/Fog/Cloud, liens, ports, capacité totale 150 Mbit/s |
| I-02 Métriques | `../mocks/platform/fake_exporter.py` (liste `METRICS`) | 16 métriques `b6g_*` et leurs étiquettes |
| I-03 MetricSnapshot | `metric-snapshot.schema.json` | `b6g.snapshot.v1` ; 3 slices et 3 niveaux toujours présents ; `null` si absent |
| I-04 Actionneur | `action-request.schema.json`, `action-result.schema.json`, `openapi/actuator.yaml` | 8 types d'action ; erreurs 400 / 404 / 409 en `application/problem+json` |
| I-05 Décision | `decide-request.schema.json`, `decision.schema.json`, `openapi/decision.yaml` | Politiques `qos-tree`, `placement`, `anomaly-reaction` |
| I-06 Jumeau | `whatif-request.schema.json`, `whatif-response.schema.json`, `openapi/twin.yaml` | `POST /v1/whatif` |
| I-07 Registre | `ledger-receipt.schema.json`, `ledger-verify.schema.json`, `openapi/ledger.yaml` | Registre chaîné SHA-256 (MAQUETTE de Fabric) |
| I-08 Événement | `event.schema.json` | `b6g.event.v1`, 12 types, `payload_sha256` du JSON canonique |
| I-09 Jeux de données | `dataset-manifest.schema.json`, `datasets.yaml` | Manifeste et colonnes de D1 à D8 |
| I-10 Inférence Edge | `openapi/edge-infer.yaml` | `POST /v1/infer` |

Précisions apportées par rapport au plan maître :

- `scenario.yaml` gagne `capacity.total_rate_mbps_max` (150), `nfs`, `deployments` et le port `fake_exporter` (9100), pour que les contrôles de l'Actionneur ne codent rien en dur.
- Le CPU d'un niveau (`tiers.<niveau>.cpu_ratio` du snapshot) est lu dans `b6g_nf_cpu_ratio{nf="<nœud k3d du niveau>"}` : aucune 17e métrique n'est ajoutée.
- `slice.bandwidth` : `ceil_mbps` est facultatif (par défaut, le plafond courant, au moins égal à `rate_mbps`).
- `noop` a pour cible `"-"`.
- Un ActionResult peut contenir `request` (l'action d'origine), utile pour le journal D8.
