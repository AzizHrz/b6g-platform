# Préparation de l'environnement B6G

Ce guide installe l'environnement de travail **par étapes, au rythme des jalons**. On n'installe un outil qu'au moment où un atelier en a besoin, et on vérifie chaque étape avant de passer à la suivante.

- **Système de référence** : Debian 13 (trixie), en natif. Ubuntu 22.04 / 24.04 convient aussi, avec les mêmes commandes, sauf le dépôt APT de Docker (`ubuntu` au lieu de `debian`).
- **Dossier du projet** : un seul dossier, par exemple `~/Projects/B6G`.
- **Hors du dépôt** : les données et outils lourds restent dans `~/b6g-data`, `~/b6g-ext` et `~/b6g-sim`.
- **Traçabilité** : chaque étape réalisée est consignée dans [SETUP_LOG.md](SETUP_LOG.md). Chaque version installée est notée dans [../versions.lock](../versions.lock).

| Étape | Jalon | Ateliers | Contenu | Obligatoire |
| --- | --- | --- | --- | --- |
| 0 | Avant tout | — | Vérification du matériel | Oui |
| 1 | INT0 | 1 | Git, SSH, Python, dépôt | Oui |
| 2 | INT1 | 1, 3, 4, 6, 9 | Docker Engine, module SCTP, outils réseau | Oui |
| 3 | INT1 | 3 | Wireshark | Recommandé |
| 4 | INT3 | 8, 10, 12 | k3d, kubectl, Helm | Oui |
| 5 | Atelier 7 | 7 | KVM, libvirt | Oui |
| 6 | INT4 | 21 | Hyperledger Fabric | Oui (repli : registre simulé) |
| 7 | Atelier 23 | 23 | Ollama et modèle `llama3.2:3b` | Oui |
| 8 | Équipe 2 | 15–20, 22 | Bibliothèques de simulation et d'IA | Selon le module |

## Étape 0 — Vérifier le matériel

```bash
free -h                       # RAM totale et disponible
nproc                         # nombre de cœurs
df -h ~                       # espace disque libre
lscpu | grep -i virtualization   # VT-x / AMD-V
ls -l /dev/kvm                # présent si la virtualisation est activée dans le BIOS
nvidia-smi 2>/dev/null || echo "pas de GPU NVIDIA détecté"
```

| Ressource | Minimum | Confortable | Remarque |
| --- | --- | --- | --- |
| RAM | 16 Go | 32 Go | Avec 16 Go, démarrer les profils un par un (cœur + observabilité + un autre bloc) |
| Disque libre | 60 Go | 100 Go | Images Docker, image de VM, jeux de données |
| CPU | 4 cœurs | 8 cœurs | k3d et Fabric sont gourmands au démarrage |
| Virtualisation | VT-x / AMD-V activé | — | Nécessaire pour l'atelier 7 |
| GPU | Aucun | NVIDIA | Accélère seulement l'atelier 23 |

**Vérification** : valeurs reportées dans `SETUP_LOG.md` (entrée « Inventaire matériel »).

## Étape 1 — Git, SSH, Python et dépôt (INT0)

```bash
sudo apt update
sudo apt install -y git make python3 python3-venv python3-pip curl ca-certificates
git config --global user.name  "Prénom Nom"
git config --global user.email "adresse@exemple.com"
git config --global pull.rebase true
git config --global init.defaultBranch main
```

Clé SSH pour GitHub (à ajouter dans *GitHub → Settings → SSH and GPG keys*) :

```bash
ssh-keygen -t ed25519 -C "adresse@exemple.com"
cat ~/.ssh/id_ed25519.pub
ssh -T git@github.com          # doit afficher « Hi <identifiant>! »
```

Dépôt et environnement Python (aucune installation hors du dépôt) :

```bash
cd ~/Projects/B6G
make setup                     # crée .venv et installe les dépendances
make check                     # inventaire : Python, modules, outils, RAM, KVM, sctp
make test-contracts            # CT-01 à CT-08 contre les mocks : doit être vert
```

**Vérification** : `make test` vert ; `python3 --version` ≥ 3.11.

## Étape 2 — Docker Engine, SCTP et outils réseau (INT1)

Docker Engine depuis le dépôt officiel de Docker. Le paquet `docker.io` de Debian fonctionne aussi, mais il est souvent plus ancien.

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "$USER"     # puis se déconnecter et se reconnecter
```

> Être membre du groupe `docker` donne des droits équivalents à `root` sur la machine. C'est acceptable sur un poste de développement personnel, pas sur une machine partagée.

Module noyau SCTP (interface N2 entre le gNB et l'AMF d'Open5GS), chargé maintenant et à chaque démarrage :

```bash
sudo modprobe sctp
echo sctp | sudo tee /etc/modules-load.d/sctp.conf
```

Outils réseau utilisés par l'Actionneur et les mesures :

```bash
sudo apt install -y iproute2 iperf3 tcpdump jq
```

**Vérification** :

```bash
docker run --rm hello-world
docker compose version
lsmod | grep sctp
tc -V && iperf3 --version
```

> **Distrobox** : s'il utilise Podman, Docker et Podman cohabitent sans problème. S'il utilise Docker, les conteneurs Distrobox apparaissent dans `docker ps`. Ne pas les supprimer par erreur avec `docker system prune`.

## Étape 3 — Wireshark (INT1, recommandé)

```bash
sudo apt install -y wireshark       # répondre « Oui » pour autoriser la capture sans root
sudo usermod -aG wireshark "$USER"
```

Utilisé pour analyser les captures NGAP, NAS, PFCP et GTP-U de l'atelier 3.

## Étape 4 — Kubernetes léger : k3d, kubectl, Helm (INT3)

k3d fait tourner un cluster k3s dans des conteneurs Docker : pas de VM par nœud. Installer des versions **fixées** et les noter dans `versions.lock`. Les scripts d'installation officiels acceptent une version précise.

```bash
# k3d (remplacer vX.Y.Z par la version retenue)
curl -s https://raw.githubusercontent.com/k3d-io/k3d/main/install.sh | TAG=vX.Y.Z bash
# kubectl : dépôt officiel pkgs.k8s.io (voir https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/)
# Helm 3
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

**Vérification** :

```bash
k3d version && kubectl version --client && helm version
k3d cluster create b6g-test --agents 1 && kubectl get nodes && k3d cluster delete b6g-test
```

## Étape 5 — Virtualisation KVM (atelier 7)

GNS3 a peut-être déjà installé QEMU. Vérifier avant d'installer : `qemu-system-x86_64 --version`.

```bash
sudo apt install -y qemu-system-x86 qemu-utils libvirt-daemon-system libvirt-clients virtinst cloud-image-utils
sudo usermod -aG libvirt,kvm "$USER"
```

> Ne pas installer VirtualBox sous Debian : il entre en conflit avec KVM pour l'accès à la virtualisation matérielle.

**Vérification** : `virsh list --all` fonctionne sans `sudo` ; `ls -l /dev/kvm` appartient au groupe `kvm`.

## Étape 6 — Hyperledger Fabric (INT4, atelier 21)

À installer **hors du dépôt**, dans `~/b6g-ext/fabric`. Nécessite Docker (étape 2).

```bash
mkdir -p ~/b6g-ext/fabric && cd ~/b6g-ext/fabric
curl -sSLO https://raw.githubusercontent.com/hyperledger/fabric/main/scripts/install-fabric.sh
chmod +x install-fabric.sh
./install-fabric.sh docker samples binary
```

**Vérification** : `cd fabric-samples/test-network && ./network.sh up createChannel` puis `./network.sh down`.

**Repli** : si Fabric ne démarre pas en une journée, garder le registre simulé (`mocks/platform/mock_ledger.py`, journal chaîné SHA-256), étiqueté MAQUETTE.

## Étape 7 — Ollama et modèle de langage (atelier 23)

Ollama est déjà installé sous Debian. Il suffit de télécharger le modèle :

```bash
ollama --version
ollama pull llama3.2:3b
ollama run llama3.2:3b "Réponds OK"
```

Sans GPU, le modèle tourne sur le CPU. C'est plus lent, mais suffisant pour les essais de l'atelier.

## Étape 8 — Simulation et IA (équipe 2)

Les bibliothèques Python s'ajoutent au `.venv` du dépôt, au fur et à mesure des modules (voir `requirements-dev.txt` et les `pyproject.toml` des modules). Exemples :

| Module | Paquets | Remarque |
| --- | --- | --- |
| Données et IA | `pandas`, `pyarrow`, `scikit-learn` | — |
| Jumeau numérique | `simpy` | — |
| Optimisation et quantique | `pulp`, `qiskit`, `qiskit-aer`, `qiskit-optimization` | Environnement virtuel séparé si conflit de versions |
| Mobilité | `eclipse-sumo` (SUMO via pip) | ns-3 et SUMO 1.18 en Distrobox Ubuntu 22.04 seulement si le plan l'exige |

## Démarrage et arrêt des services

La mémoire est limitée. Chaque bloc se démarre et s'arrête séparément. Les cibles `make up-*` sont ajoutées au fil des jalons dans `mk/*.mk` : `up-core`, `up-obs`, `up-k8s`, `up-ledger`, `up-vm`.

```bash
docker stats --no-stream          # consommation des conteneurs
free -h                           # mémoire restante
```
