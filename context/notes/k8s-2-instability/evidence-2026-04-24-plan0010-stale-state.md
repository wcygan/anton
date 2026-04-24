# 2026-04-24 — plan 0010 stale-state recheck

## Scope

Read-only check for persistent kubelet/containerd/Longhorn residue before
deciding whether k8s-2 needs a software reset before staged rejoin.

## Kubernetes pod state

No cluster pods are currently `Unknown` or waiting in `ContainerCreating`.
Specifically on k8s-2, all 22 assigned pods are `Running`.

Source:

```text
kubectl get pods -A -o json
kubectl get pods -A --field-selector spec.nodeName=k8s-2,status.phase!=Running,status.phase!=Succeeded -o wide
```

## Talos/containerd state

`talosctl containers -k` on k8s-2 reports only expected statuses:

- `SANDBOX_READY`
- `CONTAINER_RUNNING`
- `CONTAINER_EXITED` for init containers or previous terminated containers

No `SANDBOX_NOTREADY`, `CONTAINER_UNKNOWN`, or other unexpected runtime states
were present.

Source:

```text
talosctl -n 100.87.89.3 --endpoints=100.75.61.79 \
  --talosconfig=/Users/wcygan/Development/anton/talos/clusterconfig/talosconfig \
  containers -k
```

## Kubelet log residue

Recent kubelet log tail still contains cleanup fallout after the 04-23 reboot:

- `ContainerStatus from runtime service failed ... not found`
- `DeleteContainer returned error`
- `failed to set removing state ... container is already in removing state`
- early boot `driver.longhorn.io not found in the list of registered CSI drivers`
- old `clean-cilium-state` CrashLoopBackOff entries from the ADR 0021/0022
  incident

These messages were clustered around boot/recovery (`2026-04-23T20:47Z`) and
the cilium clean-state rollback window (`2026-04-23T23:50Z`). The latest matched
line in the 1000-line tail was a kubelet proxy broken-pipe message at
`2026-04-24T14:12:18Z`, not ongoing sandbox or volume reconciliation failure.

Source:

```text
talosctl -n 100.87.89.3 --endpoints=100.75.61.79 \
  --talosconfig=/Users/wcygan/Development/anton/talos/clusterconfig/talosconfig \
  logs kubelet --tail=1000
```

## Longhorn state

Longhorn volumes are healthy, but k8s-2 is not clean enough for immediate normal
storage scheduling:

| Check | Result |
|---|---|
| Longhorn node k8s-2 | `Ready=True`, `allowScheduling=false`, `Schedulable=False` due to Kubernetes cordon |
| Longhorn volumes | all listed volumes `attached` and `healthy` |
| Running replicas on k8s-2 | one (`pvc-77d63b24-2ee0-40df-a6d8-0198c4fbee34-r-c91fcfae`) |
| Stopped replica CRs with no node/disk | three, all from the 04-23 recovery window |

Stopped replica CRs:

| Replica | State | Node | Disk |
|---|---|---|---|
| `pvc-44f30e6f-5840-459d-b697-35d13f3a60a7-r-71a38b5c` | stopped | empty | empty |
| `pvc-a812745e-27fd-4fb6-809c-522303f22e53-r-d79b4efc` | stopped | empty | empty |
| `pvc-f95d9f39-5702-4a80-918c-7f2a8996974e-r-79e047c2` | stopped | empty | empty |

Source:

```text
kubectl -n storage get volumes.longhorn.io,replicas.longhorn.io,engineimages.longhorn.io,nodes.longhorn.io -o wide
kubectl -n storage get replicas.longhorn.io -o json
```

## Interpretation

The 04-20 blocker, "pods stuck `Unknown`/`ContainerCreating` after reboot,"
is not present now. A Talos reset/rejoin is therefore not required before a
limited compute-only Stage A, provided the hard rejoin taint stays in place and
storage/stateful workloads remain excluded.

Do not re-enable normal k8s-2 storage scheduling or run Longhorn maintenance on
k8s-2 until the stopped replica CRs are reviewed or Longhorn has cleaned them up.
This is a Stage C/full-rejoin gate, not a Stage A blocker.
