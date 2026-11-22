# Atelier 27 — Laboratoire de sécurité isolé et jeu étiqueté D7

| Rubrique | Contenu |
| --- | --- |
| Objectif | Monter un laboratoire 5G isolé sans route externe, y rejouer des attaques représentatives contre la plateforme, et produire un jeu de données étiqueté (D7 `security_labels`) pour l'entraînement de la détection par l'équipe 2. |
| Étiquette de réalisme | **ÉMULÉ** (cœur Open5GS et RAN UERANSIM réels, trafic d'attaque réel, sur un réseau Docker `internal` sans route externe) |
| Ce qui est réel | Cœur et RAN dupliqués dans le laboratoire, tunnels 5G des UEs, trafic normal de fond, inondation UDP et tempête de ré-enregistrements **routées par le tunnel**, captures tcpdump sur les UPF et l'AMF, étiquetage par UE et par fenêtre |
| Ce qui est simulé et pourquoi | Les attaquants et la victime sont des conteneurs du laboratoire (pas d'équipement tiers) ; le jeu est **ÉMULÉ**, jamais présenté comme un relevé de production |
| Interfaces utilisées | Contrat `contracts/datasets.yaml` (schéma D7) ; aucune interface temps réel (campagne hors ligne) |
| Comment lancer | `make up-lab` puis `make lab-run` (prérequis : plateforme à l'arrêt ou mémoire suffisante) |
| Résultat attendu | Un jeu D7 étiqueté `normal` / `udp_flood` / `reg_storm` / `scan`, avec captures `.pcap` et manifeste |
| Résultat obtenu (source, date) | `datasets/raw/security/{labels.csv, captures.json, labels.manifest.yaml, *.pcap}` (hors Git), campagne du 2026-11-22 sur M1 |

## Le laboratoire isolé (`platform/attack-lab/`, `mk/attack-lab.mk`)

Un second cœur Open5GS et un RAN UERANSIM complets, préfixés `lab-`, tournent sur le réseau Docker **`b6g-lab`** déclaré
`internal: true` : aucune route vers l'hôte ni vers l'extérieur. La campagne **refuse de s'exécuter** si ce réseau n'est
pas isolé (`platform/attack-lab/run_scenarios.py`, contrôle `Internal == true`). Conformément au plan, le laboratoire
d'attaque (atelier 27) ne s'exécute que sur ce réseau sans route externe.

| Rôle | Conteneurs |
| --- | --- |
| Cœur + RAN | `lab-mongo`, `lab-nrf`, `lab-ausf`, `lab-udm`, `lab-udr`, `lab-pcf`, `lab-nssf`, `lab-bsf`, `lab-smf-{embb,v2x,miot}`, `lab-upf-{embb,v2x,miot}`, `lab-amf`, `lab-gnb`, `lab-ue-{embb,v2x,miot}` |
| Attaque / victime | `lab-attacker-embb`, `lab-attacker-miot`, victime `lab-iperf` (serveur du réseau de données) |

## La campagne étiquetée (`run_scenarios.py`, `scenarios.yaml`)

Déroulement (`platform/attack-lab/scenarios.yaml`) : captures tcpdump sur l'interface `any` de chaque UPF du laboratoire
et de l'AMF ; trafic normal de fond (un ping par seconde de chaque UE vers la victime) ; puis chaque scénario, précédé
d'une fenêtre de trafic normal. Une ligne d'étiquette par UE et par fenêtre.

| Scénario | Étiquette | Déclenchement | Passe par le tunnel 5G ? |
| --- | --- | --- | --- |
| Inondation UDP | `udp_flood` | `iperf3 -u` depuis un UE miot, source liée à l'adresse du tunnel (`-B`) | **Oui** (socket normal routé par le tunnel) |
| Tempête de ré-enregistrements | `reg_storm` | redémarrages successifs du conteneur `lab-ue-v2x` (ré-attachements NGAP) | **Oui** (signalisation NGAP réelle) |
| Balayage de ports | `scan` | `nmap -sT` depuis l'attaquant embb | **Non** — voir « Limite connue » |

**Garde-fou d'honnêteté** : avant d'étiqueter une attaque applicative, le script lit le compteur `tx_packets` du tunnel
de l'UE et refuse de produire le jeu si moins de 10 paquets y sont passés (« trafic d'attaque non confirmé »). Aucune
attaque n'est étiquetée si elle n'a pas effectivement traversé la liaison 5G.

## Sorties

- `labels.csv` : colonnes `start_ts, end_ts, ue_id, src_ip, label`, conformes au schéma D7 de `contracts/datasets.yaml`.
- `captures.json` : un enregistrement par capture (`file, interface, bytes, sha256`).
- `labels.manifest.yaml` : identité D7, version, producteur, réalisme **ÉMULÉ**, empreinte, nombre de lignes, plage
  temporelle.
- `*.pcap` : captures par UPF et AMF. Toutes ces sorties sont sous `datasets/raw/security/` (**ignoré par Git**).

## Limite connue — capture du balayage `scan`

En l'état (2026-11-22), le scénario `scan` **n'est pas capturé à travers le tunnel 5G** et le jeu D7 est donc
**incomplet** pour cette classe :

- **Symptôme** : les captures UPF ne contiennent pas le trafic de balayage ; `lab-upf-embb.pcap` n'a pas de paquets TCP
  de scan.
- **Cause 1 — routage** : la victime est sur le même pont `b6g-lab` que l'attaquant ; le balayage par connexion
  (`nmap -sT`, sockets normaux) sort par l'interface directe `eth0` du conteneur (route connectée) au lieu du tunnel.
  La route `/32 dev uesimtunN` épinglée ne force pas le `connect()` de nmap sur le tunnel. Les inondations, elles,
  passent bien parce qu'`iperf3 -B <adresse-tunnel>` lie explicitement la source au tunnel.
- **Cause 2 — garde-fou trompé** : le compteur `tx_packets` du tunnel continue de monter à cause des pings de fond
  (1/s par UE), de sorte que le contrôle « ≥ 10 paquets » passe même quand le balayage lui-même contourne le tunnel.

**Correctif prévu (non appliqué pour l'instant, sur décision)** : (1) router le balayage par le tunnel de façon fiable
— par exemple isoler la victime pour qu'elle ne soit joignable **que** par la session PDU / la sortie N6, ou lancer le
balayage depuis un espace de noms dont la seule route vers la victime est le tunnel ; (2) faire compter au garde-fou les
seuls paquets du port d'attaque (hors ICMP de fond) pour qu'il ne puisse plus être trompé. Le motif qui fonctionne pour
l'inondation (`iperf3 -B <adresse-tunnel>`) sert de référence.

Tant que ce point n'est pas corrigé, les classes `udp_flood` et `reg_storm` du jeu D7 sont exploitables, la classe
`scan` ne l'est pas, et le tag **`int4` reste en attente** (voir `docs/INT4.md`).
