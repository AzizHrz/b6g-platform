# Virtualisation (M05) : vérification des outils (T01.4). Les cibles de la VM UPF arrivent avec l'atelier 7.
.PHONY: vm-check

vm-check:
	bash platform/vm/install_vm_tools.sh

# UPF miot en VM (T07.2) : le conteneur upf-miot est arrêté (même adresse N4 / N3), puis la VM est créée par libvirt
VIRSH := virsh -c qemu:///system
VCPUS ?= 1
.PHONY: up-vm down-vm vm-status migration-lab
up-vm: core-render
	-docker stop upf-miot
	$(BIN)/python platform/vm/upf-vm/build.py --vcpus $(VCPUS)

# Retour à l'UPF conteneurisée : VM arrêtée et supprimée (disques du pool conservés), conteneur relancé, UEs réattachés
down-vm:
	-$(VIRSH) destroy upf-miot-vm
	-$(VIRSH) undefine upf-miot-vm
	docker start upf-miot
	@sleep 10; docker restart ue-miot >/dev/null; echo "UPF miot conteneurisée rétablie"

vm-status:
	$(VIRSH) list --all
	$(VIRSH) domstats upf-miot-vm --cpu-total --balloon --vcpu 2>/dev/null | grep -E 'cpu.time|balloon.rss|vcpu.current' || true

# Migration à chaud entre deux hyperviseurs QEMU locaux (T07.4)
migration-lab:
	docker build -q -t b6g/qemu-lab:0.1.0 platform/vm/qemu-lab
	bash ateliers/a07/run_migration.sh
