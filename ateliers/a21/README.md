# Atelier 21 — Blockchain et confiance dans les réseaux B6G

| Rubrique | Contenu |
| --- | --- |
| Objectif | Rappeler le fonctionnement d'une blockchain, définir participants, transactions et mécanisme de confiance, inscrire et vérifier les événements du réseau dans un registre, mesurer coûts et limites. |
| Étiquette de réalisme | **ÉMULÉ** (Hyperledger Fabric 2.5.16 réel : deux organisations, un ordonnanceur Raft, sur une seule machine) |
| Ce qui est réel | Canal, chaincode, endossement par deux organisations, ordonnancement, validation, passerelle REST I-07, événements émis par l'Actionneur |
| Ce qui est simulé et pourquoi | Les deux organisations (opérateur, hébergeur Edge) sont deux pairs sur M1 : pas de réseau réel entre organisations |
| Interfaces utilisées | I-07 (API registre, `:8082`), I-08 (`b6g.event.v1`), I-04 (Actionneur émetteur) |
| Comment lancer | `make up-ledger` ; Actionneur : `B6G_LEDGER_URL=http://127.0.0.1:8082 make up-actuator` ; `.venv/bin/python ateliers/a21/run_a21.py` |
| Résultat attendu | Comprendre le rôle potentiel de la blockchain dans un réseau B6G |
| Résultat obtenu (source, date) | `results/events_verified.csv`, `results/cost.csv`, `figures/cost.png`, mesures du 2026-11-21 sur M1 |

## E01–E04 — Blockchain, participants, transactions, confiance (T21.1)

Une blockchain est un registre réparti en blocs chaînés par empreintes : chaque bloc contient l'empreinte du précédent,
ce qui rend toute modification a posteriori détectable. Hyperledger Fabric est une blockchain à permissions :
les participants sont identifiés (certificats X.509 émis par l'autorité de leur organisation), et une transaction n'est
valide que si elle est **endossée** selon une politique, puis **ordonnée** dans un bloc et **validée** par chaque pair.

| Élément | Choix B6G |
| --- | --- |
| Participants | Org1 (opérateur du réseau 5G, `Org1MSP`), Org2 (hébergeur Edge, `Org2MSP`), ordonnanceur (`OrdererMSP`) |
| Canal | `b6g` |
| Transactions | inscription d'un événement `b6g.event.v1` (I-08) : actions de l'Actionneur, alertes QoS et sécurité, itérations de boucle, déploiements de modèles |
| Contrat intelligent | chaincode `eventlog` en Go ([platform/ledger/chaincode/eventlog](../../platform/ledger/chaincode/eventlog)) : contrôle des champs, du type, de l'unicité et de l'empreinte `payload_sha256` |
| Confiance | politique d'endossement `AND('Org1MSP.peer', 'Org2MSP.peer')` : aucune organisation ne peut inscrire seule un événement ; empreinte du contenu recalculée par le chaincode à l'inscription et à la vérification |

L'empreinte suit la forme canonique de `b6g_common` (clés triées, sans espace, nombres conservés au caractère près) :
le test `eventlog_test.go` vérifie qu'elle est identique, octet pour octet, à celle calculée en Python.

## E05–E07 — Test, inscription et vérification (T21.2, T21.3)

| Composant | Réalisation |
| --- | --- |
| Réseau | test-network de fabric-samples, canal `b6g`, `make up-ledger` |
| Passerelle I-07 | [platform/ledger/gateway](../../platform/ledger/gateway) (Node.js 20, SDK `@hyperledger/fabric-gateway` 1.11.0), conteneur `ledger-gateway` sur `:8082` |
| Vérification | `GET /v1/verify/{id}` : empreinte recalculée par le chaincode (`hash_match`), validité de la transaction (`chain_ok`), organisations endossantes lues dans la transaction stockée (`endorsements`) |
| Émission par l'Actionneur | file locale vidée par un fil dédié : l'action est appliquée en ≈ 0,3 s sans attendre le registre ; événement retenté si le registre est indisponible |

Résultat (`results/events_verified.csv`) : **100 événements sur 100** inscrits (blocs 13 à 112), `hash_match` vrai et
endossement `Org1MSP` + `Org2MSP` pour chacun ; inscription médiane 2 046 ms (p95 2 057 ms), sous la limite de 5 s
du contrat. Refus vérifiés : doublon (409), contenu falsifié (400, empreinte rejetée par le chaincode), identifiant
inconnu (404).

## E08 — Coûts et limites (T21.4)

Charge en boucle ouverte pendant 30 s ; latence = de l'envoi à la validation dans un bloc ; CPU et mémoire des trois
conteneurs Fabric (deux pairs, ordonnanceur) d'après cAdvisor (`results/cost.csv`, `figures/cost.png`).

| Débit demandé | Débit validé | Latence p50 | Latence p95 | CPU Fabric | Mémoire Fabric |
| --- | --- | --- | --- | --- | --- |
| 1 tx/s | 0,97 tx/s | 1 052 ms | 2 051 ms | 0,04 cœur | 256 Mo |
| 10 tx/s | 10,01 tx/s | 514 ms | 961 ms | 0,18 cœur | 278 Mo |
| 50 tx/s | 49,92 tx/s | **159 ms** | 252 ms | 0,69 cœur | 338 Mo |

- Aucun échec jusqu'à 50 tx/s ; le CPU croît à peu près linéairement avec le débit (≈ 0,014 cœur par tx/s).
- La latence **diminue** quand le débit augmente : l'ordonnanceur ferme un bloc après 2 s (`BatchTimeout`) ou dès
  10 transactions (`MaxMessageCount`). À faible débit, chaque transaction attend la fin du délai (jusqu'à 2 s) ; à
  50 tx/s, les blocs se remplissent en 0,2 s.
- Conséquence pour la plateforme : le registre convient à la **traçabilité** (audit des actions, alertes, preuves),
  pas au **chemin de décision** : une inscription coûte de 0,2 à 2 s, à comparer aux 20 ms du SLA v2x. D'où l'émission
  asynchrone par l'Actionneur.
- Réglage possible : `BatchTimeout` plus court pour réduire la latence à faible débit, au prix de blocs plus nombreux.

## Résultat (A21-R)

Le registre apporte une trace infalsifiable et partagée entre organisations des décisions prises sur le réseau
(qui a demandé quoi, quand, avec quel effet) : chaque action de l'Actionneur y est inscrite, endossée par l'opérateur
et l'hébergeur, et vérifiable a posteriori. Son coût (latence de l'ordre de la seconde, 0,7 cœur à 50 tx/s) le
réserve à l'audit et à la confiance, hors de la boucle de contrôle temps réel.

## Problèmes rencontrés

Voir `docs/setup/SETUP_LOG.md` : script d'installation de Fabric non exécuté (étapes refaites une à une : dépôt
`fabric-samples`, binaires officiels, images), Go absent de l'hôte (chaîne Go de l'image `fabric-ccenv`), chaincode en
Go plutôt qu'en JavaScript (forme canonique des nombres), format `{items, total}` de la liste, émission synchrone de
l'Actionneur remplacée par une file asynchrone.
