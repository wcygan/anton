# Integration Metric Glossaries

Per-integration index of useful metric names for the workloads anton scrapes. Use this to answer "what metric do I query for X?" without reading every exporter's source. For the CRD and scrape-wiring shape, see [prometheus-operator-crds](prometheus-operator-crds.md).

## Canonical URLs

- **Longhorn metrics**: https://longhorn.io/docs/latest/monitoring/metrics/
- **Cilium metrics**: https://docs.cilium.io/en/stable/observability/metrics/
- **kube-state-metrics docs**: https://github.com/kubernetes/kube-state-metrics/tree/main/docs
  - per-resource metric list: https://github.com/kubernetes/kube-state-metrics/blob/main/docs/metrics/
- **node-exporter collectors**: https://github.com/prometheus/node_exporter#collectors
  - metric reference (generated): https://github.com/prometheus/node_exporter/blob/master/docs/node-mixin/
- **cert-manager metrics**: https://cert-manager.io/docs/devops-tips/prometheus-metrics/
- **External Secrets Operator metrics**: https://external-secrets.io/latest/api/metrics/
- **Cloudflare tunnel metrics**: https://developers.cloudflare.com/cloudflare-one/tutorials/cloudflared-prometheus/
- **Envoy Gateway / Envoy proxy stats**: https://www.envoyproxy.io/docs/envoy/latest/operations/stats_overview

## Longhorn (job `longhorn-backend`)

On by default in our HelmRelease (`metrics.serviceMonitor.enabled: true`).

| Metric | What it means |
| --- | --- |
| `longhorn_volume_robustness` | Per-volume health: `1` healthy, `2` degraded, `3` faulted, `0` unknown. Core dashboard metric. |
| `longhorn_volume_state` | State enum: `1` attached, `2` detached, `3` attaching, etc. |
| `longhorn_volume_actual_size_bytes` | Sparse on-disk size (not nominal capacity). |
| `longhorn_volume_capacity_bytes` | Nominal PVC size. |
| `longhorn_volume_read_throughput` / `_write_throughput` | Per-volume bytes/sec. |
| `longhorn_volume_read_iops` / `_write_iops` | Per-volume IOPS. |
| `longhorn_volume_read_latency` / `_write_latency` | Per-op latency. |
| `longhorn_node_status` | Per-node `allowScheduling`, `ready`, `schedulable`. |
| `longhorn_node_storage_{usage,capacity,reservation}_bytes` | Node-level disk accounting. |
| `longhorn_disk_status` | Per-disk `allowScheduling`, `ready`, `schedulable` — maps to our `node.longhorn.io/default-disks-config` annotations. |
| `longhorn_disk_storage_{usage,capacity,reservation}_bytes` | Per-disk breakdown. |
| `longhorn_instance_manager_cpu_usage_millicpu` | Instance manager (engine/replica host) CPU. |

Common queries:

```promql
# Count volumes that are NOT healthy
count(longhorn_volume_robustness != 1) or vector(0)

# Per-disk used %
(longhorn_disk_storage_usage_bytes / longhorn_disk_storage_capacity_bytes) * 100

# Rebuild detection (no direct metric — infer from robustness transitions)
changes(longhorn_volume_robustness[10m]) > 0
```

## Cilium (jobs `cilium-agent`, `cilium-operator`)

Enabled via HelmRelease edits to `operator.prometheus.*` and `prometheus.*` sub-blocks (plan 0002 commit `6cba09e1`).

| Metric | What it means |
| --- | --- |
| `cilium_endpoint_state` | Per-endpoint state enum. |
| `cilium_unreachable_nodes` | Number of nodes the agent can't reach. **Alert-worthy.** |
| `cilium_unreachable_health_endpoints` | Per-agent view of unhealthy peers. |
| `cilium_drop_count_total` | Packet drops by reason. High cardinality — aggregate. |
| `cilium_forward_count_total` | Forwarded packets counter. |
| `cilium_policy_verdict_total` | Allowed / denied / error counter per direction + match_type. |
| `cilium_bpf_map_pressure` | BPF map fill ratio. **Approaching 1.0 = pain.** |
| `cilium_kubernetes_events_received_total` | Is Cilium keeping up with k8s? |
| `cilium_operator_*` | Operator-side (IPAM, endpoint GC, etc.). |

Envoy proxy metrics (if you ever enable `envoy.prometheus.serviceMonitor: true` — currently **off** in anton): job `cilium-envoy`, extremely high cardinality. Leave off unless you explicitly need L7 observability.

## kube-state-metrics (job `kube-state-metrics`)

Exposes Kubernetes resource state as metrics. Used everywhere — dashboards, alerts, and the "top pod restarts" panel.

| Metric | What it means |
| --- | --- |
| `kube_pod_container_status_restarts_total` | Container restart counter — the canonical "did this crashloop" metric. |
| `kube_pod_status_phase` | `{phase="Running\|Pending\|Failed\|Succeeded\|Unknown"}`. |
| `kube_pod_container_resource_{requests,limits}` | Requests / limits per container, per resource. |
| `kube_deployment_status_replicas_{available,ready,updated}` | Replica rollout state. |
| `kube_namespace_created` | One series per namespace — useful for template vars. |
| `kube_node_status_condition` | `{condition="Ready\|MemoryPressure\|DiskPressure\|PIDPressure"}`. |
| `kube_persistentvolumeclaim_info` | PVC metadata — join with `kubelet_volume_stats_*` for saturation. |
| `kube_job_status_{succeeded,failed,active}` | Job outcome tracking — used for Renovate CI, Longhorn backup jobs. |

## node-exporter (job `node-exporter`)

Standard host metrics on every Talos node.

| Metric | What it means |
| --- | --- |
| `node_cpu_seconds_total{mode=...}` | Per-mode CPU time. `100 - avg(rate(...{mode="idle"}[5m])) * 100` = % busy. |
| `node_memory_MemAvailable_bytes` / `node_memory_MemTotal_bytes` | Memory availability; prefer this over `MemFree`. |
| `node_filesystem_{avail,size}_bytes` | Per-mount disk accounting. Filter out `tmpfs\|overlay\|squashfs` and `/var/lib/kubelet/.*`. |
| `node_network_{receive,transmit}_bytes_total` | Per-interface bytes. |
| `node_network_up` | Per-interface link state. Useful for "is enp2s0f0np0 up?". |
| `node_disk_io_time_seconds_total` | Disk saturation (busy time / total time). |
| `node_load1` / `node_load5` / `node_load15` | Loadavg. Coarse; prefer CPU %. |
| `node_boot_time_seconds` | Uptime reference. |
| `node_systemd_unit_state` | Systemd unit state per unit. Talos has very few units here. |

## cert-manager (job `cert-manager`)

| Metric | What it means |
| --- | --- |
| `certmanager_certificate_expiration_timestamp_seconds` | Per-certificate expiry epoch. The standard "cert expiring in 14d" alert works off this. |
| `certmanager_certificate_ready_status` | Per-certificate Ready condition. |
| `certmanager_controller_sync_call_count` | Controller work counter. |
| `certmanager_acme_client_request_*` | ACME client call counters. Useful for detecting Let's Encrypt rate-limit issues. |

## External Secrets Operator (jobs `external-secrets-*`)

| Metric | What it means |
| --- | --- |
| `externalsecret_sync_calls_total{status=...}` | Per-ExternalSecret sync outcome. Failing syncs surface here. |
| `externalsecret_status_condition` | Ready / Deleted / SecretSynced per ES. |
| `clustersecretstore_status_condition` | Store health (our `onepassword-connect` store). |

## Cloudflare tunnel (job `cloudflare-tunnel`)

Enabled via the cloudflared chart's built-in metrics server.

| Metric | What it means |
| --- | --- |
| `cloudflared_tunnel_active_streams` | In-flight requests through the tunnel. |
| `cloudflared_tunnel_total_requests` | Counter of all requests served. |
| `cloudflared_tunnel_concurrent_requests_per_tunnel` | Per-tunnel concurrency. |
| `quic_connections_active` | Number of QUIC edge connections. |

## Envoy Gateway / Envoy (NOT currently scraped)

Our `envoy-internal` and `envoy-external` Envoy proxies do not have ServiceMonitors enabled. Envoy's `/stats` endpoint is high-cardinality; adding it without care can double Prometheus's series count. If we ever enable it, start with selective `metric_relabel_configs` to drop per-listener noise.

## Kubelet / cAdvisor (job `kubelet`)

Exposed via the kubelet's own `/metrics/cadvisor` endpoint, scraped automatically by the `kubelet` ServiceMonitor the chart installs.

| Metric | What it means |
| --- | --- |
| `container_cpu_usage_seconds_total` | Per-container CPU. Use `rate(...[5m])`. |
| `container_memory_working_set_bytes` | The metric kubelet uses for OOM decisions. Prefer this over `container_memory_usage_bytes`. |
| `container_fs_usage_bytes` | Container-writable layer usage. |
| `kubelet_volume_stats_{used,capacity}_bytes` | PVC saturation — the canonical "PVC is getting full" metric. |
| `kubelet_running_pods` / `kubelet_running_containers` | Per-node pod/container counts. |

## Putting it together

Typical dashboard / alert recipe layering:

1. Resource exists? → `kube_*_info` (kube-state-metrics).
2. Resource is healthy? → `flux_resource_info`, `certmanager_certificate_ready_status`, `longhorn_volume_robustness`.
3. Resource is saturated? → `node_*`, `kubelet_volume_stats_*`, `container_*`.
4. Resource is being abused? → `cilium_drop_count_total`, `cloudflared_tunnel_*`, `kube_pod_container_status_restarts_total`.

The cluster-health-glance dashboard (`kubernetes/apps/observability/kube-prometheus-stack/app/dashboard-cluster-health.yaml`) is the worked example.
