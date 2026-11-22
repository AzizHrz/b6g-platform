# Énergie (M09) : exporteur de consommation conteneurisé (T25.2) et politique de sobriété (T25.3), par l'API Actionneur.
OBS_COMPOSE := docker compose -f platform/observability/compose.yaml
.PHONY: up-energy stop-energy up-green stop-green

# Exporteur sur le réseau b6g-obs (collecté par Prometheus sans passer par le pare-feu de l'hôte)
up-energy:
	$(OBS_COMPOSE) up -d --build energy
	@sleep 2; curl -s http://127.0.0.1:9090/api/v1/query --data-urlencode 'query=b6g_energy_total_power_watts' >/dev/null && echo "Exporteur énergie démarré (conteneur energy)"

stop-energy:
	-$(OBS_COMPOSE) stop energy

up-green:
	@mkdir -p .run
	$(BIN)/python platform/energy/green_policy.py > .run/green.log 2>&1 & echo $$! > .run/green.pid
	@echo "Politique de sobriété démarrée (journal .run/green.log)"

stop-green:
	@if [ -f .run/green.pid ]; then kill $$(cat .run/green.pid) 2>/dev/null; rm -f .run/green.pid; fi; echo "Politique de sobriété arrêtée"
