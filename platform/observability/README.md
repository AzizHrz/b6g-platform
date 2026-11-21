# M03 — Observabilité (W1.3)

| Service | Version | Port | Rôle |
| --- | --- | --- | --- |
| Prometheus | 2.55.1 | 9090 | Collecte toutes les 5 s, rétention 15 jours, règles `b6g_*` (`rules/b6g.rules.yml`) |
| Pushgateway | 1.11.1 | 9091 | Reçoit latence et perte des sondes trafficgen |
| cAdvisor | 0.55.1 | — | CPU et mémoire de chaque conteneur du projet `b6g-core` |
| Grafana | 10.4.19 | 3000 | Tableaux de bord « B6G — Plateforme v0 (INT1) » et « B6G — Multi-UE et congestion (atelier 4) » (seuils SLA du scénario), lecture anonyme |

## Sources des métriques I-02 à INT1

| Métrique `b6g_*` | Source |
| --- | --- |
| `b6g_ue_registered` | Règle : somme de `fivegs_amffunction_rm_registeredsubnbr` (AMF) |
| `b6g_slice_sessions{slice}` | Règle : `ues_active` de la SMF de chaque slice |
| `b6g_slice_throughput_mbps{slice,direction}` | Règle : débit des compteurs d'octets de `ogstun` publiés par l'Actionneur |
| `b6g_slice_latency_ms{slice,quantile}`, `b6g_slice_loss_ratio{slice}` | Sondes `platform/trafficgen/probe.py` → Pushgateway |
| `b6g_slice_bw_limit_mbps{slice}`, `b6g_link_delay_ms{link}`, `b6g_actions_total{type,status}` | Actionneur (`/metrics`) |
| `b6g_nf_cpu_ratio{nf}`, `b6g_nf_memory_bytes{nf}` | Règles sur cAdvisor |

Les six autres métriques du contrat (`b6g_k8s_replicas`, `b6g_app_request_latency_ms`, énergie, boucle, alertes)
apparaissent avec leurs producteurs (INT3 à INT5).

Les cibles Open5GS sont générées depuis le scénario (`generated/targets/open5gs.json`, par `platform/core/render.py`).

## Commandes

```bash
make up-obs        # après make up-core (le réseau b6g-core doit exister)
make obs-reload    # recharge la configuration et les règles de Prometheus
make down-obs
```

## Points d'attention

- **cAdvisor ≥ 0.52** est nécessaire avec Docker 29 : le magasin d'images containerd (`io.containerd.snapshotter.v1`)
  n'est pas reconnu par cAdvisor 0.49 (aucun conteneur identifié).
- **Pare-feu UFW** : Prometheus joint l'Actionneur sur l'hôte (`host.docker.internal:8081`). Avec UFW actif,
  autoriser les réseaux Docker vers ce port (voir `docs/setup/SETUP_LOG.md`).

## Export du jeu D1 `kpi_timeseries` (W1.4, I-09)

`tools/prom_export.py` lit les noms `b6g_*` dans Prometheus (`query_range`, pas de 5 s) et produit une ligne par
(instant, slice) avec les colonnes du contrat D1 : `ts, run_id, slice, throughput_mbps, latency_ms_p50,
latency_ms_p95, loss_ratio, bw_limit_mbps, sessions, upf_cpu_ratio, upf_memory_bytes`. Une valeur absente reste vide
(null). Le fichier (CSV ou Parquet) et son manifeste vont dans `datasets/raw/` (hors Git) ; le manifeste porte la
source, l'intervalle, le nombre de lignes, l'empreinte SHA-256 et le réalisme (ÉMULÉ par défaut).

```bash
make export-d1 RUN_ID=campagne-01 SINCE=2h               # CSV + contrôle CT-08 (tools/validate_dataset.py)
make export-d1 RUN_ID=campagne-01 SINCE=2h FORMAT=parquet
.venv/bin/python tools/prom_export.py --run-id essai --start 2026-11-21T15:00:00Z --end 2026-11-21T15:30:00Z
```

Premier export réel (2026-11-21, 3 h de mesures des ateliers 3, 4 et 6) : 6 483 lignes, contrôle CT-08 conforme,
2 valeurs de latence absentes (laissées vides). Tests sans plateforme : `tests/unit/test_prom_export.py`.
