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

### 2026-11-21 — Jalon INT0 validé, tags `int0` et `contracts-1.0.0`

- **Objectif** : valider les contrats 1.0.0 contre les mocks (critère de passage de `docs/INT0.md`).
- **Machine** : Debian 13.7, noyau 6.12.115+deb13.1-amd64.
- **Commandes** :
  ```bash
  make test-contracts
  make run-mocks          # chaîne snapshot → décision → jumeau → actionneur → registre, profils peak et incident
  make stop-mocks
  git tag int0 && git tag contracts-1.0.0
  git push origin int0 contracts-1.0.0
  ```
- **Résultat** : 82 tests de contrat réussis (CT-01 à CT-08 et validité des schémas). Chaîne HTTP complète fonctionnelle ; registre : 10 événements, `hash_match` et `chain_ok` vrais. Résultats étiquetés SYNTHÉTIQUE / MAQUETTE.
- **Vérification** : `git ls-remote --tags origin` liste `int0` et `contracts-1.0.0`.
- **Problèmes et solutions** : aucun.
- **Retour arrière** : `git push origin :refs/tags/int0 :refs/tags/contracts-1.0.0` puis `git tag -d int0 contracts-1.0.0`.

### 2026-11-21 — Module SCTP et outils réseau (étape 2 du guide, partielle)

- **Objectif** : prérequis noyau de l'interface N2 (gNB ↔ AMF) et outils de mesure de l'Actionneur, pour INT1.
- **Machine** : Debian 13.7, noyau 6.12.115+deb13.1-amd64.
- **Commandes** :
  ```bash
  sudo modprobe sctp
  echo sctp | sudo tee /etc/modules-load.d/sctp.conf
  sudo apt install -y iperf3      # démon iperf3 non activé au démarrage
  ```
- **Résultat** : module `sctp` chargé et persistant ; iperf3 3.18 installé (service `iperf3` désactivé). Docker Engine 29.9.3, Compose 5.7.0, `tc` (iproute2 6.15.0), tcpdump et jq déjà présents.
- **Vérification** : `lsmod | grep sctp` ; `cat /etc/modules-load.d/sctp.conf` ; `iperf3 --version` ; `systemctl is-enabled iperf3` → `disabled`.
- **Problèmes et solutions** : espace disque libre toujours insuffisant (27 Go, minimum 60 Go) ; à libérer avant le téléchargement des images Open5GS / UERANSIM.
- **Retour arrière** : `sudo rm /etc/modules-load.d/sctp.conf && sudo modprobe -r sctp` ; `sudo apt remove iperf3`.

### 2026-11-21 — Registre d'images local (T01.5, étape 2 du guide)

- **Objectif** : registre `registry:2` sur le port 5000 (I-12), utilisé à partir des ateliers 8, 9 et 12.
- **Machine** : Debian 13.7, noyau 6.12.115+deb13.1-amd64 ; espace disque libéré : 105 Go disponibles.
- **Commandes** :
  ```bash
  make up-registry
  make registry-check      # push puis pull de busybox:1.37 via 127.0.0.1:5000
  ```
- **Résultat** : registre actif ; catalogue `{"repositories":["b6g/busybox"]}`.
- **Vérification** : `curl -s http://127.0.0.1:5000/v2/_catalog`.
- **Problèmes et solutions** : aucun.
- **Retour arrière** : `make down-registry` puis `docker volume rm b6g-registry_b6g-registry`.

### 2026-11-21 — Cœur Open5GS à 3 slices et RAN UERANSIM, 30 UEs (T03.1)

- **Objectif** : plateforme v0 du jalon INT1 (ateliers 3, 4 et 6).
- **Machine** : Debian 13.7, Docker Engine 29.9.3, Compose 5.7.0.
- **Commandes** :
  ```bash
  docker pull gradiant/open5gs:2.7.7 gradiant/ueransim:3.2.8 mongo:6.0
  make up-core             # platform/core/render.py génère toutes les configurations depuis config/scenario.yaml
  make core-status
  docker exec ue-v2x ping -I uesimtun0 -c 3 10.46.0.1
  ```
- **Résultat** : 11 fonctions Open5GS (une SMF et une UPF par slice), 1 gNB, 30 UEs enregistrés, 30 sessions PDU
  (10 par slice). 5QI 83 accepté pour la slice v2x. RTT UE → passerelle UPF ≈ 2 à 3 ms ; sortie N6 vers 8.8.8.8 sans perte.
- **Vérification** : `make core-status` (10 interfaces `uesimtun` par conteneur d'UE) ; journaux UPF
  « Number of UPF-Sessions is now 10 » pour chaque slice ; AMF « Number of AMF-UEs is now 30 ».
- **Problèmes et solutions** :
  - UPF en redémarrage en boucle, erreur `ioctl(TUNSETIFF): Operation not permitted`. Cause : l'image Open5GS
    s'exécute sous l'utilisateur non privilégié `open5gs` (uid 999) ; la capacité `NET_ADMIN` est sans effet pour lui.
    Correction : UPF exécutées en `root` (`user: root`) ; script `platform/core/upf-entrypoint.sh` pour `ogstun` et la NAT.
  - 48 échecs d'enregistrement initiaux (cause 90) pendant le redémarrage des UPF ; résorbés automatiquement par
    les nouvelles tentatives des UEs une fois les UPF disponibles.
- **Retour arrière** : `make down-core` ; `docker volume rm b6g-core_b6g-mongo` pour effacer les abonnés.

### 2026-11-21 — Observabilité : Prometheus, Pushgateway, cAdvisor, Grafana (W1.3)

- **Objectif** : métriques `b6g_*` du contrat I-02 sur un Prometheus réel (port 9090).
- **Machine** : Debian 13.7, Docker Engine 29.9.3 (magasin d'images containerd).
- **Commandes** :
  ```bash
  make up-obs
  make obs-reload
  curl -s http://127.0.0.1:9090/api/v1/targets
  ```
- **Résultat** : Prometheus 2.55.1, Pushgateway 1.11.1, cAdvisor 0.55.1, Grafana 10.4.19 ; règles
  `platform/observability/rules/b6g.rules.yml` ; tableau de bord « B6G — Plateforme v0 (INT1) ».
- **Vérification** : toutes les cibles `open5gs`, `cadvisor`, `pushgateway` à l'état `up` ;
  `b6g_ue_registered` = 30 ; `b6g_slice_sessions` = 10 par slice.
- **Problèmes et solutions** :
  - cAdvisor 0.49.1 (version cible du plan) n'identifie aucun conteneur : « failed to identify the read-write layer ID ».
    Cause : Docker 29 utilise le magasin d'images containerd (`io.containerd.snapshotter.v1`), inconnu de cAdvisor 0.49.
    Correction : cAdvisor 0.55.1.
  - Cible `actuator` injoignable depuis Prometheus (délai dépassé). Cause : pare-feu UFW actif sur l'hôte, qui bloque
    les réseaux Docker vers le port 8081. Correction (à exécuter par l'administrateur) :
    `sudo ufw allow from 172.16.0.0/12 to any port 8081 proto tcp comment 'B6G Prometheus vers Actionneur'`.
- **Retour arrière** : `make down-obs` ; `sudo ufw delete allow from 172.16.0.0/12 to any port 8081 proto tcp`.

### 2026-11-21 — Actionneur v1, backend tc (W1.2)

- **Objectif** : appliquer `slice.bandwidth` sur la plateforme réelle (I-04), seul point d'action.
- **Commandes** :
  ```bash
  make up-actuator         # uvicorn sur 0.0.0.0:8081, B6G_ACTUATOR_BACKEND=tc
  curl -X POST http://127.0.0.1:8081/v1/actions -H 'X-B6G-Caller: essai' -H 'Content-Type: application/json' \
       -d '{"type":"slice.bandwidth","target":"v2x","params":{"rate_mbps":5,"ceil_mbps":10},"reason":"essai"}'
  ```
- **Résultat** : sens descendant par HTB dans `upf-<slice>` (classe 1:1 au plafond, classe 1:10 rate / ceil) ;
  sens montant par policer en entrée de `ogstun`, plafonné à ceil. Les types v2 (`link.netem`, `deployment.*`,
  `ue.*`, `slice.state`) sont refusés explicitement (prévus à INT3).
- **Vérification** (iperf3, slice v2x, réalisme ÉMULÉ) :

  | Réglage | Sens descendant mesuré | Sens montant mesuré |
  | --- | --- | --- |
  | rate 20 / ceil 40 (scénario) | 38,4 Mbit/s | — |
  | rate 5 / ceil 10 (action) | 9,44 Mbit/s | 9,64 Mbit/s |

- **Problèmes et solutions** :
  - Première version : classe HTB unique à la racine ; le débit plafonnait à `rate` (19,1 Mbit/s) car une classe racine
    ne peut rien emprunter. Correction : classe parente 1:1 au plafond.
  - `tc qdisc replace … htb` échoue sur une racine HTB existante (« Change operation not supported »). L'Actionneur a
    renvoyé `503 Échec du backend` et compté l'action `failed`, sans rien prétendre. Correction : création de la
    racine seulement si elle est absente.
- **Retour arrière** : `make stop-actuator` ; `docker exec -u 0 upf-<slice> tc qdisc del dev ogstun root`.

### 2026-11-21 — Sondes trafficgen : latence et perte par slice (T03.2, partiel)

- **Objectif** : alimenter `b6g_slice_latency_ms` et `b6g_slice_loss_ratio` (I-02).
- **Commandes** :
  ```bash
  make up-probes           # platform/trafficgen/probe.py, toutes les 5 s
  curl -s http://127.0.0.1:9091/metrics | grep '^b6g_'
  ```
- **Résultat** : latence UE → passerelle UPF p50 ≈ 2,2 ms, p95 ≈ 3 ms, perte nulle sur les 3 slices (ÉMULÉ).
- **Vérification** : séries présentes dans la Pushgateway et dans Prometheus.
- **Problèmes et solutions** : aucun.
- **Retour arrière** : `make stop-probes`.

### 2026-11-21 — Jalon INT1 validé sur M1

- **Objectif** : critère de passage d'INT1 (plan maître § 9.3).
- **Commandes** :
  ```bash
  sudo ufw allow from 172.16.0.0/12 to any port 8081 proto tcp comment 'B6G Prometheus vers Actionneur'
  .venv/bin/pytest -m int tests/integration/test_int1.py -v
  ```
- **Résultat** : 16 tests réussis, 6 ignorés (métriques dont le producteur arrive à INT3–INT5), 0 échec.
  Détail : `docs/INT1.md`.
- **Vérification** : `snapshot.build('http://127.0.0.1:9090')` conforme à `metric-snapshot.schema.json`, 10 sessions
  et latence mesurée pour chaque slice.
- **Problèmes et solutions** : voir les entrées T03.1, W1.3 et W1.2 ci-dessus.
- **Retour arrière** : `make stop-probes stop-actuator down-obs down-core down-registry`.

### 2026-11-21 — Outils d'expérimentation des ateliers 4 et 6

- **Objectif** : trafics simultanés des 30 UEs (T04.2, T06.3), figures des ateliers, boucle de slicing dynamique (T06.4).
- **Commandes** :
  ```bash
  make setup                         # ajout de matplotlib>=3.8 dans requirements-dev.txt (installé dans .venv)
  make up-core                       # conteneur iperf : 30 serveurs iperf3, ports 5201 à 5230
  docker exec iperf sh -c 'ss -ltn | grep -c ":52[0-3][0-9]"'
  make up-autoscaler                 # puis make stop-autoscaler
  ```
- **Résultat** : matplotlib 3.11.2 dans `.venv` ; 30 serveurs iperf3 à l'écoute ; slice-autoscaler opérationnel.
- **Vérification** : `ss` compte 30 ports ; `results/` des ateliers 4 et 6 produits.
- **Problèmes et solutions** :
  - Serveurs iperf3 non démarrés (« Usage: iperf3 … »). Cause : Docker Compose remplace `$p` et `$(seq …)` par
    ses propres variables (vides). Correction : échappement `$$` dans la commande générée par `render.py`.
  - Débit UDP surestimé en mode inverse (`-R`) : le champ `end.sum` d'iperf3 porte le débit émis. Correction :
    lecture de `end.sum_received` (débit reçu) dans `platform/trafficgen/load.py` ; mesures des ateliers 4 et 6 refaites.
  - Écart de −13 % à −16 % sur la slice miot avec 10 flux TCP : goodput TCP réduit par les pertes dans la file HTB à
    faible débit (4 955 paquets rejetés). Méthode de référence retenue pour le contrôle des plafonds : UDP à 1,5 × ceil
    (écart −2,3 %, en-têtes IP/UDP).
- **Retour arrière** : `make stop-autoscaler` ; retrait de matplotlib de `requirements-dev.txt` puis `make setup`.

### 2026-11-21 — Test global de l'environnement et documentation (T01.4, T01.6, étapes 0, 3 et 5 du guide)

- **Objectif** : critère de l'atelier 1 (`make env-check` vert sur M1) ; outils de capture de l'atelier 3 ;
  outils de virtualisation de l'atelier 7.
- **Machine** : Debian 13.7, noyau 6.12.115+deb13.1-amd64.
- **Commandes** :
  ```bash
  sudo apt install -y tshark                                   # administrateur ; capture non-root : « Non »
  echo '127.0.0.1 b6g-plat b6g-intel' | sudo tee -a /etc/hosts  # administrateur ; une seule machine pour l'instant
  make env-check                                               # tools/env_check.py
  make vm-check                                                # platform/vm/install_vm_tools.sh
  bash platform/install_docker.sh
  ```
- **Résultat** : tshark 4.4.19 ; `b6g-plat` et `b6g-intel` résolus vers 127.0.0.1. `make env-check` : bloc INT0 entièrement
  OK, matériel conforme au plan § 4.2, SCTP chargé, horloge synchronisée (NTP), Prometheus / Grafana / Actionneur /
  registre joignables ; restent indicatifs k3d, kubectl, Helm (atelier 8). `make vm-check` : VT-x, `/dev/kvm`,
  QEMU 10.0.13, libvirt 11.3.0, virt-install 5.0.0, xorriso, groupes `libvirt` et `kvm`, `virsh` sans sudo.
- **Vérification** : sorties des trois commandes ; `getent hosts b6g-plat`.
- **Problèmes et solutions** :
  - `make check` signalait `tc` absent et SCTP « non vérifiable » : `/usr/sbin` hors du `PATH` utilisateur et
    `modinfo` introuvable. Correction : recherche des outils aussi dans `/usr/sbin` et `/sbin`, lecture de `/proc/modules`.
  - `cloud-image-utils` (cloud-localds) absent : l'image de démarrage cloud-init de l'atelier 7 sera construite avec
    `xorriso`, déjà installé.
  - Réseau libvirt `default` inactif : à démarrer à l'atelier 7 (`virsh -c qemu:///system net-start default`).
- **Retour arrière** : `sudo apt remove tshark` ; retirer la ligne `b6g-plat b6g-intel` de `/etc/hosts`.

### 2026-11-21 — Captures de signalisation de l'atelier 3 (T03.3)

- **Objectif** : observer NGAP, NAS-5GS, SBI, PFCP et GTP-U sans installer d'outil de capture dans les conteneurs.
- **Commandes** : conteneurs `tcpdump` (image `gradiant/open5gs:2.7.7`, qui contient tcpdump) attachés à l'espace
  réseau de chaque fonction (`--net container:<nf>`), puis `docker cp` des fichiers et décodage
  `ateliers/a03/decode_captures.py` (procédure complète : `ateliers/a03/README.md` § E08).
- **Résultat** : 4 captures (600 Ko) dans `~/b6g-data/a03/pcap/` (hors dépôt) ; séquence complète d'un UE en 50,5 ms.
- **Problèmes et solutions** :
  - Premier essai perdu : conteneurs de capture lancés avec `--rm`, supprimés avec leur fichier à l'arrêt de tcpdump.
    Correction : conteneurs persistants, `docker stop`, `docker cp`, puis `docker rm`.
  - Messages NAS vides après « Security mode » : intégrité active, chiffrement nul (NEA0). Correction : option
    tshark `nas-5gs.null_decipher:TRUE`.
  - SBI non décodé : port 7777 non standard. Correction : `-d tcp.port==7777,http2`.
  - Plusieurs UEs regroupés dans une même trame SCTP : décodage PDU par PDU (sortie PDML) pour attribuer chaque
    message NGAP à son RAN-UE-NGAP-ID.
- **Retour arrière** : sans objet (lecture seule) ; `rm -r ~/b6g-data/a03/pcap` pour libérer l'espace.
