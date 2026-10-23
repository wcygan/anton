---
name: observe-with-grafana
description: >-
  Observe Anton's health through the read-only `grafana` MCP server: firing
  alerts, nodes, Flux, workloads, storage, and logs, with Grafana deeplinks as
  evidence. Use for "how is the cluster doing", a quick health glance, checking
  a change's effect through metrics or logs, or when an agent should look
  before running kubectl. Also verifies that the Grafana MCP itself works.
---

# Observe Anton with Grafana

The outcome is a short, ranked health report built from Grafana: each layer
below marked green or red, the query that proves it, and a Grafana deeplink for
anything red. Stop at the layers the user's question needs; a broad "how is it
doing" walks all of them.

## Before you start

1. Confirm the `grafana` MCP tools are available (`mcp__grafana__*`). Call
   `list_datasources`. It returns Prometheus (uid `prometheus`), Loki, and
   Alertmanager.
2. If the tools are missing or the call fails, the server did not start. Run
   `uv run --script ${ANTON_PRIVATE_DIR:-../anton-private}/mcp/grafana.py check`
   from this repository. It names the first failing layer (Tailscale,
   1Password, Grafana, token, or MCP). The private `verify-grafana-mcp` skill
   has the fixes. Fall back to `anton-cluster-health` with kubectl if Grafana
   stays unavailable, and say so in the report.

The server is read-only: a Viewer token plus `--disable-write`. Never print the
Grafana URL from a deeplink into committed files; it contains the tailnet name.
Use `<tailnet-name>.ts.net` in anything you write down.

## Walk the layers

Use `query_prometheus` with `queryType: instant` unless a trend matters. An
empty result means green for the "show me what is wrong" queries.

| # | Layer | Query | Green when |
| --- | --- | --- | --- |
| 1 | Firing alerts | `ALERTS{alertstate="firing", alertname!~"Watchdog\|InfoInhibitor"}` | Empty. Otherwise each alert names the next layer to read. |
| 2 | Nodes | `kube_node_status_condition{condition="Ready", status="true"} == 0` and `time() - node_boot_time_seconds` | No unready node; uptime matches known maintenance. |
| 3 | Flux | `flux_resource_info{ready!="True"}` | Empty. |
| 4 | Workloads | `sum by (namespace, phase) (kube_pod_status_phase{phase!~"Running\|Succeeded"}) > 0` and `topk(10, increase(kube_pod_container_status_restarts_total[1h]) > 0)` | Both empty. |
| 5 | Longhorn | `longhorn_volume_robustness{state!="healthy"} == 1` | Empty. |
| 6 | SeaweedFS | `SeaweedFS_volumeServer_read_only_volumes{type="IsReadOnly"} > 0` | Empty. |
| 7 | Capacity | `max by (instance, mountpoint) (1 - node_filesystem_avail_bytes{fstype!~"tmpfs\|overlay\|squashfs"} / node_filesystem_size_bytes) > 0.8` | Empty. |
| 8 | Certificates | `certmanager_certificate_ready_status{condition="True"} == 0` | Empty. |
| 9 | Log pipeline | `sum(rate(loki_distributor_bytes_received_total[5m]))` | Above zero. |

For context beyond these rows, `get_dashboard_summary` on uid
`cluster-health-glance` lists the curated panels (Nodes Ready, Flux Ready %,
Unhealthy Workloads, Restart Hotspots, and more). `run_panel_query` runs a
panel's own query, which keeps your numbers identical to what the user sees.

## Follow a red layer into logs

Use `query_loki_logs` with a narrow selector and a time range of one hour or
less, for example `{namespace="storage", pod="seaweedfs-volume-0"} |~ "(?i)error|warn"`.
The server enforces a Loki guardrail: it rejects broad selectors and ranges
over 24 hours, and returns at most 100 lines. `query_loki_patterns` groups
repeated lines when a pod is noisy. For deeper LogQL work, use the
`query-kubernetes-logs` skill.

## Report

Lead with the overall verdict. Then list red layers first, each with the query,
the offending series (namespace, pod, node, or volume), when it started if
`ALERTS_FOR_STATE` or a range query shows it, and a `generate_deeplink` link.
End with the green layers on one line. Recommend fixes, but do not act on them:
mutations follow the repository's normal approval rules and other skills.
