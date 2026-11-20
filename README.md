# B6G — Déploiement et expérimentation des réseaux B6G

Dépôt unique du projet : plateforme réelle (cœur 5G Open5GS + UERANSIM, observabilité, Actionneur, Kubernetes, registre, énergie, boucle autonome) et modules de simulation et d'intelligence, reliés par des **contrats versionnés**.

État : **jalon INT0** (contrats 1.0.0, scénario, bibliothèque commune, mocks, tests de contrat). Détail : [docs/INT0.md](docs/INT0.md).

## Démarrer (Debian 13 / Ubuntu 22.04+)

Prérequis système, rien d'autre pour INT0 :

```bash
sudo apt update
sudo apt install -y git make python3 python3-venv python3-pip
```

Puis, dans le dépôt :

```bash
make setup            # crée .venv et installe les dépendances Python (dans le dépôt uniquement)
make check            # vérifie l'environnement ; la partie INT1 (Docker, KVM, sctp) est indicative
make test-contracts   # CT-01 à CT-08 contre les mocks : doit être vert pour passer INT0
make test             # lint + tous les tests
```

Pour voir la chaîne complète tourner en HTTP (snapshot → décision → jumeau → action → registre) :

```bash
make run-mocks        # 5 services locaux ; documentation interactive sur http://127.0.0.1:<port>/docs
curl -X POST 127.0.0.1:9100/profile/peak
.venv/bin/python -c "from b6g_common import snapshot; import json; print(json.dumps(snapshot.build('http://127.0.0.1:9100')['slices'], indent=1))"
make stop-mocks
```

## Structure

```
config/scenario.yaml        I-01 : source unique (slices, UEs, niveaux, liens, ports, SLA)
contracts/                  schémas JSON 2020-12, OpenAPI 3.1, datasets.yaml, exemples, CHANGELOG
libs/b6g_common/            scenario.load(), snapshot.build(), validate(), events.make(), actions.check()
platform/actuator/          Actionneur (I-04) : backend memory à INT0, tc / kubectl à INT1
platform/ …                 core/ ran/ observability/ k8s/ vm/ ledger/ energy/ loop/ attack-lab/ (à venir)
intelligence/               modules de simulation et d'IA (à venir)
mocks/platform/             fake_exporter (I-02), mock_ledger (I-07)
mocks/intelligence/         mock_decision (I-05), mock_twin (I-06)
datasets/samples/           D1 à D8, 100 lignes + manifeste
tests/contract/             CT-01 à CT-08
tools/                      env_check, make_samples, validate_dataset
ateliers/_template/         gabarit de README d'atelier
```

## Contribuer

- Règles de collaboration (branches, pull requests, fichiers à risque de conflit) : [CONTRIBUTING.md](CONTRIBUTING.md).
- Préparation de l'environnement, étape par étape : [docs/setup/ENVIRONMENT.md](docs/setup/ENVIRONMENT.md) ; journal : [docs/setup/SETUP_LOG.md](docs/setup/SETUP_LOG.md).

## Règles de travail

- Toute action sur la plateforme passe par l'Actionneur (`POST /v1/actions`, ou une politique `decide()`), jamais par `tc`, `docker` ou `kubectl` lancés directement : chaque action est ainsi validée, journalisée et inscrite au registre.
- Modifier `contracts/` ou `config/` : branche `common/<sujet>`, entrée dans `contracts/CHANGELOG.md`, `make test-contracts` vert.
- Branches courtes `t1/<tâche>-<sujet>` et `t2/<tâche>-<sujet>`, fusion en squash, tags `int0` … `int6`.
- Rien de lourd ni de secret dans Git (voir `.gitignore`).
