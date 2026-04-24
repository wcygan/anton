# 2026-04-24 — plan 0010 execution baseline

## Scope

Read-only baseline captured before deploying the software-side k8s-2 rejoin
hardening from plan 0010. No live cluster mutations were made during these
checks.

Timestamp: `2026-04-24T16:53:13Z`

## Node and pod state

| Check | Result |
|---|---|
| k8s-2 Kubernetes state | `Ready,SchedulingDisabled` |
| k8s-2 live taints | `node.kubernetes.io/unschedulable:NoSchedule` |
| k8s-2 rejoin label | absent (`anton.io/rejoin` unset) |
| Pods assigned to k8s-2 | 22 `Running` |
| Non-running pods assigned to k8s-2 | none |
| k8s-2 allocatable before reservations | `19950m` CPU, `97951180Ki` memory, `110` pods |

Sources:

```text
kubectl get nodes -o wide
kubectl describe node k8s-2
kubectl get node k8s-2 -o json
kubectl get pods -A --field-selector spec.nodeName=k8s-2 -o wide
kubectl get pods -A --field-selector spec.nodeName=k8s-2,status.phase!=Running,status.phase!=Succeeded
```

## Boot epochs

Prometheus `node_boot_time_seconds` at baseline:

| Node | Boot time |
|---|---|
| k8s-1 | `2026-04-16T19:49:31Z` |
| k8s-2 | `2026-04-23T20:47:11Z` |
| k8s-3 | `2026-04-23T20:45:29Z` |

Source:

```text
node_boot_time_seconds{instance=~"192.168.1.(98|99|100):9100"}
```

## Recent restart and OOM surface

Prometheus showed no restart increments and no OOMKilled increments in the
network/kube-system/storage watchlist over the previous 6 hours.

Current CNI DaemonSet restart counters still reflect the 04-23 incident window:

| DaemonSet pod | Node | Restarts |
|---|---|---:|
| `kube-multus-ds-vmz29` | k8s-1 | 5 |
| `kube-multus-ds-5r6zx` | k8s-2 | 2 |
| `kube-multus-ds-hpt2m` | k8s-3 | 0 |
| `storage-vxlan-mtvp7` | k8s-2 | 5 |
| `whereabouts-6chbl` | k8s-2 | 10 |
| `whereabouts-cxms7` | k8s-3 | 1 |

Sources:

```text
increase(kube_pod_container_status_restarts_total{namespace=~"network|kube-system|storage"}[6h])
increase(kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}[6h])
kubectl -n network get pods -o wide
```

## k8s-2 memory snapshot

Largest working sets on k8s-2 at baseline:

| Namespace | Pod/container | WSS |
|---|---|---:|
| kube-system | `kube-apiserver-k8s-2/kube-apiserver` | 1066 MiB |
| storage | `longhorn-manager-.../longhorn-manager` | 232 MiB |
| kube-system | `cilium-.../cilium-agent` | 175 MiB |
| storage | `instance-manager-.../instance-manager` | 156 MiB |
| registries | `harbor-postgres-1/postgres` | 93 MiB |
| network | `kube-multus-ds-5r6zx/kube-multus` | 53 MiB |
| network | `whereabouts-6chbl/whereabouts` | 14 MiB |
| network | `storage-vxlan-mtvp7/vxlan` | 4 MiB |

Sources:

```text
topk(12, max by(namespace,pod,container) (container_memory_working_set_bytes{node="k8s-2",container!=""}))
max by(namespace,pod,container) (container_memory_working_set_bytes{node="k8s-2",namespace="network",container=~"kube-multus|whereabouts|vxlan"})
```

## Longhorn state

Longhorn sees k8s-2 as healthy but unschedulable because Kubernetes has the node
cordoned:

| Field | Value |
|---|---|
| `allowScheduling` | `false` |
| Ready condition | `True` |
| Schedulable condition | `False`, reason `KubernetesNodeCordoned` |
| Disks | `longhorn-1` and `longhorn-2` both `allowScheduling: true`, `evictionRequested: false` |
| Replicas currently on k8s-2 | 1 running replica (`pvc-77d63b24-2ee0-40df-a6d8-0198c4fbee34-r-c91fcfae`) |

Sources:

```text
kubectl -n storage get nodes.longhorn.io k8s-2 -o json
kubectl -n storage get replicas.longhorn.io -o json
```

## Vector sink state

The Talos log sink is running and receiving k8s-2 kernel-source records. Recent
k8s-2 lines were DNS/discovery warnings, not a panic/oops/reset signature.

Sources:

```text
kubectl -n observability get pod talos-log-sink-vector-0 -o wide
kubectl -n observability exec talos-log-sink-vector-0 -c rotator -- \
  grep '"source":"kernel"' /vector-data-dir/talos-sink-2026-04-24.log
```

## Staged repo-side hardening

The following file-side changes have been authored but not deployed to the live
cluster at this baseline:

| File | Staged intent |
|---|---|
| `kubernetes/apps/network/multus/app/flux-kustomization.yaml` | Multus `256Mi -> 512Mi`; add `priorityClassName: system-node-critical` |
| `kubernetes/apps/network/whereabouts/app/flux-kustomization.yaml` | Whereabouts `128Mi` request / `512Mi` limit; add `priorityClassName: system-node-critical` |
| `kubernetes/apps/network/storage-vxlan/app/daemonset.yaml` | VXLAN `64Mi` request / `128Mi` limit; add `priorityClassName: system-node-critical` |
| `talos/patches/global/machine-kubelet.yaml` | Add `systemReserved`, `kubeReserved`, and hard eviction thresholds |
| `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-cni-plumbing.yaml` | Add CNI restart, OOMKilled, and memory-near-limit alerts |

Validation completed:

```text
kubectl kustomize kubernetes/apps/network/multus/app
kubectl kustomize kubernetes/apps/network/whereabouts/app
kubectl kustomize kubernetes/apps/network/storage-vxlan/app
kubectl kustomize kubernetes/apps/observability/kube-prometheus-stack/app
mise exec -- yq eval '.' talos/patches/global/machine-kubelet.yaml
mise exec -- task talos:generate-config
cd talos && mise exec -- talhelper validate talconfig
rg 'systemReserved|kubeReserved|evictionHard|memory.available' talos/clusterconfig/kubernetes-k8s-*.yaml
kubectl get priorityclass system-node-critical system-cluster-critical -o wide
```

Notes:

- `task talos:generate-config` is not on the bare shell `PATH`; it succeeds via
  `mise exec -- task talos:generate-config`.
- Multus and Whereabouts app kustomizations render Flux `Kustomization` objects
  containing upstream JSON patches, not the final upstream DaemonSets. Final
  live patch application still needs Flux build/reconcile validation before
  deployment.
- The live cluster still has the old CNI resource limits at this baseline.
