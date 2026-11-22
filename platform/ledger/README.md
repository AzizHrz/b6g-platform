# M08 — Registre Hyperledger Fabric (atelier 21)

Réalisme : **ÉMULÉ** (Fabric 2.5.16 réel : deux organisations, un ordonnanceur Raft, sur M1).

| Élément | Détail |
| --- | --- |
| Réseau | test-network de fabric-samples (hors dépôt, `~/b6g-ext/fabric/fabric-samples`), canal `b6g` |
| Chaincode | `chaincode/eventlog/` (Go) : inscription d'événements `b6g.event.v1`, contrôle des champs, du type, de l'unicité et de l'empreinte `payload_sha256` (forme canonique identique à `b6g_common`) |
| Endossement | `AND('Org1MSP.peer', 'Org2MSP.peer')` : opérateur ET hébergeur Edge |
| Passerelle I-07 | `gateway/` (Node.js 20, `@hyperledger/fabric-gateway`), conteneur `ledger-gateway` sur `:8082` |

```bash
make up-ledger      # réseau + canal + chaincode + passerelle (:8082)
curl -s http://127.0.0.1:8082/v1/health
make down-ledger    # arrête la passerelle et le réseau (efface les données du registre)
```

Chaîne avec l'Actionneur : `B6G_LEDGER_URL=http://127.0.0.1:8082 make up-actuator` ; chaque action appliquée est
inscrite de façon asynchrone (l'action n'attend pas le registre). Résultats, coûts et limites : `ateliers/a21/README.md`.
Compilation du chaincode sans Go sur l'hôte : enveloppe `~/b6g-ext/fabric/gowrap/go` (image `fabric-ccenv`).
