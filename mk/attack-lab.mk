# Laboratoire d'attaque isolé b6g-lab (M11, T27.2) : cœur, RAN et outils d'attaque sur un réseau sans route externe.
LAB_COMPOSE := docker compose -f platform/attack-lab/generated/compose.yaml

.PHONY: up-lab down-lab lab-status lab-run

up-lab:
	$(BIN)/python platform/attack-lab/render_lab.py
	docker build -q -t b6g/attack-tools:0.1.0 platform/attack-lab/attack-tools
	$(LAB_COMPOSE) up -d lab-mongo
	@for i in $$(seq 1 30); do docker exec lab-mongo mongosh --quiet --eval 'db.runCommand({ping:1}).ok' >/dev/null 2>&1 && break; sleep 1; done
	docker exec lab-mongo mongosh --quiet /subscribers.js
	$(LAB_COMPOSE) up -d lab-nrf lab-ausf lab-udm lab-udr lab-pcf lab-nssf lab-bsf lab-upf-embb lab-upf-v2x lab-upf-miot \
		lab-smf-embb lab-smf-v2x lab-smf-miot lab-amf lab-iperf
	@sleep 5
	$(LAB_COMPOSE) up -d lab-gnb
	@sleep 3
	$(LAB_COMPOSE) up -d lab-ue-embb lab-ue-v2x lab-ue-miot lab-attacker-embb lab-attacker-miot
	@echo "Laboratoire isolé démarré : make lab-status"

lab-status:
	@$(LAB_COMPOSE) ps --format 'table {{.Name}}\t{{.Status}}'
	@for u in lab-ue-embb lab-ue-v2x lab-ue-miot; do printf '%s : ' $$u; docker exec $$u sh -c 'ip -o -4 addr show | grep -c uesimtun' 2>/dev/null || echo 0; done

# Campagne étiquetée : captures + labels.csv dans datasets/raw/security/ (D7)
lab-run:
	$(BIN)/python platform/attack-lab/run_scenarios.py

down-lab:
	-$(LAB_COMPOSE) down
