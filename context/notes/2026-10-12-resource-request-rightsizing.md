# Resource request right-sizing

Approved scope: staged request changes only. Preserve all replica counts,
resource limits, and Longhorn CPU reservations. Assessment used seven days of
Prometheus container CPU and working-set memory data, including unsampled
memory maxima and one-minute evaluations of five-minute CPU rates for candidates.
Requests reserve scheduling capacity; reducing them does not reduce measured
consumption or power draw by itself.

## Desired requests per container

| Component | CPU before → after | Memory before → after | Replicas |
|---|---|---|---|
| Envoy proxies | 100m → 50m | implicit 1Gi → 256Mi | 4 across two gateways |
| Cloudflare tunnel | 10m unchanged | implicit 256Mi → 128Mi | 2 |
| Prometheus | none → 250m | none → 5Gi | 1 |
| Loki | 250m → 100m | 512Mi → 384Mi | 1 |
| Harbor PostgreSQL | 250m → 100m | 512Mi unchanged | 3 |
| Harbor Dragonfly | 100m → 50m | 256Mi → 128Mi | 3 |
| Multus | 100m → 50m | 512Mi → 192Mi | 3 |
| Whereabouts | 100m → 50m | 128Mi → 64Mi | 3 |
| Cilium agent | 100m → 200m | 512Mi → 1Gi | 3 |
| Kubernetes API server | 200m → 500m | 512Mi → 4Gi | 3 |

Prometheus reached approximately 4.7Gi working set, Cilium 860Mi per agent,
and API servers 4.1Gi per instance during the assessment window. Limits remain
unchanged, so requests are not new caps. PostgreSQL retains its 256MB shared
buffers and 1Gi limit. Longhorn instance managers retain 2280m CPU per node.

The reductions total 1.25 CPU cores and 4.875Gi of memory requests. Correcting
the three under-requested components adds 1.45 CPU cores and 17Gi memory:
the expected net change is **+0.20 CPU cores and +12.125Gi memory reserved**.
This more accurately accounts for existing consumption while removing excess
reservations from the small components.

## Rollout and recovery

Each stage is committed and published separately, then reconciled through Flux.
Talos API-server resources are generated from source and applied through a
narrow `cluster.apiServer.resources.requests` patch with `--mode=no-reboot`,
one node at a time, after a dry run. An etcd snapshot is retained privately
outside the repository before that stage.

Acceptance: desired requests on running containers; unchanged limits and
replicas; all three nodes Ready; all 16 Longhorn volumes healthy; all Flux
Kustomizations and HelmReleases Ready; Prometheus targets recovered; Harbor
health components healthy; Loki ready; public application HTTP checks succeed.
Stop and investigate if a stage exceeds ten minutes or health fails to recover.
Rollback is a stage-specific Git revert; for Talos restore the previous requests
on the affected node and revert the source change.

CNPG uses its existing `primaryUpdateMethod: restart` and a 180-second smart
shutdown timeout. This preserves its configured policy but can interrupt database
availability during the primary's replacement. Prometheus and Loki each have a
single replica, so their rolling replacements also involve brief availability gaps.

## Verification

- YAML/source validation and all 354 repository contract tests passed.
- Talos generated successfully; API-server dry run showed only the four new
  request configuration lines, with no reboot required.
- Completed commits in order: ingress `88eaee96`, observability `ae6bd14d`,
  PostgreSQL `20d7a648`, Dragonfly `eec909ae`, Multus `acd4a2cf`,
  Whereabouts `5a7ba1de`, Cilium `b62de67c`, API servers `e2a4dc09`.
- Verified all 26 affected running containers across the ten component groups
  have their exact intended requests, unchanged limits, and Ready status.
  Checked controller replica counts and main/init-container limits against
  the pre-rollout snapshot; unchanged. No temporary cluster resources created.
- API-server patches applied serially on k8s-1, k8s-2, k8s-3, with successful
  Talos/etcd, Kubernetes, storage, and service checks between nodes. Talos
  rendered the new static-pod spec before the kubelet refreshed the mirror pod;
  waited for the running pod resources to match before advancing.
- Actual steady-state regular-container requests: CPU **13.191 → 13.391 cores**;
  memory **20.484375 → 32.609375Gi**. These totals exclude completed jobs and
  terminating pods and are not measurements of CPU/RAM consumption.
- Final health: **3/3 nodes Ready**, **16/16 Longhorn volumes healthy**,
  **54/54 Flux Kustomizations Ready**, **27/27 HelmReleases Ready**,
  **72/72 Prometheus targets UP**. Longhorn instance-manager CPU remains
  **2280m on each node**.
- Harbor reports core, database, jobservice, portal, redis, registry and
  registryctl healthy. Loki readiness passes and receives approximately
  30 log lines/sec. Prometheus ingests approximately 9,082 samples/sec with
  285,028 active head series. Public bakery and food application checks return
  HTTP 200. Cilium reports all agents healthy and manages all 137 cluster pods
  in its status snapshot. These rates/counts are point-in-time evidence.
- Post-rollout observation covers readiness and repeated scrape recovery,
  not a full week of future peak traffic. Existing limits remain available
  for bursts; monitor usage through the next scheduled maintenance cycle.
