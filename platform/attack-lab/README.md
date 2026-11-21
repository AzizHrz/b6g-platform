# M11 — Laboratoire d'attaque isolé (T27.2, contribution de l'équipe 1 à l'atelier 27)

Réalisme : **ÉMULÉ**. Génère le jeu **D7** (`security_labels`) : captures de trafic normal et anormal **étiquetées**,
pour l'entraînement de la détection d'intrusion de l'équipe 2 (M24).

## Isolement

Le laboratoire est une copie autonome du cœur 5G et du RAN (préfixe `lab-`, projet Compose `b6g-lab`) sur un réseau
Docker **`internal: true`** (`10.230.0.0/24`) : aucune route vers l'hôte ni vers Internet. Il ne touche à aucun
élément de la plateforme principale (`b6g-core`, Prometheus, Actionneur, cluster k3d). `run_scenarios.py` refuse de
s'exécuter si le réseau n'est pas isolé.

| Élément | Détail |
| --- | --- |
| Cœur et RAN | mêmes slices, abonnés et UEs que le scénario (`render_lab.py` réutilise `platform/core/render.py`) |
| Attaquants | conteneurs `lab-attacker-embb` et `lab-attacker-miot` (hping3, nmap, tcpdump) partageant l'espace réseau d'un conteneur d'UE : ils émettent par le tunnel `uesimtunN`, comme un terminal compromis |
| Victime | serveur `lab-iperf` sur le réseau de données du laboratoire |

## Scénarios (`scenarios.yaml`)

| Étiquette | Description | Outil |
| --- | --- | --- |
| `normal` | trafic de fond : un ping par seconde de chaque UE vers la victime | ping |
| `udp_flood` | inondation UDP depuis un UE compromis | hping3 |
| `reg_storm` | tempête d'enregistrements : redémarrages successifs d'un conteneur d'UE (10 UEs) | docker restart |
| `scan` | balayage de ports de la victime depuis un UE | nmap |

```bash
make up-lab      # génère, démarre le laboratoire isolé (cœur, RAN, attaquants)
make lab-status
make lab-run     # campagne étiquetée -> datasets/raw/security/ (captures + labels.csv + manifeste D7)
make down-lab
```

`make lab-run` écrit une ligne D7 par UE et par fenêtre (`normal` ou étiquette d'attaque), les captures `*.pcap`
(ogstun de chaque UPF, NGAP de l'AMF) et le manifeste. **Garde-fou d'honnêteté** : avant d'étiqueter une attaque, le
script vérifie que des paquets sont réellement passés par le tunnel de l'UE (compteur `tx_packets`) ; sinon il s'arrête
sans produire de jeu, pour qu'aucune étiquette d'attaque ne soit apposée sur du trafic absent.

## Note d'exécution

La génération d'attaques (hping3, nmap) exécute des outils offensifs : elle est réservée à ce réseau isolé. Dans une
session automatisée, ces commandes peuvent être bloquées par le contrôle de sécurité de l'environnement ; la campagne
est alors lancée par le responsable (`make lab-run`). Le trafic normal et la tempête d'enregistrements ne nécessitent
aucun outil offensif.
