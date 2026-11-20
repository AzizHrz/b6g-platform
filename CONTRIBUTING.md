# Contribuer au projet B6G

Ce guide s'adresse à tous les membres des deux équipes. Il fixe une seule manière de travailler, pour que les *pull requests* se fusionnent sans conflit ni surprise.

## 1. Premier démarrage

1. Accepter l'invitation à l'organisation GitHub du projet. Chaque membre est rattaché à l'équipe `equipe-1` ou `equipe-2`.
2. Configurer Git avec votre identité :
   ```bash
   git config --global user.name  "Prénom Nom"
   git config --global user.email "adresse@exemple.com"
   git config --global pull.rebase true
   git config --global rebase.autoStash true
   git config --global init.defaultBranch main
   ```
3. Ajouter une clé SSH à votre compte GitHub (*Settings → SSH and GPG keys*), puis cloner le dépôt :
   ```bash
   git clone git@github.com:<organisation>/<dépôt>.git
   cd <dépôt>
   make setup && make test
   ```
   `make test` doit être vert avant toute contribution.
4. Pour installer le reste de l'environnement, suivre le guide [docs/setup/ENVIRONMENT.md](docs/setup/ENVIRONMENT.md).

## 2. Qui possède quoi

Le fichier [.github/CODEOWNERS](.github/CODEOWNERS) désigne automatiquement les relecteurs.

| Dossiers | Propriétaire | Relecture d'une modification |
| --- | --- | --- |
| `platform/`, `mocks/platform/`, `tools/` | Équipe 1 | 1 membre de l'équipe 1 |
| `intelligence/`, `mocks/intelligence/`, `datasets/`, `models/` | Équipe 2 | 1 membre de l'équipe 2 |
| `config/`, `contracts/`, `libs/`, `tests/`, `docs/`, `report/` | **Commun** | 1 membre de **chaque** équipe |
| `ateliers/aXX/` | Responsable de l'atelier | Le responsable de l'atelier |
| `.github/`, `Makefile`, `pyproject.toml`, `README.md` | Responsable de l'intégration | Le responsable de l'intégration |

Les dossiers communs n'appartiennent à aucune équipe en particulier :

| Dossier | Rôle |
| --- | --- |
| `config/` | Dit **quoi** construire : `scenario.yaml` est la description unique du réseau. |
| `contracts/` | Dit **comment** échanger : schémas JSON, OpenAPI et journal des versions. |
| `libs/b6g_common/` | Fournit les **outils** communs : chargement du scénario, construction du snapshot, validation. |
| `tests/` | **Prouve** que l'ensemble s'emboîte : tests de contrat, d'intégration et de démonstration. |

## 3. Branches

| Branche | Usage | Exemple |
| --- | --- | --- |
| `main` | Seule branche permanente. Toujours fonctionnelle. **Protégée** : ni push direct, ni force-push, ni suppression | — |
| `t1/<tâche>-<sujet>` | Une tâche de l'équipe 1 | `t1/T06.2-slicing` |
| `t2/<tâche>-<sujet>` | Une tâche de l'équipe 2 | `t2/T24.1-forecast` |
| `common/<sujet>` | Modification d'un dossier commun | `common/contracts-1.1.0` |
| `fix/<sujet>` | Correction d'un défaut constaté sur `main` | `fix/snapshot-null-slice` |

Le projet n'a ni branche `develop` ni branche par équipe. Une branche correspond à une tâche du plan, vit **3 jours au plus** et est supprimée après sa fusion.

## 4. Cycle de travail

```bash
git switch main && git pull                      # 1. partir d'un main à jour
git switch -c t1/T06.2-slicing                   # 2. une branche par tâche
# ... travail ...
make test                                        # 3. lint + tests verts
git add -p                                       # 4. ajouter seulement ce qui concerne la tâche
git commit -m "T06.2: limite de débit par slice via tc HTB"
git fetch origin && git rebase origin/main       # 5. se remettre à jour (au moins une fois par jour)
make test
git push -u origin t1/T06.2-slicing              # 6. publier la branche
# 7. ouvrir la pull request (en brouillon dès le début si le travail dure plus d'une journée)
```

**Messages de commit** : `<identifiant de tâche>: <résumé à l'impératif>`. Pour une modification hors tâche, utiliser le préfixe `docs:`, `ci:` ou `fix:`.

## 5. Pull requests

1. Remplir le modèle : tâche, étapes `Axx-Exx`, interfaces touchées, tests lancés, captures.
2. La CI doit être verte : lint `ruff` et tests de contrat CT-01 à CT-08.
3. La branche doit être à jour avec `main`. GitHub bloque la fusion sinon.
4. Les relectures exigées par CODEOWNERS doivent être approuvées, et toutes les conversations résolues.
5. **Fusion en squash uniquement**, par l'auteur. La branche est supprimée automatiquement.

**Taille.** Une PR = une tâche, idéalement moins de 400 lignes modifiées (hors données d'échantillon). Une grosse tâche se découpe en plusieurs PR successives.

**Délais de relecture.** Le relecteur répond dans les 24 heures ouvrées. C'est l'**auteur** qui résout les conflits, jamais le relecteur.

## 6. Fichiers à risque de conflit et règles associées

Ce sont les fichiers que plusieurs personnes modifient en même temps. Chacun a sa règle.

| Fichier ou dossier | Pourquoi il produit des conflits | Règle |
| --- | --- | --- |
| `config/scenario.yaml` | Tous les modules le lisent, chacun veut y ajouter un paramètre | Modification seulement par une PR `common/`, petite et isolée. Une seule PR ouverte à la fois sur ce fichier. Annoncer la modification à l'autre équipe |
| `contracts/*.schema.json`, `contracts/openapi/*` | Fournisseur et consommateurs dépendent du même fichier | PR `common/` relue par les deux équipes, version augmentée. Changement incompatible annoncé 48 h avant. **Gel à INT5** |
| `contracts/CHANGELOG.md` | Tout le monde ajoute une entrée au même endroit | Ajouter sa ligne sous `## À paraître`, une ligne par PR. En cas de conflit, **garder les deux lignes** |
| `requirements-dev.txt`, `pyproject.toml` | Chacun ajoute ses dépendances | Une dépendance par ligne, **ordre alphabétique**, version minimale indiquée |
| `Makefile` | Chaque module veut ses cibles | Ne pas modifier le `Makefile` racine. Ajouter ses cibles dans `mk/<module>.mk`, inclus automatiquement |
| `README.md` racine | Chacun veut y décrire son module | Réservé au responsable de l'intégration. Chaque module se documente dans son dossier ou dans `ateliers/aXX/README.md` |
| Ateliers partagés 1, 2, 27, 28 | Les deux équipes écrivent dans le même README | Chaque équipe écrit sa partie dans un fichier séparé (`ateliers/a27/equipe-1.md`, `ateliers/a27/equipe-2.md`). Le responsable de l'atelier les assemble |
| Configurations Open5GS / UERANSIM générées | Fichiers produits par `render.py` à partir du scénario | Jamais versionnées (`platform/*/generated/` est ignoré). Après une modification du scénario, **régénérer** |
| `datasets/samples/`, `contracts/examples/` | Fichiers produits par `tools/make_samples.py` | En cas de conflit, ne pas fusionner à la main : `make samples`, puis committer le résultat |
| Tableaux de bord Grafana (`*.json`) | JSON volumineux réordonné à chaque export | Un tableau de bord par fichier, un propriétaire par fichier, export avec clés triées |
| Notebooks Jupyter | Sorties et métadonnées changent à chaque exécution | Préférer des scripts `.py`. Sinon, vider les sorties avant le commit (`nbstripout`) |
| Fichiers Docker Compose | Plusieurs services dans un même fichier | Un fichier Compose par module (`platform/<module>/compose.yaml`) |
| `.github/` | Règles du dépôt | Réservé au responsable de l'intégration |
| Fins de ligne | Membres sous Windows et Linux | Normalisées par `.gitattributes` et `.editorconfig`. Ne pas les modifier |

## 7. Ordre de fusion aux jalons

Avant un jalon d'intégration (INT0 à INT6), fusionner dans cet ordre :

1. les PR de **contrats** (`common/`) ;
2. les PR des **fournisseurs** du service (par exemple l'Actionneur) ;
3. les PR des **consommateurs** (par exemple la boucle autonome).

Lancer ensuite le test du jalon (`tests/integration/test_intX.py`). S'il passe, le responsable de l'intégration pose le tag `intX` sur `main`.

## 8. Ce qui ne va jamais dans le dépôt

- **Données lourdes** : captures `.pcap` / `.pcapng`, jeux bruts ou traités, modèles. Elles restent dans `~/b6g-data` et sont référencées par leur manifeste. Seuls les échantillons de `datasets/samples/` (moins de 5 Mo) sont versionnés.
- **Images et outils externes** : images de VM, images Docker, arbres ns-3, `fabric-samples`.
- **Secrets** : kubeconfig, clés, certificats, mots de passe, fichiers `.env`. Le dépôt étant **public**, une fuite est définitive. Si un secret a été poussé par erreur, le **révoquer** immédiatement : le supprimer de l'historique ne suffit pas.
- **Fichiers personnels de travail** (`.local/`, notes locales).

Le fichier `.gitignore` couvre ces cas. Avant chaque commit, vérifier `git status`.

## 9. En cas de problème

| Situation | Que faire |
| --- | --- |
| Conflit pendant `git rebase origin/main` | Corriger les fichiers, `git add <fichier>`, `git rebase --continue`, puis `make test` et `git push --force-with-lease` (sur **sa propre branche** uniquement) |
| Conflit sur un fichier généré | Régénérer (`make samples`, `render.py`) au lieu de fusionner à la main |
| CI rouge sur `main` | Priorité absolue : le responsable de l'intégration ouvre une branche `fix/` ou annule (`git revert`) la PR fautive |
| Contrat modifié qui casse votre module | Ouvrir une issue étiquetée `interface` avec la requête et la réponse observées. Ne pas modifier le contrat dans sa propre PR |
| Commit poussé par erreur sur la mauvaise branche | Ne pas réécrire `main`. Faire `git revert` puis rejouer le travail sur une branche |
