"""Collecte Prometheus du cluster k3d (T08.3) : configuration générée depuis config/scenario.yaml.

    .venv/bin/python platform/k8s/render_obs.py        (appelé par make k8s-obs)

Produit (non versionné) :
    platform/observability/generated/scrape.d/k8s.yml      collecte par l'API Kubernetes (jeton de lecture seule) :
        - k8s-cadvisor      CPU et mémoire des pods (kubelet /metrics/cadvisor de chaque nœud)
        - kube-state-metrics répliques des déploiements
        - k8s-pods          métriques applicatives des pods annotés prometheus.io/scrape (b6g_app_request_latency_ms)
    platform/observability/generated/rules/k8s.rules.yml   b6g_k8s_replicas{deployment, tier} et CPU de chaque niveau
Le jeton est écrit dans platform/observability/generated/k8s-token (non versionné).
"""
from __future__ import annotations

from pathlib import Path

import yaml
from b6g_common import scenario as scn

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "platform" / "observability" / "generated"
API = "k3d-b6g-server-0:6443"          # joint par Prometheus via le réseau Docker k3d-b6g
TOKEN = "/etc/prometheus/generated/k8s-token"


def api_job(name: str, sd_role: str, path_tpl: str, keep: str | None = None, extra_relabel: list | None = None) -> dict:
    job = {
        "job_name": name, "scheme": "https", "scrape_interval": "15s",
        "tls_config": {"insecure_skip_verify": True}, "authorization": {"credentials_file": TOKEN},
        "kubernetes_sd_configs": [{"role": sd_role, "api_server": f"https://{API}",
                                   "tls_config": {"insecure_skip_verify": True},
                                   "authorization": {"credentials_file": TOKEN}}],
        "relabel_configs": (extra_relabel or []) + [
            {"target_label": "__address__", "replacement": API},
            {"source_labels": path_tpl[0], "regex": path_tpl[1], "target_label": "__metrics_path__",
             "replacement": path_tpl[2]},
        ],
    }
    if keep:
        job["metric_relabel_configs"] = [{"source_labels": ["__name__"], "regex": keep, "action": "keep"}]
    return job


def scrape(sc: dict) -> dict:
    jobs = [
        api_job("k8s-cadvisor", "node",
                (["__meta_kubernetes_node_name"], "(.+)", "/api/v1/nodes/$1/proxy/metrics/cadvisor"),
                keep="container_cpu_usage_seconds_total|container_memory_working_set_bytes",
                extra_relabel=[{"source_labels": ["__meta_kubernetes_node_label_b6g_tier"], "target_label": "tier"}]),
        api_job("kube-state-metrics", "service",
                (["__meta_kubernetes_namespace", "__meta_kubernetes_service_name"], "(.+);(.+)",
                 "/api/v1/namespaces/$1/services/$2:http/proxy/metrics"),
                keep="kube_deployment_.*|kube_pod_info|kube_horizontalpodautoscaler_.*",
                extra_relabel=[{"source_labels": ["__meta_kubernetes_service_name"], "regex": "kube-state-metrics",
                                "action": "keep"}]),
        api_job("k8s-pods", "pod",
                (["__meta_kubernetes_namespace", "__meta_kubernetes_pod_name",
                  "__meta_kubernetes_pod_annotation_prometheus_io_port"], "(.+);(.+);(.+)",
                 "/api/v1/namespaces/$1/pods/$2:$3/proxy/metrics"),
                extra_relabel=[{"source_labels": ["__meta_kubernetes_pod_annotation_prometheus_io_scrape"],
                                "regex": "true", "action": "keep"},
                               {"source_labels": ["__meta_kubernetes_pod_name"], "target_label": "pod"}]),
    ]
    return {"scrape_configs": jobs}


def rules(sc: dict) -> dict:
    tiers = "|".join(sc["tiers"])
    r = [
        # Répliques disponibles par déploiement et par niveau (espace de noms b6g-<niveau>)
        {"record": "b6g_k8s_replicas",
         "expr": f'label_replace(sum by (namespace, deployment) (kube_deployment_status_replicas_available'
                 f'{{namespace=~"b6g-({tiers})"}}), "tier", "$1", "namespace", "b6g-(.+)")'},
    ]
    # CPU de chaque niveau : cœurs utilisés par le nœud k3d / capacité du niveau (scénario § tiers)
    for t in sc["tiers"].values():
        sel = f'job="cadvisor", name="{t["k8s_node"]}"'
        r.append({"record": "b6g_nf_cpu_ratio",
                  "expr": f'label_replace(sum(rate(container_cpu_usage_seconds_total{{{sel}}}[30s])) '
                          f'/ {t["cpu_millicores"] / 1000}, "nf", "{t["k8s_node"]}", "", "")'})
    return {"groups": [{"name": "b6g-k8s", "interval": "15s", "rules": r}]}


def main() -> None:
    sc = scn.load()
    for sub, data in (("scrape.d/k8s.yml", scrape(sc)), ("rules/k8s.rules.yml", rules(sc))):
        p = OUT / sub
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    print(f"Collecte k8s générée : {OUT.relative_to(ROOT)}/scrape.d, rules")


if __name__ == "__main__":
    main()
