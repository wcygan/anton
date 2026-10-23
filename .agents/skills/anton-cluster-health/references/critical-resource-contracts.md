# Critical Resource Contracts

This runbook records resource requests that protect scheduling and recovery for
critical workloads. Requests are reservations, not utilization targets or a
claim that cluster capacity has been reclaimed. Record the measurement window,
unknowns, proposed reservations, and rollback path with each change.

## Harbor registry

### Baseline

The Harbor HelmRelease pins goharbor chart `1.19.2`. Its registry Deployment has
two replicas, each with `registry` and `registryctl` containers. The live
Deployment currently reports `resources: {}` for both containers, so all four
containers are BestEffort despite resource values being present in the
HelmRelease. The chart reads registry settings from
`registry.registry.resources` and controller settings from
`registry.controller.resources`; a sibling `registry.resources` value is
ignored.

Prometheus `container_memory_working_set_bytes` and five-minute CPU rates were
queried through the Kubernetes service proxy over the previous seven days,
using `quantile_over_time(0.95, ...[7d:5m])`. The observed per-pod p95 ranges
were:

| Container | CPU p95 | Memory p95 |
| --- | ---: | ---: |
| `registry` | 1.17–1.28m | 47.4–48.3MiB |
| `registryctl` | 0.69–0.72m | 34.0–35.4MiB |

This is a bounded observation of the available seven-day samples; it does not
cover a full workload cycle or establish peak demand. Older data, longer-term
growth, and behavior during large image transfers remain unknown.

### Proposed reservations and benefit

The registry retains its existing intended reservation of `100m` CPU and
`256Mi` memory per replica, plus its existing `512Mi` memory limit, at the chart
key that renders onto the registry container. `registryctl` receives `10m` CPU
and `64Mi` memory requests per replica. Those values round above the observed
seven-day p95 while remaining modest reservations; no CPU or memory limit is
proposed for `registryctl` without evidence for a safe cap.

The intended benefit is accurate scheduler and node-pressure accounting for
four running containers. This change preserves spare capacity and does not
claim node capacity savings or a utilization improvement. Revisit the proposed
requests after a representative busy period or if OOMs, evictions, pending
pods, or sustained throttling appear.

### Render and rollout verification

Before review, render the pinned chart and assert resources on the generated
containers:

```sh
mise exec -- python3 scripts/check-harbor-resource-contract.py
```

After the GitOps change is merged and Flux has reconciled, verify the release
and actual Deployment values:

```sh
mise exec -- flux get hr harbor -n registries
mise exec -- kubectl -n registries get deployment harbor-registry \
  -o jsonpath='{range .spec.template.spec.containers[*]}{.name}{" requests="}{.resources.requests}{" limits="}{.resources.limits}{"\n"}{end}'
mise exec -- kubectl -n registries get deployment harbor-registry
mise exec -- kubectl -n registries get pods -l app=harbor,component=registry
```

Confirm the registry and registryctl requests on the Deployment template,
available replicas remain `2/2`, both pods become Ready, and restart counts
remain stable through the normal observation window. Check Harbor through its
existing health procedure and ensure Flux reports the intended Git revision.
No live reconciliation is implied by passing the render check.

### Rollback

If the reconciled Deployment does not become Ready, registry service degrades,
or resource pressure appears after the change, revert the reviewed Git commit
and let Flux reconcile the revert:

```sh
git revert --no-edit <resource-contract-commit>
```

Then verify the HelmRelease revision and Deployment values again. The prior
chart render left both containers with empty resources, so rollback restores
that state while a revised reservation is prepared.

## SeaweedFS components

### Baseline

The `Seaweed` CR set no requests on the master, volume, filer or S3
containers, so volume and filer pods were BestEffort and master and S3 pods
were Burstable only through their sidecars. Under memory pressure the kubelet
evicts pods that use more memory than they request before any others, whatever
their priority, so the volume servers were among the first candidates even
after moving to the `storage-service` tier.

Pod working sets (`container_memory_working_set_bytes` summed per pod, read
through the Kubernetes service proxy on 2026-10-23, with 25 days retained):

| Component | p95, 7 days | Peak, 25 days |
| --- | ---: | ---: |
| master | 127 MiB | 154 MiB |
| volume | 62 MiB | 712 MiB |
| filer | 226 MiB | 1,705 MiB |
| S3 (with read probe) | 288 MiB | 336 MiB |

The volume peak fell on the 2026-10-20 stock cutover. The filer passed 512 MiB
on four days (2026-09-28, 10-02, 10-13 and 10-14) and reached 1.9 GiB on
2026-09-28, just before the 25-day window. Their causes were not investigated.

### Reservations and benefit

Memory requests only: master `192Mi`, volume `768Mi`, filer `512Mi`, S3
`384Mi`. They cover the observed master, volume and S3 peaks; the filer's
covers its routine load but not those four days. Together they reserve about
1.5 GiB per node out of roughly 88 GiB allocatable. No limits:
a limit would turn a spike into an OOM kill mid-write. CPU is unchanged. A pod
that spikes above its request rejoins the first eviction group, where its
priority still ranks it after ordinary workloads and storage consumers.

### Rollout verification and rollback

The change rolls every SeaweedFS StatefulSet and the S3 Deployment, so it
needs the writer fence in the `seaweedfs-ops` node-maintenance procedure.
Afterwards confirm the requests and QoS on the running pods:

```sh
mise exec -- kubectl -n storage get pods -l app.kubernetes.io/instance=seaweedfs \
  -o custom-columns='NAME:.metadata.name,PRIORITY:.spec.priority,QOS:.status.qosClass'
```

Every component pod should report priority `500000000` and QoS `Burstable`.
Rollback is a Git revert, which rolls the pods again under the same fence.
