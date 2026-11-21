# Registre d'images local (T01.5) sur le port 5000.
.PHONY: up-registry down-registry registry-check

up-registry:
	docker compose -f platform/registry/compose.yaml up -d

down-registry:
	-docker compose -f platform/registry/compose.yaml down

# Vérification : push puis pull d'une petite image par le registre local
registry-check:
	docker pull -q busybox:1.37
	docker tag busybox:1.37 127.0.0.1:5000/b6g/busybox:1.37
	docker push -q 127.0.0.1:5000/b6g/busybox:1.37
	docker image rm 127.0.0.1:5000/b6g/busybox:1.37
	docker pull -q 127.0.0.1:5000/b6g/busybox:1.37
	curl -s http://127.0.0.1:5000/v2/_catalog
