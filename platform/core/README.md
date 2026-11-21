# M01 — Cœur 5G Open5GS et RAN UERANSIM (T03.1)

Réalisme : **ÉMULÉ** (logiciels et paquets réels, sans couche radio).

## Contenu

| Élément | Détail |
| --- | --- |
| Cœur | Open5GS 2.7.7 (image `gradiant/open5gs:2.7.7`) : NRF, AUSF, UDM, UDR, PCF, NSSF, BSF, AMF, et **une SMF + une UPF par slice** (`smf-embb`, `upf-embb`, …) |
| RAN | UERANSIM 3.2.8 (image `gradiant/ueransim:3.2.8`) : 1 gNB à 3 S-NSSAI, 3 conteneurs d'UE (`ue-<slice>`) lançant chacun 10 UEs (`nr-ue -n 10`) |
| Base | MongoDB 6.0, 30 abonnés (IMSI 001010000000001 à 030) |
| Mesure | Conteneur `iperf` (serveur iperf3) sur le réseau de données, joint à travers la NAT de chaque UPF |
| Réseau | Pont Docker `b6g-core` (172.22.0.0/24), adresses fixes ; sous-réseaux UE : embb 10.45.0.0/16, v2x 10.46.0.0/16, miot 10.47.0.0/16 |

Toutes les valeurs (PLMN, TAC, S-NSSAI, DNN, sous-réseaux, 5QI, nombre d'UEs) viennent de `config/scenario.yaml`.
`render.py` génère les configurations dans `platform/core/generated/` et `platform/ran/generated/` (non versionnés).
Les clés K / OPc sont les valeurs de test publiques de UERANSIM : aucune carte SIM réelle.

## Commandes

```bash
make up-core        # génère, démarre MongoDB, charge les abonnés, puis cœur, gNB et UEs
make core-status    # état des conteneurs et nombre d'interfaces uesimtun par conteneur d'UE (10 attendues)
make core-logs
make down-core
```

Vérification manuelle du plan utilisateur :

```bash
docker exec ue-v2x ping -I uesimtun0 -c 3 10.46.0.1     # passerelle de l'UPF v2x
docker exec ue-v2x ping -I uesimtun0 -c 3 8.8.8.8       # sortie N6
```

## Points d'attention

- L'image Open5GS s'exécute sous l'utilisateur `open5gs` (uid 999). Les UPF tournent donc en `root`
  (création de `ogstun` et des règles NAT, `platform/core/upf-entrypoint.sh`).
- Le 5QI 83 de la slice v2x (GBR à délai critique) est accepté par Open5GS 2.7.7 pour la session par défaut.
- Après une modification de `config/scenario.yaml` : `make up-core` régénère et applique.
