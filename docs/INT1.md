# Jalon INT1 — plateforme v0, métriques réelles, Actionneur v1

**Passage :** `tests/integration/test_int1.py` vert contre la plateforme réelle : CT-02 réel et une action
`slice.bandwidth` appliquée (plan maître § 9.3). Réalisme des mesures : **ÉMULÉ**.

## Démarrage

```bash
make up-core          # Open5GS + UERANSIM, 30 UEs
make up-obs           # Prometheus, Pushgateway, cAdvisor, Grafana
make up-actuator      # Actionneur v1, backend tc
make up-probes        # latence et perte par slice
make up-registry      # registre d'images :5000
B6G_PROM_URL=http://127.0.0.1:9090 B6G_ACTUATOR_URL=http://127.0.0.1:8081 .venv/bin/pytest -m int tests/integration/test_int1.py
```

Depuis M2 : mêmes variables avec `b6g-plat` (résolu par `/etc/hosts`) et les ports 9090 et 8081 ouverts vers M2.

## Contenu intégré

| Brique | Tâche | Livrable |
| --- | --- | --- |
| Cœur Open5GS 2.7.7 à 3 slices (une SMF et une UPF par slice), gNB et 30 UEs UERANSIM 3.2.8 | T03.1 | `platform/core/`, `platform/ran/`, `mk/core.mk` |
| Prometheus, Pushgateway, cAdvisor, Grafana ; règles `b6g_*` | W1.3 | `platform/observability/`, `mk/observability.mk` |
| Actionneur v1 réel : `slice.bandwidth` par tc HTB / policer dans l'UPF de la slice | W1.2 | `platform/actuator/b6g_actuator/backends.py` |
| Sondes de latence et de perte par slice | T03.2 (partiel) | `platform/trafficgen/probe.py`, `mk/trafficgen.mk` |
| Registre d'images local | T01.5 | `platform/registry/`, `mk/registry.mk` |

## Tests

| Test | Vérifie |
| --- | --- |
| `test_actionneur_backend_reel` | Actionneur sur le backend `tc`, initialisation sans erreur |
| `test_cibles_prometheus_actives` | Toutes les cibles de collecte à l'état `up` |
| `test_ct02_reel_metrique_et_etiquettes` (10) | Les 10 métriques produites à INT1, avec leurs étiquettes |
| `test_ct02_metriques_des_jalons_suivants` (6, ignorés) | Métriques dont le producteur arrive plus tard : k8s (INT3), application (INT3), énergie (S6), boucle (INT5), alertes (INT4+) |
| `test_30_ues_et_10_sessions_par_slice` | `b6g_ue_registered` = 30, `b6g_slice_sessions` = 10 par slice |
| `test_snapshot_reel_valide` | `snapshot.build()` sur le vrai Prometheus, conforme au schéma, latence et sessions présentes |
| `test_action_slice_bandwidth_appliquee` | Action `applied`, nouvelle limite visible dans Prometheus, retour à l'état initial |
| `test_debit_mesure_suit_le_plafond` | Débit descendant iperf3 à ± 10 % du plafond (10 Mbit/s) après l'action |

Tests unitaires du backend tc (sans Docker, lancés par `make test`) : `tests/unit/test_actuator_tc.py`.

## Limites connues

- Pas de couche radio (UERANSIM) : latences de l'ordre de 2 à 3 ms entre l'UE et l'UPF.
- Sens montant limité par un policer (rejet au-delà de `ceil`), pas par une file HTB.
- `make run-mocks` et `make up-actuator` utilisent le même port 8081 : ne lancer que l'un des deux.
- Une seule machine (M1) : `b6g-plat` et `b6g-intel` pointent vers 127.0.0.1 tant que M2 n'est pas raccordée.
