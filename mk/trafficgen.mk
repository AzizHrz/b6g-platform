# Sondes trafficgen (M02, T03.2) : latence et perte par slice -> Pushgateway.
.PHONY: up-probes stop-probes

up-probes:
	@mkdir -p .run
	$(BIN)/python platform/trafficgen/probe.py --period 5 > .run/probes.log 2>&1 & echo $$! > .run/probes.pid
	@sleep 6; tail -1 .run/probes.log

stop-probes:
	@if [ -f .run/probes.pid ]; then kill $$(cat .run/probes.pid) 2>/dev/null; rm -f .run/probes.pid; fi; echo "Sondes arrêtées"
