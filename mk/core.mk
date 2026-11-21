# Cœur Open5GS + RAN UERANSIM (M01, T03.1). Configurations générées depuis config/scenario.yaml.
CORE_COMPOSE := docker compose -f platform/core/generated/compose.yaml

.PHONY: core-render up-core down-core core-subscribers core-status core-logs

core-render:
	$(BIN)/python platform/core/render.py

# Démarrage ordonné : MongoDB, abonnés, fonctions du cœur, puis gNB et UEs
up-core: core-render
	$(CORE_COMPOSE) up -d mongo
	@for i in $$(seq 1 30); do docker exec mongo mongosh --quiet --eval 'db.runCommand({ping:1}).ok' >/dev/null 2>&1 && break; sleep 1; done
	$(MAKE) --no-print-directory core-subscribers
	$(CORE_COMPOSE) up -d nrf ausf udm udr pcf nssf bsf upf-embb upf-v2x upf-miot smf-embb smf-v2x smf-miot amf
	@sleep 5
	$(CORE_COMPOSE) up -d gnb
	@sleep 3
	$(CORE_COMPOSE) up -d ue-embb ue-v2x ue-miot
	@echo "Cœur démarré : make core-status"

core-subscribers:
	docker exec mongo mongosh --quiet /subscribers.js

down-core:
	-$(CORE_COMPOSE) down

core-status:
	@$(CORE_COMPOSE) ps --format 'table {{.Name}}\t{{.Status}}'
	@for u in ue-embb ue-v2x ue-miot; do printf '%s : ' $$u; docker exec $$u sh -c 'ip -o -4 addr show | grep -c uesimtun' 2>/dev/null || echo 0; done

core-logs:
	$(CORE_COMPOSE) logs --tail=50
