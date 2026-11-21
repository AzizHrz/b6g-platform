# Virtualisation (M05) : vérification des outils (T01.4). Les cibles de la VM UPF arrivent avec l'atelier 7.
.PHONY: vm-check

vm-check:
	bash platform/vm/install_vm_tools.sh
