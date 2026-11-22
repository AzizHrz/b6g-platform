// Chaincode eventlog (M08, T21.2) : registre des événements b6g.event.v1 (I-08) de la plateforme B6G.
//
// Chaque événement est inscrit tel que reçu (texte JSON d'origine), sous la clé event_id, après contrôle :
// champs obligatoires, type autorisé, unicité, et empreinte payload_sha256 = SHA-256 du JSON canonique de payload.
// Le JSON canonique est identique à celui de b6g_common (Python) : clés triées, séparateurs sans espace, caractères
// non ASCII non échappés, nombres conservés au caractère près (json.Number).
// Politique d'endossement prévue au déploiement : AND('Org1MSP.peer', 'Org2MSP.peer').
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"github.com/hyperledger/fabric-contract-api-go/v2/contractapi"
)

// EventLog : contrat du registre.
type EventLog struct {
	contractapi.Contract
}

var allowedTypes = map[string]bool{
	"actuator.applied": true, "slice.resized": true, "slice.state": true, "link.netem": true,
	"deployment.scaled": true, "deployment.moved": true, "ue.isolated": true, "ue.released": true,
	"alert.qos": true, "alert.security": true, "loop.iteration": true, "model.deployed": true,
}

var required = []string{"schema", "event_id", "ts", "source", "type", "severity", "payload", "payload_sha256"}

func decode(raw string) (map[string]interface{}, error) {
	dec := json.NewDecoder(strings.NewReader(raw))
	dec.UseNumber()
	var obj map[string]interface{}
	if err := dec.Decode(&obj); err != nil {
		return nil, fmt.Errorf("invalid: JSON illisible : %v", err)
	}
	return obj, nil
}

// canonical reproduit json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).
func canonical(v interface{}) ([]byte, error) {
	var buf bytes.Buffer
	switch t := v.(type) {
	case map[string]interface{}:
		keys := make([]string, 0, len(t))
		for k := range t {
			keys = append(keys, k)
		}
		sort.Strings(keys)
		buf.WriteByte('{')
		for i, k := range keys {
			if i > 0 {
				buf.WriteByte(',')
			}
			kb, err := canonical(k)
			if err != nil {
				return nil, err
			}
			buf.Write(kb)
			buf.WriteByte(':')
			vb, err := canonical(t[k])
			if err != nil {
				return nil, err
			}
			buf.Write(vb)
		}
		buf.WriteByte('}')
	case []interface{}:
		buf.WriteByte('[')
		for i, e := range t {
			if i > 0 {
				buf.WriteByte(',')
			}
			eb, err := canonical(e)
			if err != nil {
				return nil, err
			}
			buf.Write(eb)
		}
		buf.WriteByte(']')
	case json.Number:
		buf.WriteString(t.String())
	default:
		enc := json.NewEncoder(&buf)
		enc.SetEscapeHTML(false)
		if err := enc.Encode(t); err != nil {
			return nil, err
		}
		buf.Truncate(buf.Len() - 1) // retire le saut de ligne ajouté par Encode
	}
	return buf.Bytes(), nil
}

func payloadHash(obj map[string]interface{}) (string, error) {
	c, err := canonical(obj["payload"])
	if err != nil {
		return "", err
	}
	sum := sha256.Sum256(c)
	return hex.EncodeToString(sum[:]), nil
}

// PutEvent inscrit un événement ; renvoie son event_id. Erreurs préfixées : invalid, hash, duplicate.
func (s *EventLog) PutEvent(ctx contractapi.TransactionContextInterface, raw string) (string, error) {
	obj, err := decode(raw)
	if err != nil {
		return "", err
	}
	for _, k := range required {
		if _, ok := obj[k]; !ok {
			return "", fmt.Errorf("invalid: champ %s manquant", k)
		}
	}
	if obj["schema"] != "b6g.event.v1" {
		return "", fmt.Errorf("invalid: schema %v", obj["schema"])
	}
	typ, _ := obj["type"].(string)
	if !allowedTypes[typ] {
		return "", fmt.Errorf("invalid: type %q non autorisé", typ)
	}
	id, _ := obj["event_id"].(string)
	if id == "" {
		return "", fmt.Errorf("invalid: event_id vide")
	}
	h, err := payloadHash(obj)
	if err != nil {
		return "", fmt.Errorf("invalid: %v", err)
	}
	if h != obj["payload_sha256"] {
		return "", fmt.Errorf("hash: payload_sha256 ne correspond pas au contenu (attendu %s)", h)
	}
	existing, err := ctx.GetStub().GetState(id)
	if err != nil {
		return "", err
	}
	if existing != nil {
		return "", fmt.Errorf("duplicate: événement %s déjà inscrit", id)
	}
	if err := ctx.GetStub().PutState(id, []byte(raw)); err != nil {
		return "", err
	}
	// Index event_id -> identifiant de transaction (le numéro de bloc est retrouvé par qscc GetBlockByTxID)
	key, err := ctx.GetStub().CreateCompositeKey("txid", []string{id})
	if err != nil {
		return "", err
	}
	if err := ctx.GetStub().PutState(key, []byte(ctx.GetStub().GetTxID())); err != nil {
		return "", err
	}
	_ = ctx.GetStub().SetEvent("b6g.event", []byte(id))
	return id, nil
}

// GetTxID renvoie l'identifiant de la transaction qui a inscrit l'événement.
func (s *EventLog) GetTxID(ctx contractapi.TransactionContextInterface, id string) (string, error) {
	key, err := ctx.GetStub().CreateCompositeKey("txid", []string{id})
	if err != nil {
		return "", err
	}
	b, err := ctx.GetStub().GetState(key)
	if err != nil {
		return "", err
	}
	if b == nil {
		return "", fmt.Errorf("notfound: événement %s inconnu", id)
	}
	return string(b), nil
}

// GetEvent renvoie le texte JSON inscrit.
func (s *EventLog) GetEvent(ctx contractapi.TransactionContextInterface, id string) (string, error) {
	b, err := ctx.GetStub().GetState(id)
	if err != nil {
		return "", err
	}
	if b == nil {
		return "", fmt.Errorf("notfound: événement %s inconnu", id)
	}
	return string(b), nil
}

// VerifyEvent recalcule l'empreinte du contenu inscrit et la compare à payload_sha256.
func (s *EventLog) VerifyEvent(ctx contractapi.TransactionContextInterface, id string) (bool, error) {
	raw, err := s.GetEvent(ctx, id)
	if err != nil {
		return false, err
	}
	obj, err := decode(raw)
	if err != nil {
		return false, err
	}
	h, err := payloadHash(obj)
	if err != nil {
		return false, err
	}
	return h == obj["payload_sha256"], nil
}

// QueryEvents renvoie (en JSON) les événements filtrés par type (vide = tous) et date minimale, au plus limit.
func (s *EventLog) QueryEvents(ctx contractapi.TransactionContextInterface, typ string, since string, limit int) (string, error) {
	it, err := ctx.GetStub().GetStateByRange("", "")
	if err != nil {
		return "", err
	}
	defer it.Close()
	out := make([]json.RawMessage, 0)
	for it.HasNext() && (limit <= 0 || len(out) < limit) {
		kv, err := it.Next()
		if err != nil {
			return "", err
		}
		obj, err := decode(string(kv.Value))
		if err != nil {
			continue
		}
		if typ != "" && obj["type"] != typ {
			continue
		}
		if ts, _ := obj["ts"].(string); since != "" && ts < since {
			continue
		}
		out = append(out, json.RawMessage(kv.Value))
	}
	b, err := json.Marshal(out)
	return string(b), err
}

func main() {
	cc, err := contractapi.NewChaincode(&EventLog{})
	if err != nil {
		panic(err)
	}
	if err := cc.Start(); err != nil {
		panic(err)
	}
}
