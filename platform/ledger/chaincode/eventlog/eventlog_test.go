package main

import "testing"

// Empreintes de référence calculées par b6g_common (Python) : sha256_hex(payload), JSON canonique.
var references = []struct{ payload, sha string }{
	{`{"slice": "v2x", "rate_mbps": 30.0, "ceil_mbps": 60}`, "772f0e7930e23670e9b8aa0a407980e31f76e4d545bf7782038384e93275af3f"},
	{`{"target": "ue-miot-02", "reason": "latence p95 137 ms > SLA 20 ms", "x": 1e-05, "neg": -2.5}`, "844dfb2edd614d6f5cf879b22c66e9f4442d2428a144d6dd8b0b0edc3515e90b"},
	{`{"nested": {"b": [1, 2.25, {"z": null, "a": true}], "a": "é<&>\""}, "empty": {}, "list": []}`, "0b1818aae9e48bdfac39598566cd3f383165c9cbf65818d4fb97c100c2b89651"},
}

func TestEmpreinteIdentiqueAPython(t *testing.T) {
	for _, r := range references {
		obj, err := decode(`{"payload": ` + r.payload + `}`)
		if err != nil {
			t.Fatal(err)
		}
		h, err := payloadHash(obj)
		if err != nil {
			t.Fatal(err)
		}
		if h != r.sha {
			c, _ := canonical(obj["payload"])
			t.Errorf("empreinte %s, attendu %s (JSON canonique : %s)", h, r.sha, c)
		}
	}
}
