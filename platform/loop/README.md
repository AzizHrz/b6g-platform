# M10 — Boucle de contrôle (v0 : slice-autoscaler, T06.4)

Réalisme : **ÉMULÉ** (actions réelles sur la plateforme par l'Actionneur).

`slice_autoscaler.py` est la première version de la boucle autonome : une règle à seuils, toutes les 5 s, qui lit
l'état par `b6g_common.snapshot.build()` (I-03) et agit **uniquement** par `POST /v1/actions` (I-04).

| Paramètre | Valeur par défaut | Rôle |
| --- | --- | --- |
| `period` | 5 s | Période de la boucle |
| `window_s` | 10 s | Fenêtre de moyenne du snapshot |
| `busy_ratio` | 0,9 | Débit ≥ 90 % de `ceil` : slice congestionnée |
| SLA latence | `config/scenario.yaml` | Latence p95 au-dessus du SLA : slice congestionnée |
| `step` | 1,5 | Facteur d'augmentation de `ceil` (et de `rate` dans la capacité restante) |
| `cooldown_s` | 10 s | Période de garde entre deux actions sur une même slice |
| `idle_ratio` | 0,3 | Retour aux valeurs du scénario quand le débit retombe sous 30 % du `rate` initial |

```bash
make up-autoscaler        # journal JSON des décisions : .run/autoscaler.log
make stop-autoscaler
.venv/bin/python platform/loop/slice_autoscaler.py --once   # un seul cycle
```

Tests sans plateforme : `tests/unit/test_slice_autoscaler.py`. Résultats et analyse : `ateliers/a06/README.md`.
La boucle MAPE-K complète (Monitor, Analyze, Decide par l'API Décision, Act et Learn) est prévue à l'atelier 26.
