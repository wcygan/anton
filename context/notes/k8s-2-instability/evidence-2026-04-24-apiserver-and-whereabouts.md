# 2026-04-24 apiserver + whereabouts follow-up

## Scope

Read-only cluster checks plus one local GitOps manifest hardening change. No
direct cluster mutation was performed.

## Prometheus measurement correction

The earlier `topk(10, sum by (pod, container) (...container_memory...))`
query double-counted cAdvisor because the same kubelet endpoint is scraped by
two ServiceMonitors. Use `max by (pod, container) (...)` for container memory
attribution.

Corrected k8s-2 kube-apiserver memory around the 2026-04-23 reboot window:

| Time UTC | WSS MiB | RSS MiB | Cache MiB |
|---|---:|---:|---:|
| 20:30 | 809 | 727 | 350 |
| 20:37 | 970 | 888 | 351 |
| 20:43 | 1006 | 925 | 353 |
| 20:46 | 1265 | 1181 | 357 |

So the real rise is still large, but about **+456 MiB WSS / +454 MiB RSS**,
not +950 MiB. Node-level memory moved more than the apiserver alone:

| Time UTC | Active anon MiB | AnonPages MiB | MemAvailable MiB |
|---|---:|---:|---:|
| 20:30 | 2018 | 1869 | 91610 |
| 20:37 | 2365 | 2215 | 91244 |
| 20:43 | 2485 | 2313 | 91095 |
| 20:46 | 2987 | 2815 | 90622 |

Top RSS deltas from 20:30 -> 20:46 among containers already present at 20:30:

| Pod | Container | RSS delta MiB |
|---|---|---:|
| kube-apiserver-k8s-2 | kube-apiserver | 454 |
| longhorn-manager-kqfjh | longhorn-manager | 29 |
| instance-manager-dea08a8882257aeac9b60752069609d2 | instance-manager | 26 |
| kube-scheduler-k8s-2 | kube-scheduler | 6 |
| cilium-22f9m | cilium-agent | 2 |

New containers also contributed but did not dominate the RSS picture
(`cilium-operator` ~75 MiB RSS, `harbor-postgres-1` ~30 MiB RSS by 20:46).
Some node-anon growth remains outside the top tracked containers, either root
cgroup/runtime memory or many small containers.

Source queries:

```promql
max by (pod, container) (container_memory_working_set_bytes{node="k8s-2",container!=""})
max by (__name__) ({__name__=~"container_memory_rss|container_memory_cache|container_memory_working_set_bytes",node="k8s-2",pod="kube-apiserver-k8s-2",container="kube-apiserver"})
max by (__name__) ({__name__=~"node_memory_Active_anon_bytes|node_memory_AnonPages_bytes|node_memory_MemAvailable_bytes",instance="192.168.1.99:9100"})
```

## Apiserver traffic attribution

The 04-23 k8s-2 apiserver did not show a huge ordinary request storm before
reset. It did show a watch/longrunning jump shortly before the reset:

| Time UTC | k8s-2 request QPS | audit events/s | longrunning requests | watch events/s |
|---|---:|---:|---:|---:|
| 20:30 | 1.00 | 2.13 | 42 | 3.37 |
| 20:37 | 1.20 | 6.80 | 60 | 18.53 |
| 20:43 | 1.23 | 3.33 | 76 | 11.03 |
| 20:46 | 4.50 | 30.70 | 350 | 60.68 |
| 20:47 | 7.13 | not sampled | 453 | not sampled |

Top k8s-2 watch-event resources at 20:46 were `leases` (24.07/s), `pods`
(6.27/s), `customresourcedefinitions` (5.37/s), `ciliumendpoints` (4/s), and
Longhorn `settings` (3.53/s). Inflight requests stayed low
(1 mutating, 1 read-only at 20:46). Etcd request rates through k8s-2 were
modest at 20:46 (`get` 5.2/s, `update` 2.47/s, `list` 0.3/s).

Interpretation: this looks more like watch rehydration / HA load redistribution
after the k8s-3 intentional reboot and Harbor churn than a classic LIST storm.
It is still the biggest single container-memory mover before the k8s-2 reset,
but it does not explain the 04-21 reboot by itself.

## 04-21 comparison

At the 2026-04-21 20:34Z k8s-2 reset, apiserver memory was high but falling:

| Time UTC | WSS MiB | RSS MiB | Cache MiB | request QPS | longrunning | watch events/s |
|---|---:|---:|---:|---:|---:|---:|
| 20:20 | 1177 | 1093 | 831 | 9.43 | 154 | 22.83 |
| 20:30 | 1120 | 1035 | 844 | 9.97 | 154 | 23.33 |
| 20:34 | 1086 | 1002 | 849 | 8.63 | 155 | 22.90 |

No pre-reset apiserver surge was visible on 04-21.

## Whereabouts restart cause

`whereabouts-6chbl` current status:

- `restartCount=10`
- last termination: `reason=Error`, `exitCode=1`
- last started `2026-04-23T20:47:25Z`, finished `2026-04-23T20:47:57Z`
- `kubectl get events --field-selector involvedObject.name=whereabouts-6chbl`
  returned no events

`kubectl -n network logs whereabouts-6chbl --previous` shows the last crash was:

```text
2026-04-23T20:47:57Z [error] could not create the pod networks controller:
Could not find node with node name 'k8s-2'.: Get "https://10.43.0.1:443/api/v1/nodes/k8s-2": dial tcp 10.43.0.1:443: i/o timeout
```

Interpretation: the last whereabouts crash was API/network unavailability while
k8s-2 was recovering, not OOM and not clear IPAM corruption. Kubernetes only
preserves the most recent prior container log, so this does not classify all 10
restarts.

## Local repo hardening

Patched `kubernetes/apps/network/multus/app/flux-kustomization.yaml` to raise
`kube-multus-ds` memory request/limit from `256Mi` to `512Mi`. This addresses
the real 04-23 Multus OOMs as CNI hardening, independent of the k8s-2 reset
root cause. Validation:

```text
kubectl kustomize kubernetes/apps/network/multus/app
```

Build succeeded.

