# Registre Hyperledger Fabric (M08, atelier 21). Fabric 2.5.16 hors dépôt : ~/b6g-ext/fabric/fabric-samples.
FABRIC := $(HOME)/b6g-ext/fabric/fabric-samples
FABRIC_NET := $(FABRIC)/test-network
FABRIC_PATH := $(HOME)/b6g-ext/fabric/gowrap:$(FABRIC)/bin:$(PATH)
LEDGER_IMAGE := b6g/ledger-gateway:1.0.0

.PHONY: up-ledger down-ledger ledger-gateway ledger-status

# Réseau (Org1, Org2, ordonnanceur), canal b6g, chaincode eventlog (endossement Org1 ET Org2), passerelle I-07 :8082
up-ledger:
	cd $(FABRIC_NET) && PATH=$(FABRIC_PATH) ./network.sh up createChannel -c b6g
	cd $(FABRIC_NET) && PATH=$(FABRIC_PATH) ./network.sh deployCC -c b6g -ccn eventlog \
		-ccp $(CURDIR)/platform/ledger/chaincode/eventlog -ccl go -ccv 1.0 \
		-ccep "AND('Org1MSP.peer','Org2MSP.peer')"
	$(MAKE) --no-print-directory ledger-gateway

ledger-gateway:
	docker build -q -t $(LEDGER_IMAGE) platform/ledger/gateway
	-docker rm -f ledger-gateway
	docker run -d --name ledger-gateway --restart unless-stopped --network fabric_test -p 8082:8082 \
		-v $(FABRIC_NET)/organizations:/crypto:ro $(LEDGER_IMAGE)
	@sleep 3; curl -s http://127.0.0.1:8082/v1/health; echo

ledger-status:
	docker ps --filter name=example.com --filter name=ledger-gateway --format 'table {{.Names}}\t{{.Status}}'

# Arrêt complet : la passerelle puis le réseau (network.sh down supprime aussi les données du registre)
down-ledger:
	-docker rm -f ledger-gateway
	cd $(FABRIC_NET) && PATH=$(FABRIC_PATH) ./network.sh down
