# 2026-04-24 — plan 0010 staged hardening

## Scope

Repo-side changes authored for plan 0010 before any live deployment or Talos
apply. This note separates "validated in Git/rendered config" from "active on
the cluster."

## Persistent k8s-2 rejoin gate

`talos/talconfig.yaml` now renders a k8s-2-only node label and taint:

```yaml
machine:
  nodeLabels:
    anton.io/rejoin: k8s-2
  nodeTaints:
    anton.io/rejoin: k8s-2:NoSchedule
```

Rendered placement:

| Rendered config | Rejoin label/taint |
|---|---|
| `talos/clusterconfig/kubernetes-k8s-1.yaml` | absent |
| `talos/clusterconfig/kubernetes-k8s-2.yaml` | present |
| `talos/clusterconfig/kubernetes-k8s-3.yaml` | absent |

Validation:

```text
mise exec -- yq eval '.' talos/talconfig.yaml
mise exec -- task talos:generate-config
cd talos && mise exec -- talhelper validate talconfig
mise exec -- talosctl validate --mode=metal --config talos/clusterconfig/kubernetes-k8s-{1,2,3}.yaml
```

Live status at authoring time: not applied. k8s-2 remains protected by the
imperative cordon/unschedulable taint captured in
`evidence-2026-04-24-plan0010-baseline.md`.

## CNI and kubelet hardening

Already authored and locally validated in the same execution pass:

| File | Change |
|---|---|
| `kubernetes/apps/network/multus/app/flux-kustomization.yaml` | Multus `512Mi` request/limit and `priorityClassName: system-node-critical` |
| `kubernetes/apps/network/whereabouts/app/flux-kustomization.yaml` | Whereabouts `128Mi` request, `512Mi` limit, and `priorityClassName: system-node-critical` |
| `kubernetes/apps/network/storage-vxlan/app/daemonset.yaml` | VXLAN `64Mi` request, `128Mi` limit, and `priorityClassName: system-node-critical` |
| `talos/patches/global/machine-kubelet.yaml` | kubelet `systemReserved`, `kubeReserved`, and `evictionHard` headroom |
| `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-cni-plumbing.yaml` | CNI restart, OOMKilled, and memory-near-limit alerts |
| `kubernetes/apps/observability/kube-prometheus-stack/app/prometheusrule-k8s-2-rejoin-abort.yaml` | k8s-2 reboot, kube-apiserver rapid memory growth, longrunning/watch burst, and APF queue abort/watch alerts |

Validation:

```text
kubectl kustomize kubernetes/apps/network/multus/app
kubectl kustomize kubernetes/apps/network/whereabouts/app
kubectl kustomize kubernetes/apps/network/storage-vxlan/app
kubectl kustomize kubernetes/apps/observability/kube-prometheus-stack/app
kubectl get priorityclass system-node-critical system-cluster-critical -o wide
```

The five k8s-2 rejoin abort PromQL expressions were also checked against the
live Prometheus API and parsed successfully:

```text
changes(node_boot_time_seconds{instance="192.168.1.99:9100"}[10m]) > 0
max(delta(container_memory_working_set_bytes{node="k8s-2",namespace="kube-system",pod="kube-apiserver-k8s-2",container="kube-apiserver"}[20m])) > 384 * 1024 * 1024
delta(sum(apiserver_longrunning_requests{job="apiserver",instance="192.168.1.99:6443"})[10m:]) > 40
sum(rate(apiserver_watch_events_total{job="apiserver",instance="192.168.1.99:6443"}[5m])) > 20
sum(apiserver_flowcontrol_current_inqueue_requests{instance="192.168.1.99:6443"}) > 0
```

## Deployment gates still open

- Commit/push and Flux reconcile for Kubernetes app changes.
- Talos apply plan for kubelet reservations and persistent k8s-2 taint/label.
- Pre/post allocatable-memory capture after Talos apply.
- Live verification that k8s-2 has both the persistent `anton.io/rejoin`
  taint/label and the existing cordon until Stage A begins.
