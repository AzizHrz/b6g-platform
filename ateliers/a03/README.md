# Atelier 3 — Enregistrement, sessions et connectivité

| Rubrique | Contenu |
| --- | --- |
| Objectif | Déployer le cœur 5G et le RAN, enregistrer les UEs, établir les sessions PDU, mesurer la connectivité de référence par slice, observer la signalisation et identifier les limites de la plateforme. |
| Étiquette de réalisme | **ÉMULÉ** (Open5GS 2.7.7 et UERANSIM 3.2.8 réels, signalisation et trafic réels ; couche radio simulée par UERANSIM) |
| Ce qui est réel | NGAP sur SCTP, NAS-5GS, SBI HTTP/2, PFCP, GTP-U, sessions PDU, trafic IP, limitation tc, mesures iperf3 / ping |
| Ce qui est simulé et pourquoi | Interface radio : UERANSIM remplace PHY / MAC / RLC par une liaison UDP (port 4997) entre UE et gNB |
| Interfaces utilisées | I-01 (scénario), I-02 (métriques), D2 measure.v1 (`results/baseline.csv`) |
| Comment lancer | `make up-core up-obs up-actuator` puis `.venv/bin/python ateliers/a03/run_a03.py` ; captures : voir § E08 |
| Résultat attendu | Tableau de référence par slice (débit, RTT, perte, temps d'attachement) et signalisation commentée |
| Résultat obtenu (source, date) | `results/`, `figures/`, mesures du 2026-11-21 sur M1 |

## E01–E03 — Cœur, RAN et sessions (T03.1)

Réalisé au jalon INT1 (`platform/core/`, `docs/INT1.md`) : 11 fonctions Open5GS dont une SMF et une UPF par slice,
1 gNB, 30 UEs, 30 sessions PDU (10 par slice), métrique `b6g_slice_sessions` = 10 pour chaque slice.

## E04–E07 — Mesures de référence (T03.2)

3 répétitions. Chaque répétition redémarre les 30 UEs (attachement mesuré dans les journaux UERANSIM, de la dernière
« Sending Initial Registration » à « PDU Session establishment is successful »), puis mesure à vide, par slice et pour
un UE : débit TCP descendant et montant (10 s, iperf3), 50 ping vers la passerelle de l'UPF.
568 mesures au format measure.v1 (`results/baseline.csv`), synthèse `results/baseline_summary.csv` :

| Slice | Plafond (ceil) | Débit DL moyen | Débit UL moyen | RTT moyen | RTT p95 | Perte | Attachement médian | Attachement p95 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| embb | 100 Mbit/s | 96,25 Mbit/s (σ 0,0) | 82,99 Mbit/s (σ 3,3) | 2,36 ms | 3,29 ms | 0 | 65 ms | 81 ms |
| v2x | 40 Mbit/s | 38,48 Mbit/s (σ 0,0) | 24,88 Mbit/s (σ 2,6) | 2,25 ms | 3,31 ms | 0 | 61 ms | 76 ms |
| miot | 10 Mbit/s | 9,54 Mbit/s (σ 0,0) | 9,57 Mbit/s (σ 0,05) | 2,25 ms | 3,23 ms | 0 | 66 ms | 78 ms |

90 attachements sur 90 réussis. Le débit descendant est fixé par la limitation HTB (à −4 % du plafond pour TCP) et
reproductible d'une répétition à l'autre. Le RTT est le même pour les trois slices : sans couche radio ni charge, il
ne reflète que le traitement logiciel du gNB et de l'UPF.

## E08 — Signalisation observée (T03.3)

Captures `tcpdump` (image Open5GS) dans les espaces réseau de `gnb`, `amf`, `smf-v2x` et `upf-v2x` pendant le
ré-enregistrement des 10 UEs v2x et un ping ; décodage `tshark` 4.4.19 (`decode_captures.py`).

```bash
for nf in gnb amf smf-v2x upf-v2x; do
  docker run -d --name cap-$nf --net container:$nf --cap-add NET_RAW --cap-add NET_ADMIN -u root \
    --entrypoint tcpdump gradiant/open5gs:2.7.7 -i any -s 0 -U -w /tmp/$nf.pcap
done
docker restart ue-v2x && docker exec ue-v2x ping -I uesimtun0 -c 5 8.8.8.8
for nf in gnb amf smf-v2x upf-v2x; do
  docker stop cap-$nf && docker cp cap-$nf:/tmp/$nf.pcap ~/b6g-data/a03/pcap/ && docker rm cap-$nf
done
.venv/bin/python ateliers/a03/decode_captures.py
```

Les fichiers `.pcap` restent hors du dépôt (`~/b6g-data/a03/pcap/`, 600 Ko) ; le dépôt contient leur décodage :
`results/captures/sequence_ue.csv` (un UE), `results/captures/resume.csv` (582 messages) et
`figures/sequence_enregistrement.png`.

Séquence d'un UE v2x (IMSI 001010000000020), du premier message à la session prête : **50,5 ms**.

| t (ms) | Interface | Message | Commentaire |
| --- | --- | --- | --- |
| 0,0 | N2 / N1 | InitialUEMessage + Registration request | Le gNB transmet la première demande NAS de l'UE à l'AMF |
| 12,8 → 24,8 | N1 | Authentication request / response | 5G-AKA ; l'AMF interroge l'AUSF (SBI `nausf-auth`) |
| 28,4 → 29,6 | N1 | Security mode command / complete | Activation de l'intégrité (NIA2) et du chiffrement (NEA0, nul : messages lisibles) |
| 31,5 → 36,3 | SBI | `GET /nudm-sdm/v2/imsi-…/am-data`, `smf-select-data`, `ue-context-in-smf-data` | Profil d'abonné lu dans l'UDM |
| 39,1 → 39,3 | N2 / N1 | InitialContextSetup + Registration accept | Contexte UE créé dans le gNB |
| 43,1 | N1 | Registration complete, PDU session establishment request (DNN v2x, S-NSSAI 4-000004) | |
| 48,5 → 48,8 | N4 | PFCP Session Establishment Request / Response (UE 10.46.1.52) | La SMF v2x programme l'UPF v2x |
| 49,1 | SBI | `POST /namf-comm/v1/ue-contexts/imsi-…/n1-n2-messages` | La SMF renvoie l'acceptation à l'AMF |
| 49,5 → 50,5 | N2 / N1 | PDUSessionResourceSetup + PDU session establishment accept | Tunnel GTP-U créé, adresse IP attribuée |
| + 5,4 s | N3 | GTP-U (G-PDU) : Echo request / reply | Trafic utilisateur encapsulé entre gNB et UPF |

Comptages sur la fenêtre de capture : 10 établissements, 10 modifications et 10 suppressions de session PFCP
(remplacement des anciennes sessions des 10 UEs), 130 paquets GTP-U vus par le gNB, 48 par l'UPF v2x.

## E09 — Limites identifiées (T03.4)

| # | Limite | Constat | Impact sur les ateliers suivants |
| --- | --- | --- | --- |
| L1 | **Pas de couche radio** | UERANSIM remplace l'interface air par une liaison UDP ; RTT UE → UPF de 2 à 3 ms, identique pour les trois slices | Latences et débits radio non représentatifs (ateliers 5, 14, 15, 16) : la radio relève de la simulation (équipe 2) ; les comparaisons portent sur les mécanismes, pas sur les valeurs absolues |
| L2 | **Pas de priorisation par 5QI dans l'UPF** | Le 5QI 83 de v2x est signalé, mais aucun traitement prioritaire n'est mesurable : les trois slices ont le même RTT à vide | La différenciation de service repose sur la limitation tc par slice (Actionneur), une UPF par slice (ateliers 4, 6, 26) |
| L3 | **Sens montant limité par un policer** | Le policer rejette au-delà de `ceil` sans file : TCP montant à 24,9 Mbit/s pour un plafond de 40 (v2x), 83 pour 100 (embb) | Les décisions de dimensionnement doivent viser le sens descendant ou prévoir une marge en montant (ateliers 6, 26) ; une file montante (IFB) est une amélioration possible |
| L4 | **Rupture de lien radio simulée sous charge** | Sous forte charge, un UE a perdu son lien avec le gNB (« Radio link failure ») et son tunnel est resté inutilisable jusqu'au redémarrage de son conteneur (atelier 4) | Les campagnes longues (boucle de l'atelier 26, démonstration de l'atelier 28) doivent surveiller le nombre de sessions (`b6g_slice_sessions`) et relancer les UEs perdus |
| L5 | **Resynchronisation SQN à chaque redémarrage d'UE** | UERANSIM repart d'un SQN nul : échec d'authentification puis resynchronisation à chaque redémarrage | Allonge le temps d'attachement mesuré ; à mentionner dans toute mesure d'attachement (atelier 3, ateliers 12 et 14) |
| L6 | **Chaîne de mesure lente** | Latence vue par Prometheus environ 15 s après la dégradation (sonde toutes les 5 s, Pushgateway, collecte 5 s) | Délai de réaction de la boucle borné par la mesure (ateliers 6, 26) ; sondes plus fréquentes ou métriques directes à étudier |
| L7 | **Pas de mobilité ni de handover** | UERANSIM ne gère pas le handover entre gNB | Handover et mobilité traités par simulation ns-3 / SUMO (équipe 2, ateliers 12 et 14) |
| L8 | **Une seule machine** | Toutes les fonctions partagent le processeur et le noyau de M1 ; aucun délai de transport réel | Les délais Edge / Fog / Cloud et NTN sont ajoutés par `link.netem` (Actionneur v2, ateliers 10 et 17) |
