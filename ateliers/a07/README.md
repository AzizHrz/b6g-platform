# Atelier 7 — Virtualisation des fonctions réseau B6G

| Rubrique | Contenu |
| --- | --- |
| Objectif | Rappeler la NFV, virtualiser une fonction réseau (UPF de la slice miot) dans une VM, mesurer son coût selon le nombre de vCPU, étudier la migration à chaud, analyser avantages et limites. |
| Étiquette de réalisme | **ÉMULÉ** (QEMU/KVM, libvirt, Open5GS UPF et trafic réels sur M1 ; pas de second serveur physique) |
| Ce qui est réel | VM KVM Ubuntu 22.04 hébergeant Open5GS UPF, raccordée au réseau du cœur ; sessions PFCP avec `smf-miot` ; trafic GTP-U des 10 UEs miot ; migrations QEMU réelles |
| Ce qui est simulé et pourquoi | Les « deux hyperviseurs » de la migration sont deux processus QEMU/KVM de la même machine : libvirt refuse la migration vers le même hôte et le projet ne dispose que de M1 |
| Interfaces utilisées | I-01 (adresses, sous-réseau miot), I-02 (métriques UPF), N3 / N4 / N6 (3GPP) |
| Comment lancer | `make up-vm` ; `.venv/bin/python ateliers/a07/run_a07.py` ; `make migration-lab` ; retour au conteneur : `make down-vm` |
| Résultat attendu | Comprendre l'impact de la virtualisation sur les performances du réseau B6G |
| Résultat obtenu (source, date) | `results/vm_resources.csv`, `results/migration.csv`, `figures/vm_resources.png`, mesures du 2026-11-21 sur M1 |

## E01 — Contexte NFV (T07.1)

La virtualisation des fonctions réseau (ETSI GS NFV 002) sépare la fonction (VNF) du matériel : une fonction réseau
devient un logiciel exécuté dans une machine virtuelle, sur une infrastructure de virtualisation (NFVI), pilotée par
un orchestrateur (MANO : NFVO, VNFM, VIM).

| Concept NFV | Réalisation dans la plateforme |
| --- | --- |
| VNF | Open5GS UPF de la slice miot, dans la VM `upf-miot-vm` |
| NFVI (calcul, stockage, réseau) | KVM / QEMU 10.0.13 ; pool libvirt `b6g` ; pont Docker `b6g-core` partagé avec les fonctions conteneurisées |
| VIM | libvirt 11.3.0 (`virsh`, `virt-install`) |
| VNFM / NFVO | Scripts du dépôt : `platform/vm/upf-vm/build.py`, cibles `make up-vm` / `down-vm` |
| Descripteur de VNF | Configuration cloud-init générée depuis le scénario (adresse N4 / N3, sous-réseau UE, DNN) |

## E02–E03 — Création de la VM et déploiement de la VNF (T07.2)

`platform/vm/upf-vm/build.py` crée la VM depuis l'image Ubuntu 22.04 officielle (vérifiée par SHA-256) : disque qcow2
adossé à l'image de base, cloud-init (adresse 172.22.0.43, identique au conteneur `upf-miot` qu'elle remplace),
installation d'Open5GS UPF 2.8.0 (PPA officiel), interface `ogstun` (10.47.0.1/16) et NAT rétablis à chaque démarrage.
La VM est raccordée au pont Docker `b6g-core` : elle voit la SMF et le gNB comme les conteneurs.

Résultat : association PFCP avec `smf-miot` (Open5GS 2.7.7), 10 UEs miot à travers la VM, RTT 1,3 ms vers la
passerelle et 47 ms vers Internet. La VM de test de la migration démarre en 8,2 s (image sans paquet supplémentaire).

## E04–E05 — CPU et mémoire selon la configuration (T07.3)

3 répétitions de 15 s de trafic TCP descendant sans limitation sur les 10 UEs miot, pour 1, 2 et 4 vCPU (changement
à froid, vérifié par `nproc` dans l'invité). CPU : temps CPU total du domaine (`virsh domstats`) ; mémoire : RSS du
processus QEMU (`results/vm_resources.csv`, `figures/vm_resources.png`).

| vCPU | Débit moyen (min – max) | CPU consommé | CPU / vCPU alloués | Mémoire (RSS QEMU) |
| --- | --- | --- | --- | --- |
| 1 | 998 Mbit/s (818 – 1 131) | 1,73 cœur | 173 % | 709 Mo |
| 2 | 924 Mbit/s (790 – 1 148) | 2,50 cœurs | 125 % | 748 Mo |
| 4 | 885 Mbit/s (773 – 1 093) | 3,15 cœurs | 79 % | 772 Mo |

- Le débit ne progresse pas avec le nombre de vCPU, alors que la consommation CPU augmente : la VM n'est pas le goulot.
  Pendant ces mesures, le gNB UERANSIM atteint 2,32 cœurs (traitement GTP-U et liaison radio simulée en espace
  utilisateur) : la limite la plus probable est le gNB, pas l'UPF virtualisée.
- Même à 1 vCPU, la VM consomme 1,73 cœur : les fils d'entrées-sorties de QEMU (virtio-net, émulation) s'ajoutent
  au vCPU de l'invité. C'est le surcoût de virtualisation.
- La mémoire résidente (709 à 772 Mo pour 1 Gio alloué) croît légèrement avec le nombre de vCPU.
- Dispersion importante d'une répétition à l'autre (± 20 %) : machine partagée avec le cœur, le cluster k3d et la
  supervision.
- Premier essai écarté : l'ajout de vCPU à chaud (`setvcpus --live`) n'activait pas les processeurs dans l'invité
  (`nproc` restait à 1) ; les mesures retenues reconfigurent la VM à froid.

## E06 — Migration à chaud (T07.4)

Deux hyperviseurs QEMU/KVM dans un conteneur privilégié (`platform/vm/qemu-lab`), reliés par un pont interne et deux
interfaces tap ; disque partagé ; migration lancée par QMP (`migrate`) vers un hyperviseur en attente (`-incoming`) ;
ping toutes les 10 ms vers la VM pendant la migration (`ateliers/a07/migrate_lab.py`, `results/migration.csv`).

| Migration | Interruption mesurée (ping) | Arrêt annoncé par QEMU | Durée totale | Mémoire transférée |
| --- | --- | --- | --- | --- |
| 1 (A → B) | 32 ms | 12 ms | 4,9 s | 702 Mo |
| 2 (B → A) | 72 ms | 37 ms | 3,4 s | 479 Mo |
| 3 (A → B) | 72 ms | 33 ms | 3,4 s | 475 Mo |

L'interruption vue par le réseau (32 à 72 ms) dépasse l'arrêt de la VM annoncé par QEMU (12 à 37 ms) : il faut aussi
que le commutateur apprenne la nouvelle interface (annonce réseau après reprise). Résolution de la mesure : environ
17 ms (cadence réelle du ping). La migration est transparente pour une session TCP mais reste visible pour un flux
temps réel exigeant (SLA v2x de 20 ms).

## E07 — Avantages et limites (T07.5)

| Avantages (mesurés) | Limites (mesurées) |
| --- | --- |
| Isolation forte : noyau propre à la VNF (règles NAT, `ogstun`, version Open5GS 2.8.0 différente des conteneurs) | Surcoût CPU : 1,73 cœur pour 1 vCPU, contre 0,98 cœur pour la même UPF conteneurisée au même débit (atelier 9) |
| Mobilité : migration à chaud en 3,4 à 4,9 s, interruption de 32 à 72 ms | Interruption de service lors de la migration, incompatible avec un SLA de 20 ms sans redondance |
| Remplacement transparent : même adresse N4 / N3, la SMF se réassocie seule | Démarrage plus long qu'un conteneur et réassociation PFCP à attendre (sessions refusées entre-temps) |
| Dimensionnement explicite (vCPU, mémoire) | Ajouter des vCPU n'augmente pas le débit si le goulot est ailleurs (gNB) |
| | Mémoire : ≈ 700 Mo résidents pour une fonction réseau unique |

## Problèmes rencontrés

Voir `docs/setup/SETUP_LOG.md` : droits du dossier personnel (pool libvirt dédié), test d'état du pool, conflit
d'adresse avec le conteneur, service `open5gs-upfd` non activé au démarrage et NAT non persistant (service
`b6g-upf-net` ajouté), sessions refusées tant que la SMF n'est pas réassociée (réattachement des UEs avec reprise).
