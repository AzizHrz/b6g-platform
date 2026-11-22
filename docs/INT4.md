# Jalon INT4 — registre Fabric réel, rejeu NTN, captures de sécurité D7

**Passage :** CT-07 réel et `tests/integration/test_int4.py` verts (plan maître § 9.3). Résultat du 2026-11-22 sur M1 :
**5 tests réussis**. Réalisme : **ÉMULÉ** (plateforme et registre réels) ; le rejeu NTN est **SYNTHÉTIQUE** (échantillon,
en attendant l'outil de l'équipe 2) et le jeu D7 est **ÉMULÉ** (laboratoire isolé).

## Démarrage

```bash
make up-core up-obs                               # plateforme et observabilité (INT1)
make up-ledger                                    # réseau Fabric, canal b6g, chaincode eventlog, passerelle I-07 :8082
B6G_LEDGER_URL=http://127.0.0.1:8082 make up-actuator   # Actionneur raccordé au registre
.venv/bin/pytest -m int tests/integration/test_int4.py
```

La campagne D7 (captures de sécurité) se lance à part, sur un réseau isolé dédié (voir `ateliers/a27/README.md`) :

```bash
make up-lab        # cœur + RAN + outils d'attaque sur le réseau Docker « b6g-lab » (internal, sans route externe)
make lab-run       # campagne étiquetée → datasets/raw/security/ (hors Git)
```

## Contenu intégré

| Brique | Tâche | Livrable |
| --- | --- | --- |
| Registre Hyperledger Fabric 2.5.16 (Org1, Org2, ordonnanceur Raft), canal `b6g`, chaincode `eventlog` (Go), endossement `AND(Org1MSP, Org2MSP)` | A21 / T21.1–T21.3 | `platform/ledger/chaincode/eventlog/`, `mk/ledger.mk`, `ateliers/a21/` |
| Passerelle REST I-07 (`:8082`, Node.js, `@hyperledger/fabric-gateway`) : `POST /v1/events`, `GET /v1/events/{id}`, `GET /v1/verify/{id}` | A21 / T21.3 | `platform/ledger/gateway/` |
| Émission asynchrone par l'Actionneur (file locale vidée par un fil dédié, retries) | W1.2 / T21.3 | `platform/actuator/b6g_actuator/app.py` |
| Rejeu NTN par l'Actionneur (lien gNB piloté à partir d'un profil de visibilité satellite) | A24 (chemin plateforme) | `datasets/samples/ntn_profile.csv`, `platform/actuator/b6g_actuator/backends.py` |
| Laboratoire d'attaque isolé `b6g-lab` et jeu D7 `security_labels` | A27 / T27.2 | `platform/attack-lab/`, `mk/attack-lab.mk`, `ateliers/a27/` |

## Tests

| Test | Vérifie |
| --- | --- |
| `test_ct07_reel_poster_relire_verifier` | CT-07 réel : un événement posté, relu, vérifié (`hash_match`, `chain_ok`, endossement Org1 + Org2) |
| `test_ct07_reel_doublon_empreinte_fausse_inconnu` | Doublon rejeté (409), contenu falsifié rejeté par le chaincode (400), identifiant inconnu (404) |
| `test_actionneur_inscrit_ses_actions_dans_fabric` | Une action de l'Actionneur produit un événement vérifiable dans le registre |
| `test_rejeu_ntn_par_l_actionneur` | Chemin plateforme du rejeu NTN : l'Actionneur applique les variations du lien gNB (profil **SYNTHÉTIQUE**) |
| `test_captures_securite_d7` | Structure du jeu D7 : `labels.csv` conforme au contrat `contracts/datasets.yaml`, `captures.json`, manifeste |

Tests de contrat associés : `CT-07` (`tests/contract/test_ct07_ledger.py`) contre la passerelle réelle. Forme canonique
de l'empreinte vérifiée côté chaincode par `platform/ledger/chaincode/eventlog/eventlog_test.go` (identique, octet pour
octet, à la référence Python de `b6g_common`).

## Écarts au plan et limites connues

- **Rejeu NTN — SYNTHÉTIQUE** : l'outil de rejeu `intelligence/ntn/replay.py` relève de l'équipe 2 (non livré). Le test
  valide le **chemin plateforme** (Actionneur → lien gNB) à partir de l'échantillon `datasets/samples/ntn_profile.csv` ;
  il sera rejoué sur le profil réel de l'équipe 2 sans changement côté plateforme.
- **Jeu D7 — capture du balayage incomplète** : les scénarios `udp_flood` (inondation UDP) et `reg_storm` (tempête de
  ré-enregistrements) sont **réellement capturés à travers le tunnel 5G** ; le scénario `scan` (balayage de ports) ne
  l'est **pas encore** — le balayage par connexion sort par l'interface directe du conteneur attaquant plutôt que par le
  tunnel, et n'apparaît donc pas dans les captures UPF. Détail, cause et correctif prévu : `ateliers/a27/README.md`,
  section « Limite connue ». Le test `test_captures_securite_d7` vérifie la **structure** du jeu, pas la présence du
  trafic de balayage. **Le tag `int4` est tenu en attente tant que la capture du balayage n'est pas complète.**
- **Deux organisations sur une seule machine** : Org1 et Org2 sont deux pairs sur M1 ; pas de réseau réel entre
  organisations (voir `ateliers/a21/README.md`).
- **Les captures D7 (`.pcap`, `labels.csv`) ne sont pas versionnées** : `datasets/raw/` est ignoré par Git ; seul le
  code de production du jeu est suivi.
