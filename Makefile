# B6G — commandes communes. INT0 : `make setup && make test`
PY      ?= python3
VENV    := .venv
BIN     := $(VENV)/bin
export B6G_ROOT := $(CURDIR)

# Chaque module ajoute ses cibles dans mk/<module>.mk (évite les conflits sur ce fichier)
-include mk/*.mk

.PHONY: help setup check test test-contracts lint samples run-mocks stop-mocks clean

help:
	@echo "make setup           crée .venv et installe les dépendances (rien n'est installé hors du dépôt)"
	@echo "make check           vérifie l'environnement (INT0 obligatoire, INT1 indicatif)"
	@echo "make test-contracts  lance CT-01 à CT-08 contre les mocks (passage d'INT0)"
	@echo "make test            lint + tous les tests"
	@echo "make samples         régénère contracts/examples/ et datasets/samples/"
	@echo "make run-mocks       démarre fake_exporter, actionneur, registre, décision, jumeau en local"
	@echo "make stop-mocks      arrête les mocks"

$(BIN)/python:
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip

setup: $(BIN)/python
	$(BIN)/pip install -q -r requirements-dev.txt
	@echo "Environnement prêt : source $(VENV)/bin/activate"

check: $(BIN)/python
	$(BIN)/python tools/env_check.py

test-contracts:
	$(BIN)/pytest -m ct

lint:
	$(BIN)/ruff check .

test: lint
	$(BIN)/pytest

samples:
	$(BIN)/python tools/make_samples.py

run-mocks:
	@mkdir -p .run data
	$(BIN)/uvicorn mocks.platform.fake_exporter:app --port 9100 > .run/fake_exporter.log 2>&1 & echo $$! > .run/fake_exporter.pid
	B6G_LEDGER_FILE=data/ledger.jsonl $(BIN)/uvicorn mocks.platform.mock_ledger:app --port 8082 > .run/ledger.log 2>&1 & echo $$! > .run/ledger.pid
	B6G_LEDGER_URL=http://127.0.0.1:8082 $(BIN)/uvicorn b6g_actuator.app:app --port 8081 > .run/actuator.log 2>&1 & echo $$! > .run/actuator.pid
	$(BIN)/uvicorn mocks.intelligence.mock_decision:app --port 8090 > .run/decision.log 2>&1 & echo $$! > .run/decision.pid
	$(BIN)/uvicorn mocks.intelligence.mock_twin:app --port 8091 > .run/twin.log 2>&1 & echo $$! > .run/twin.pid
	@sleep 2; echo "Mocks : exporter :9100  actionneur :8081  registre :8082  décision :8090  jumeau :8091 (docs : /docs)"

stop-mocks:
	@for f in .run/*.pid; do [ -f $$f ] && kill $$(cat $$f) 2>/dev/null; rm -f $$f; done; echo "Mocks arrêtés"

clean: stop-mocks
	rm -rf .pytest_cache .ruff_cache .run
