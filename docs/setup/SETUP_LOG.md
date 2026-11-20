# Journal de préparation de l'environnement

Une entrée par étape réalisée, la plus récente en bas. Ce journal sert de preuve de configuration pour le rapport : il permet de rejouer l'installation sur une autre machine.

## Modèle d'entrée

```markdown
### AAAA-MM-JJ — <titre de l'étape> (étape N du guide)

- **Objectif** : pourquoi cette étape, quel atelier en dépend.
- **Machine** : Debian 13, noyau <uname -r>.
- **Commandes** :
  ```bash
  <commandes exactes>
  ```
- **Résultat** : versions installées, sortie utile (résumée).
- **Vérification** : commande de contrôle et résultat attendu / obtenu.
- **Problèmes et solutions** : erreur rencontrée, cause, correction (ou « aucun »).
- **Retour arrière** : comment annuler l'étape.
```

## Entrées

### 2026-11-21 — Inventaire matériel (étape 0 du guide)

- **Objectif** : dimensionner les profils de démarrage et identifier les prérequis manquants pour INT1.
- **Machine** : Debian 13.7, noyau 6.12.115+deb13.1-amd64.
- **Commandes** :
  ```bash
  free -h; nproc; df -h ~
  lscpu | grep -i virtualization; ls -l /dev/kvm
  nvidia-smi
  lsmod | grep sctp; /usr/sbin/modinfo sctp
  python3 --version; git --version; docker --version; docker compose version
  ```
- **Résultat** :

  | Ressource | Valeur relevée | Évaluation |
  | --- | --- | --- |
  | CPU | Intel Core i7-13800H, 14 cœurs / 20 threads | Confortable |
  | RAM | 30 Gio (≈ 16 Gio disponibles au relevé), swap 24 Gio | Confortable |
  | Disque libre (`/`) | 27 Go sur 444 Go (94 % utilisé) | **Sous le minimum (60 Go)** |
  | Virtualisation | VT-x activé, `/dev/kvm` présent, utilisateur dans `kvm` et `libvirt` | OK |
  | GPU | NVIDIA RTX 2000 Ada, 8 Gio, pilote 550.163.01, CUDA 12.4 | OK (atelier 23) |
  | SCTP | module `sctp.ko.xz` disponible, **non chargé** | À charger (étape 2) |
  | Outils présents | Python 3.13.5, Git 2.47.3, GNU Make 4.4.1, Docker 29.9.3, Compose 5.7.0, QEMU 10.0.13, `tc` (iproute2 6.15.0), tcpdump, jq, Wireshark, virsh | — |
  | Outils absents | iperf3, kubectl, k3d, Helm, Ollama | Installés aux étapes concernées |

- **Vérification** : valeurs ci-dessus relevées le 2026-11-21.
- **Problèmes et solutions** : espace disque insuffisant pour les images Docker et la VM de l'atelier 7 ; libérer au moins 35 Go avant l'étape 2.
- **Retour arrière** : sans objet (relevé en lecture seule).

### 2026-11-21 — Git, SSH, Python et dépôt (étape 1 du guide)

- **Objectif** : disposer du dépôt local et de l'environnement Python requis pour INT0.
- **Machine** : Debian 13.7, noyau 6.12.115+deb13.1-amd64.
- **Commandes** :
  ```bash
  cd ~/Projects/B6G
  git init -b main
  ssh -T git@github.com
  make setup
  make check
  make test
  ```
- **Résultat** : paquets système déjà présents (git, make, python3-venv), aucune installation système nécessaire. Authentification SSH GitHub fonctionnelle. `.venv` créé ; dépendances de `requirements-dev.txt` installées.
- **Vérification** : `make check` : partie INT0 entièrement OK (Python 3.13.5, modules, `config/scenario.yaml` : 3 slices, 30 UEs). `make test` : lint `ruff` sans erreur, 82 tests réussis.
- **Problèmes et solutions** : `make check` signale `tc` absent et le module `sctp` non vérifiable, car `/usr/sbin` n'est pas dans le `PATH` de l'utilisateur ; `tc` est bien installé (`/usr/sbin/tc`).
- **Retour arrière** : `make clean && rm -rf .venv` ; `rm -rf .git`.
