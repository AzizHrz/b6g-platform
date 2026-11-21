#!/usr/bin/env bash
# Docker Engine, Compose v2 et registre local (T01.5).
# Vérifie l'installation ; si Docker manque, affiche les commandes officielles (dépôt download.docker.com) à lancer
# avec sudo. Le registre local (registry:2, port 5000) se démarre ensuite avec « make up-registry ».
set -euo pipefail

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "[OK] Docker Engine $(docker info --format '{{.ServerVersion}}')"
  echo "[OK] $(docker compose version)"
  id -nG | tr ' ' '\n' | grep -qx docker && echo "[OK] utilisateur dans le groupe docker"
  exit 0
fi

distro=$(. /etc/os-release && echo "$ID")          # debian | ubuntu
codename=$(. /etc/os-release && echo "$VERSION_CODENAME")
cat <<EOF
[MANQUE] Docker Engine. Commandes à lancer dans un terminal administrateur :

sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/${distro}/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${distro} ${codename} stable" | sudo tee /etc/apt/sources.list.d/docker.list
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker "\$USER"     # puis déconnexion / reconnexion

Vérification : docker run --rm hello-world ; docker compose version ; make up-registry registry-check
EOF
exit 1
