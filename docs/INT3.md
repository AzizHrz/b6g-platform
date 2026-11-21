# Jalon INT3 — cluster à trois niveaux, edge-infer, Actionneur v2

**Passage :** CT-09, CT-10 et `tests/integration/test_int3.py` (plan maître § 9.3). Résultat du 2026-11-21 sur M1 :
**12 tests réussis, 1 ignoré** (catalogue des données, livrable de l'équipe 2). Réalisme : ÉMULÉ, sauf l'image
edge-infer (MAQUETTE, voir ci-dessous).

## Démarrage

```bash
make up-core up-obs up-actuator up-probes up-registry      # plateforme INT1
make up-k8s k8s-namespaces k8s-connect k8s-obs             # cluster, espaces de noms, UPF reliées, collecte
kubectl apply -k platform/k8s/apps/echo-app
kubectl apply -k platform/k8s/apps/edge-infer-edge
.venv/bin/pytest -m int tests/integration/test_int3.py
```

Attendre 30 s avant de relancer `test_int1.py` : `test_int3` arrête puis relance la slice miot, et l'instantané
d'INT1 est une moyenne sur 30 s.

## Contenu intégré

| Brique | Livrable |
| --- | --- |
| Cluster k3d à trois niveaux (atelier 8) | `platform/k8s/cluster.yaml`, `platform/k8s/namespaces.yaml` |
| Gabarit de déploiement I-11 (Kustomize, variables imposées dans `params.env`) | `platform/k8s/apps/_template/` |
| edge-infer déployé par le gabarit sur l'Edge (NodePort 30092) et le Cloud (30093) | `platform/k8s/apps/edge-infer-edge/`, `edge-infer-cloud/` |
| Actionneur v2 : `slice.state`, `link.netem`, `deployment.replicas`, `deployment.placement`, `ue.isolate`, `ue.release` | `platform/actuator/b6g_actuator/backends.py` (version 2.0.0) |
| Accès restreint de l'équipe 2 (espaces `b6g-edge`, `b6g-fog`, `b6g-cloud`) | `platform/k8s/team2-access.yaml`, `make k8s-team2-kubeconfig` (fichier hors Git) |
| Atelier 10 (Edge / Fog / Cloud) | `ateliers/a10/` |

## Tests

| Test | Vérifie |
| --- | --- |
| `test_actionneur_v2` | Backend `tc`, version 2.x |
| `test_cluster_trois_niveaux` | Nœuds du scénario étiquetés edge / fog / cloud |
| `test_ct09_edge_infer_sur_l_edge` | CT-09 : 20 requêtes `/v1/infer` conformes au contrat I-10, latence serveur < 50 ms |
| `test_ct10_gabarit_dry_run_serveur` (4) | CT-10 : `kubectl apply -k --dry-run=server` pour le gabarit et chaque application |
| `test_link_netem_n6_mesure` | `link.netem` n6-v2x 30 ms : RTT UE → passerelle augmenté d'au moins 25 ms, puis rétabli |
| `test_deployment_replicas_et_placement` | 3 répliques prêtes ; pod déplacé sur l'Edge puis rendu au Cloud |
| `test_ue_isolate_puis_release` | UE isolé sans réponse, voisin non affecté, puis rétabli |
| `test_slice_state_arret_puis_reprise` | SMF et UPF arrêtées, puis reprise : UEs réattachés, limitation réappliquée |
| `test_metriques_k8s_et_liens` | `b6g_k8s_replicas`, latence d'edge-infer, `b6g_link_delay_ms` pour les 7 liens |
| `test_catalogue_des_donnees` | ignoré : `datasets/catalog.yaml` relève de l'équipe 2 (M18) |

## Écarts au plan

- **edge-infer** : l'équipe 2 n'a pas encore livré son image ; une version de remplacement conforme au contrat I-10
  (`platform/apps/edge-infer-stub`, règle à seuils, étiquette MAQUETTE) valide le chemin de déploiement et CT-09.
  Elle sera remplacée par `b6g-plat:5000/b6g/edge-infer:<version>` (seule la ligne `image` de `params.env` change).
- **ServiceMonitor** absent du gabarit (opérateur Prometheus non installé) : collecte par les annotations `prometheus.io/*`.
- **n6-<slice>** : netem appliqué à la file de la classe HTB de la slice dans l'UPF (sens descendant) ;
  **tier-<niveau>** : netem en sortie du nœud k3d (aller-retour ajouté = délai configuré).
