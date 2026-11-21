# Kubernetes léger k3d (M06, atelier 8). Outils installés hors du dépôt dans ~/b6g-ext/bin (k3d, kubectl, helm).
K8S_BIN := $(HOME)/b6g-ext/bin
export PATH := $(K8S_BIN):$(PATH)

.PHONY: up-k8s down-k8s k8s-status

up-k8s:
	k3d cluster create --config platform/k8s/cluster.yaml
	kubectl get nodes -L b6g/tier

down-k8s:
	-k3d cluster delete b6g

k8s-status:
	kubectl get nodes -L b6g/tier
	kubectl get pods -A -o wide

# Observabilité du cluster (T08.3) : kube-state-metrics (Helm), compte de lecture seule, collecte par l'API k8s
KSM_CHART_VERSION ?= 5.25.1
.PHONY: k8s-obs k8s-obs-off
k8s-obs:
	helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
	helm repo update prometheus-community >/dev/null
	helm upgrade --install kube-state-metrics prometheus-community/kube-state-metrics \
		--version $(KSM_CHART_VERSION) -n kube-system --wait
	kubectl apply -f platform/k8s/prometheus-reader.yaml
	@mkdir -p platform/observability/generated
	kubectl -n kube-system create token prometheus-b6g --duration=8760h > platform/observability/generated/k8s-token
	@chmod 644 platform/observability/generated/k8s-token
	-docker network connect k3d-b6g prometheus
	$(BIN)/python platform/k8s/render_obs.py
	curl -s -X POST http://127.0.0.1:9090/-/reload && echo "Prometheus rechargé (collecte k8s active)"

# Retire la collecte k8s (avant make down-k8s) : les cibles k8s disparaissent de Prometheus
k8s-obs-off:
	-rm -f platform/observability/generated/scrape.d/k8s.yml platform/observability/generated/rules/k8s.rules.yml
	-docker network disconnect k3d-b6g prometheus
	curl -s -X POST http://127.0.0.1:9090/-/reload && echo "Prometheus rechargé (collecte k8s retirée)"

# Cœur Open5GS et gNB / UE UERANSIM dans k3d (T08.2) : charts Gradiant, versions figées, valeurs du scénario
OPEN5GS_CHART_VERSION ?= 2.2.5
GNB_CHART_VERSION ?= 0.2.6
.PHONY: k8s-core k8s-core-down k8s-core-status
k8s-core:
	$(BIN)/python platform/k8s/values/render.py
	helm upgrade --install open5gs oci://registry-1.docker.io/gradiant/open5gs --version $(OPEN5GS_CHART_VERSION) \
		-n b6g-5gc --create-namespace -f platform/k8s/generated/open5gs.yaml --wait --timeout 10m
	helm upgrade --install ueransim-gnb oci://registry-1.docker.io/gradiant/ueransim-gnb --version $(GNB_CHART_VERSION) \
		-n b6g-5gc -f platform/k8s/generated/gnb.yaml --wait --timeout 5m
	$(MAKE) --no-print-directory k8s-core-status

k8s-core-status:
	kubectl -n b6g-5gc get pods -o wide

k8s-core-down:
	-helm -n b6g-5gc uninstall ueransim-gnb open5gs
