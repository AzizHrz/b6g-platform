// Passerelle REST du registre (M08, T21.3) : API I-07 (contracts/openapi/ledger.yaml) au-dessus d'Hyperledger Fabric.
//
//   POST /v1/events            inscrit un événement b6g.event.v1 (texte d'origine transmis tel quel au chaincode)
//   GET  /v1/events            liste (type, since, limit)
//   GET  /v1/events/{id}       événement + tx_id + block_number
//   GET  /v1/verify/{id}       {hash_match, chain_ok, endorsements, tx_id, block_number}
//   GET  /v1/health
// Identité : utilisateur User1 d'Org1 ; l'endossement par Org1 et Org2 est obtenu par le service Gateway du pair.
'use strict';

const fs = require('fs');
const path = require('path');
const http = require('http');
const crypto = require('crypto');
const grpc = require('@grpc/grpc-js');
const { connect, signers, hash } = require('@hyperledger/fabric-gateway');
const { common, msp, peer } = require('@hyperledger/fabric-protos');

const CHANNEL = process.env.CHANNEL || 'b6g';
const CHAINCODE = process.env.CHAINCODE || 'eventlog';
const PEER = process.env.PEER_ENDPOINT || 'peer0.org1.example.com:7051';
const CRYPTO = process.env.CRYPTO_PATH || '/crypto/peerOrganizations/org1.example.com';
const PORT = Number(process.env.PORT || 8082);

function firstFile(dir) {
  return path.join(dir, fs.readdirSync(dir)[0]);
}

async function newGateway() {
  const tlsCert = fs.readFileSync(path.join(CRYPTO, 'peers/peer0.org1.example.com/tls/ca.crt'));
  const client = new grpc.Client(PEER, grpc.credentials.createSsl(tlsCert),
    { 'grpc.ssl_target_name_override': 'peer0.org1.example.com' });
  const user = path.join(CRYPTO, 'users/User1@org1.example.com/msp');
  const identity = { mspId: 'Org1MSP', credentials: fs.readFileSync(firstFile(path.join(user, 'signcerts'))) };
  const signer = signers.newPrivateKeySigner(crypto.createPrivateKey(fs.readFileSync(firstFile(path.join(user, 'keystore')))));
  return connect({
    client, identity, signer, hash: hash.sha256,
    evaluateOptions: () => ({ deadline: Date.now() + 5000 }),
    endorseOptions: () => ({ deadline: Date.now() + 15000 }),
    submitOptions: () => ({ deadline: Date.now() + 5000 }),
    commitStatusOptions: () => ({ deadline: Date.now() + 60000 }),
  });
}

const utf8 = (b) => Buffer.from(b).toString('utf8');

function problem(res, status, title, detail) {
  const body = JSON.stringify({ type: `https://b6g.local/problems/${status}`, title, status, detail: detail || '' });
  res.writeHead(status, { 'Content-Type': 'application/problem+json' });
  res.end(body);
}

function send(res, obj) {
  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(obj));
}

// Code HTTP d'après le préfixe du message d'erreur du chaincode (invalid, hash, duplicate, notfound)
function fromChaincodeError(err) {
  const text = [err.message, ...((err.details || []).map((d) => d.message))].join(' ; ');
  if (/duplicate:/.test(text)) return [409, 'event_id déjà inscrit', text];
  if (/notfound:/.test(text)) return [404, 'Événement inconnu', text];
  if (/(invalid|hash):/.test(text)) return [400, 'Événement invalide', text];
  return [503, 'Registre indisponible', text];
}

async function main() {
  const gateway = await newGateway();
  const network = gateway.getNetwork(CHANNEL);
  const contract = network.getContract(CHAINCODE);
  const qscc = network.getContract('qscc');

  async function txInfo(id) {
    const txId = utf8(await contract.evaluateTransaction('GetTxID', id));
    const block = common.Block.deserializeBinary(await qscc.evaluateTransaction('GetBlockByTxID', CHANNEL, txId));
    return { txId, blockNumber: Number(block.getHeader().getNumber()) };
  }

  async function endorsers(txId) {
    const ptx = peer.ProcessedTransaction.deserializeBinary(await qscc.evaluateTransaction('GetTransactionByID', CHANNEL, txId));
    const payload = common.Payload.deserializeBinary(ptx.getTransactionenvelope().getPayload_asU8());
    const tx = peer.Transaction.deserializeBinary(payload.getData_asU8());
    const action = peer.ChaincodeActionPayload.deserializeBinary(tx.getActionsList()[0].getPayload_asU8());
    const ids = action.getAction().getEndorsementsList()
      .map((e) => msp.SerializedIdentity.deserializeBinary(e.getEndorser_asU8()).getMspid());
    return { mspIds: [...new Set(ids)].sort(), valid: ptx.getValidationcode() === 0 };
  }

  const server = http.createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    try {
      if (req.method === 'GET' && url.pathname === '/v1/health') {
        return send(res, { status: 'ok', backend: 'hyperledger-fabric', channel: CHANNEL, chaincode: CHAINCODE });
      }
      if (req.method === 'POST' && url.pathname === '/v1/events') {
        if (!req.headers['x-b6g-caller']) return problem(res, 400, 'En-tête X-B6G-Caller manquant', 'obligatoire');
        const chunks = [];
        for await (const c of req) chunks.push(c);
        const raw = Buffer.concat(chunks).toString('utf8');
        let evt;
        try { evt = JSON.parse(raw); } catch (e) { return problem(res, 400, 'JSON invalide', e.message); }
        try {
          const proposal = contract.newProposal('PutEvent', { arguments: [raw] });
          const tx = await proposal.endorse();
          const commit = await tx.submit();
          const status = await commit.getStatus();
          if (!status.successful) return problem(res, 503, 'Transaction non validée', `code ${status.code}`);
          return send(res, { event_id: evt.event_id, tx_id: commit.getTransactionId(),
            block_number: Number(status.blockNumber), status: 'committed' });
        } catch (e) {
          const [code, title, detail] = fromChaincodeError(e);
          return problem(res, code, title, detail);
        }
      }
      if (req.method === 'GET' && url.pathname === '/v1/events') {
        // Contrat I-07 : {items, total} ; filtres appliqués par le chaincode, `limit` derniers éléments (comme le mock)
        const all = JSON.parse(utf8(await contract.evaluateTransaction('QueryEvents', url.searchParams.get('type') || '',
          url.searchParams.get('since') || '', '0')));
        const limit = Math.max(1, Math.min(Number(url.searchParams.get('limit') || 100), 1000));
        return send(res, { items: all.slice(-limit), total: all.length });
      }
      let m = url.pathname.match(/^\/v1\/events\/([^/]+)$/);
      if (req.method === 'GET' && m) {
        try {
          const evt = JSON.parse(utf8(await contract.evaluateTransaction('GetEvent', m[1])));
          const { txId, blockNumber } = await txInfo(m[1]);
          return send(res, { ...evt, tx_id: txId, block_number: blockNumber });
        } catch (e) { const [code, title, detail] = fromChaincodeError(e); return problem(res, code, title, detail); }
      }
      m = url.pathname.match(/^\/v1\/verify\/([^/]+)$/);
      if (req.method === 'GET' && m) {
        try {
          const ok = utf8(await contract.evaluateTransaction('VerifyEvent', m[1])) === 'true';
          const { txId, blockNumber } = await txInfo(m[1]);
          const e = await endorsers(txId);
          return send(res, { hash_match: ok, chain_ok: e.valid, endorsements: e.mspIds, tx_id: txId, block_number: blockNumber });
        } catch (e) { const [code, title, detail] = fromChaincodeError(e); return problem(res, code, title, detail); }
      }
      return problem(res, 404, 'Ressource inconnue', url.pathname);
    } catch (e) {
      return problem(res, 503, 'Registre indisponible', e.message);
    }
  });
  server.listen(PORT, () => console.log(`passerelle I-07 sur :${PORT} (canal ${CHANNEL}, chaincode ${CHAINCODE})`));
}

main().catch((e) => { console.error(e); process.exit(1); });
