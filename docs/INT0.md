# Jalon INT0 — contrats 1.0.0, scénario, mocks

**Passage :** CT-01, CT-03 à CT-08 verts contre les mocks (`make test-contracts`). Ensuite : tag `int0` et `contracts-1.0.0` sur `main`.

| Test | Vérifie | Fichier |
| --- | --- | --- |
| CT-01 | `config/scenario.yaml` conforme au schéma et aux règles (capacité, sous-réseaux, liens) | `tests/contract/test_ct01_scenario.py` |
| CT-02 (mock) | 16 métriques `b6g_*` et leurs étiquettes sur `fake_exporter` ; version réelle à INT1 | `test_ct02_metrics.py` |
| CT-03 | `snapshot.build()` : 3 slices, 3 niveaux, `null` si absent, pour 5 profils | `test_ct03_snapshot.py` |
| CT-04 | Actionneur : 10 exemples valides → 200 en `dry_run` sans changer l'état ; 10 invalides → 400 / 404 / 409 | `test_ct04_actuator.py` |
| CT-05 | Décision : 3 politiques × 5 snapshots → Decision valide, actions acceptées par l'Actionneur | `test_ct05_decision.py` |
| CT-06 | Jumeau : `whatif` valide pour les 5 snapshots | `test_ct06_twin.py` |
| CT-07 | Registre : poster, relire, vérifier (`hash_match`), doublon 409, falsification détectée | `test_ct07_ledger.py` |
| CT-08 | D1 à D8 : manifeste valide, colonnes et types, empreinte SHA-256, 100 lignes | `test_ct08_datasets.py` |
| — | Schémas JSON et OpenAPI 3.1 bien formés, version 1.0.0 | `test_contracts_files.py` |

## Mocks livrés

| Mock | Remplace | Port | Réalisme |
| --- | --- | --- | --- |
| `mocks/platform/fake_exporter.py` | Prometheus + métriques `b6g_*` (profils day, peak, incident, night, satellite) | 9100 | SYNTHÉTIQUE |
| `platform/actuator` (backend `memory`) | Actionneur réel (`tc`, `kubectl`) | 8081 | Code réel, aucune commande système |
| `mocks/platform/mock_ledger.py` | Hyperledger Fabric | 8082 | MAQUETTE (journal chaîné SHA-256) |
| `mocks/intelligence/mock_decision.py` | Service Décision (politiques à seuils) | 8090 | Règles |
| `mocks/intelligence/mock_twin.py` | Jumeau numérique (latence ∝ 1/débit) | 8091 | Modèle naïf |
| `datasets/samples/` | D1 à D8 (100 lignes chacun) | — | SYNTHÉTIQUE / SIMULÉ |

## Ce qui vient ensuite (INT1)

Plateforme v0 : Open5GS + UERANSIM (3 slices, 30 UEs), Prometheus avec les règles `b6g_*`, backend `tc` de l'Actionneur. Le même `snapshot.build()` pointera sur le vrai Prometheus (port 9090) au lieu de `fake_exporter` (9100).
