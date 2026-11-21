# Boucle de slicing dynamique (M10 v0, T06.4) : slice-autoscaler à seuils, période 5 s.
.PHONY: up-autoscaler stop-autoscaler

up-autoscaler:
	@mkdir -p .run
	$(BIN)/python platform/loop/slice_autoscaler.py --period 5 > .run/autoscaler.log 2>&1 & echo $$! > .run/autoscaler.pid
	@echo "slice-autoscaler démarré (journal : .run/autoscaler.log)"

stop-autoscaler:
	@if [ -f .run/autoscaler.pid ]; then kill $$(cat .run/autoscaler.pid) 2>/dev/null; rm -f .run/autoscaler.pid; fi; echo "slice-autoscaler arrêté"
