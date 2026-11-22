# M06 — Cluster Kubernetes k3d (atelier 8)

Réalisme : **ÉMULÉ** (k3s réel ; nœuds = conteneurs Docker sur M1).

| Fichier | Rôle |
| --- | --- |
| `cluster.yaml` | Cluster `b6g` : 1 serveur, 3 agents étiquetés `b6g/tier=edge|fog|cloud` (nœuds du scénario), API :6443, registre `b6g-plat:5000` |
| `apps/echo-app/` | Déploiement, service NodePort 30080 et HPA de `b6g-echo-app` (niveau Cloud) |
| `values/render.py` | Valeurs Helm d'Open5GS et de UERANSIM générées depuis le scénario (sortie : `generated/`, non versionnée) |
| `prometheus-reader.yaml` | Compte de service en lecture seule pour la collecte Prometheus |
| `render_obs.py` | Collecte Prometheus du cluster et règles `b6g_k8s_replicas`, CPU des niveaux |

Outils (hors dépôt, `~/b6g-ext/bin`) : k3d 5.7.4, kubectl 1.30.6, Helm 3.16.2.

```bash
make up-k8s                                    # cluster
kubectl apply -k platform/k8s/apps/echo-app    # application de test + HPA
make k8s-core                                  # Open5GS + gNB / UE dans l'espace b6g-5gc
make k8s-obs                                   # kube-state-metrics + collecte Prometheus (make k8s-obs-off pour retirer)
make k8s-status ; make k8s-core-status
make k8s-core-down ; make down-k8s             # arrêt (faire make k8s-obs-off avant down-k8s)
```

Résultats et dépannage : `ateliers/a08/README.md`, `docs/setup/SETUP_LOG.md`.
