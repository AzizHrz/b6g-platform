#!/usr/bin/env bash
# Outils de virtualisation de l'atelier 7 (T01.4) : vérification de QEMU/KVM et libvirt.
# Le script n'installe rien : il affiche la commande sudo à lancer si un élément manque.
# Usage : bash platform/vm/install_vm_tools.sh   (ou make vm-check)
set -euo pipefail

missing_pkgs=()
ok()   { printf '[OK]   %s\n' "$*"; }
miss() { printf '[MANQUE] %s\n' "$*"; }

# 1. Virtualisation matérielle
if LC_ALL=C lscpu | grep -qE 'Virtualization:\s+(VT-x|AMD-V)'; then
  ok "virtualisation matérielle : $(LC_ALL=C lscpu | awk -F: '/Virtualization:/{gsub(/ /,"",$2); print $2}')"
else
  miss "virtualisation matérielle (activer VT-x / AMD-V dans le BIOS)"
fi
if [ -c /dev/kvm ]; then ok "/dev/kvm présent"; else miss "/dev/kvm (module kvm_intel ou kvm_amd)"; fi

# 2. Paquets (Debian 13 / Ubuntu)
for pkg in qemu-system-x86 qemu-utils libvirt-daemon-system libvirt-clients virtinst xorriso; do
  if dpkg -s "$pkg" >/dev/null 2>&1; then
    ok "paquet $pkg $(dpkg-query -W -f='${Version}' "$pkg")"
  else
    miss "paquet $pkg"; missing_pkgs+=("$pkg")
  fi
done

# 3. Droits de l'utilisateur
for grp in libvirt kvm; do
  if id -nG | tr ' ' '\n' | grep -qx "$grp"; then ok "membre du groupe $grp"; else miss "groupe $grp"; fi
done
if virsh -c qemu:///system list --all >/dev/null 2>&1; then
  ok "virsh fonctionne sans sudo (qemu:///system)"
else
  miss "accès à qemu:///system sans sudo"
fi

# 4. Réseau libvirt « default » (NAT 192.168.122.0/24), utilisé par les VM de l'atelier 7
state=$(virsh -c qemu:///system net-info default 2>/dev/null | awk '/^Active:/{print $2}')
if [ "${state:-}" = "yes" ]; then ok "réseau libvirt default actif"; else
  printf '[INFO] réseau libvirt default inactif : virsh -c qemu:///system net-start default\n'
fi

if [ ${#missing_pkgs[@]} -gt 0 ]; then
  printf '\nÀ installer (dans un terminal administrateur) :\n  sudo apt install -y %s\n' "${missing_pkgs[*]}"
  printf 'puis : sudo usermod -aG libvirt,kvm "$USER" et reconnexion.\n'
  exit 1
fi
echo "Outils de virtualisation prêts. Le démarrage d'une VM de test est réalisé à l'atelier 7 (T07.2)."
