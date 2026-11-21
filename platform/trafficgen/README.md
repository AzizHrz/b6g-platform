# M02 — trafficgen (T03.2)

Réalisme : **ÉMULÉ**.

`probe.py` mesure, toutes les 5 s, la latence (p50, p95) et la perte de chaque slice : 20 `ping` depuis le premier
UE de la slice (`uesimtun0` du conteneur `ue-<slice>`) vers la passerelle de son UPF. Les valeurs sont publiées dans
la Pushgateway sous les noms du contrat I-02 (`b6g_slice_latency_ms`, `b6g_slice_loss_ratio`).

```bash
make up-probes      # boucle en arrière-plan, journal dans .run/probes.log
make stop-probes
.venv/bin/python platform/trafficgen/probe.py --once   # une seule mesure
```

Débit : serveur iperf3 `iperf` sur le réseau `b6g-core`, par exemple pour la slice v2x en sens descendant :

```bash
UE=$(docker exec ue-v2x sh -c "ip -o -4 addr show uesimtun0 | awk '{print \$4}' | cut -d/ -f1")
docker exec ue-v2x iperf3 -c iperf -B "$UE" -R -t 5
```
