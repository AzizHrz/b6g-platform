# Boucle de slicing dynamique (M10 v0, T06.4) : slice-autoscaler à seuils, période 5 s.
.PHONY: up-autoscaler stop-autoscaler up-mocks-ia stop-mocks-ia up-loop stop-loop

up-autoscaler:
	@mkdir -p .run
	$(BIN)/python platform/loop/slice_autoscaler.py --period 5 > .run/autoscaler.log 2>&1 & echo $$! > .run/autoscaler.pid
	@echo "slice-autoscaler démarré (journal : .run/autoscaler.log)"

stop-autoscaler:
	@if [ -f .run/autoscaler.pid ]; then kill $$(cat .run/autoscaler.pid) 2>/dev/null; rm -f .run/autoscaler.pid; fi; echo "slice-autoscaler arrêté"

# Mocks d'intelligence de l'équipe 2 (jusqu'à INT5) : Décision :8090, Jumeau :8091 (atelier 26)
up-mocks-ia:
	@mkdir -p .run
	$(BIN)/uvicorn mocks.intelligence.mock_decision:app --port 8090 > .run/mock_decision.log 2>&1 & echo $$! > .run/mock_decision.pid
	$(BIN)/uvicorn mocks.intelligence.mock_twin:app --port 8091 > .run/mock_twin.log 2>&1 & echo $$! > .run/mock_twin.pid
	@sleep 2; curl -s http://127.0.0.1:8090/v1/health; curl -s http://127.0.0.1:8091/v1/health; echo

stop-mocks-ia:
	@for n in mock_decision mock_twin; do if [ -f .run/$$n.pid ]; then kill $$(cat .run/$$n.pid) 2>/dev/null; rm -f .run/$$n.pid; fi; done; echo "Mocks IA arrêtés"

# Boucle MAPE-K complète (M10, atelier 26)
up-loop:
	@mkdir -p .run
	$(BIN)/python platform/loop/act_learn.py --iterations $${ITERATIONS:-10} > .run/loop.log 2>&1 & echo $$! > .run/loop.pid
	@echo "Boucle MAPE-K démarrée (journal .run/loop.log)"

stop-loop:
	@if [ -f .run/loop.pid ]; then kill $$(cat .run/loop.pid) 2>/dev/null; rm -f .run/loop.pid; fi; echo "Boucle arrêtée"
