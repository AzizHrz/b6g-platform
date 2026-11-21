# Pile d'observabilité (M03, W1.3) et Actionneur v1 réel (M04, W1.2).
OBS_COMPOSE := docker compose -f platform/observability/compose.yaml

.PHONY: up-obs down-obs obs-reload up-actuator stop-actuator

# Le réseau b6g-core doit exister (make up-core) ; les cibles Prometheus sont générées par core-render.
up-obs: core-render
	$(OBS_COMPOSE) up -d
	@echo "Prometheus :9090  Grafana :3000 (lecture anonyme)  Pushgateway :9091"

down-obs:
	-$(OBS_COMPOSE) down

obs-reload:
	curl -s -X POST http://127.0.0.1:9090/-/reload && echo "Prometheus rechargé"

# Actionneur sur l'hôte, backend tc : il agit dans les conteneurs UPF par docker exec.
# Écoute sur toutes les interfaces : Prometheus (pont Docker) et M2 doivent l'atteindre.
up-actuator:
	@mkdir -p .run data
	B6G_ACTUATOR_BACKEND=tc B6G_LEDGER_URL=$${B6G_LEDGER_URL:-} $(BIN)/uvicorn b6g_actuator.app:app \
		--host 0.0.0.0 --port 8081 > .run/actuator.log 2>&1 & echo $$! > .run/actuator.pid
	@sleep 2; curl -s http://127.0.0.1:8081/v1/health; echo

stop-actuator:
	@[ -f .run/actuator.pid ] && kill $$(cat .run/actuator.pid) 2>/dev/null; rm -f .run/actuator.pid; echo "Actionneur arrêté"

# Export du jeu D1 kpi_timeseries depuis Prometheus (W1.4) : make export-d1 RUN_ID=campagne-01 SINCE=30m
RUN_ID ?= $(shell date -u +%Y%m%dT%H%M%S)
SINCE ?= 30m
FORMAT ?= csv
.PHONY: export-d1
export-d1:
	$(BIN)/python tools/prom_export.py --run-id $(RUN_ID) --since $(SINCE) --format $(FORMAT)
	$(BIN)/python tools/validate_dataset.py datasets/raw/kpi_timeseries-$(RUN_ID).manifest.yaml
