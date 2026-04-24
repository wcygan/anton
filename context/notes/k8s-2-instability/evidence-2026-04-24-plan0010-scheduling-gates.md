# 2026-04-24 — plan 0010 scheduling gates

## Scope

Scheduling policy for k8s-2 staged rejoin before any uncordon. This is a plan
gate, not a live-cluster mutation.

## Freeze

Until Stage A and Stage B pass, freeze unrelated high-churn work:

- no Harbor drain drills
- no Longhorn maintenance or replica reshaping on k8s-2
- no Cilium, Talos, Kubernetes, or storage-network upgrades
- no broad Flux reconciliations unrelated to plan 0010
- no throwaway probe pods during a drain/rejoin window

Use long-lived existing probes for health checks during churn. Plan 0006 already
showed a fresh probe pod can be blocked by the same CNI admission path being
tested.

## Stage A cohort

The first tolerated cohort should be deliberately boring:

| Requirement | Stage A rule |
|---|---|
| Workload type | stateless compute/test pods only |
| Replicas | 5-10 total pods |
| Storage | no PVCs, no Longhorn volumes |
| Networking | ordinary Cilium pod network only; no Multus secondary attachments |
| Placement | `nodeSelector` or required affinity to `kubernetes.io/hostname=k8s-2` |
| Gate | explicit toleration for `anton.io/rejoin=k8s-2:NoSchedule` |
| Exclusions | Harbor, CNPG, Dragonfly, SeaweedFS, Longhorn, observability singletons, Flux/controllers, CNI pods, CSI pods, control-plane pods |

Preferred implementation when Stage A begins: create or enable a purpose-built
`playground` Deployment such as `k8s-2-rejoin-smoke` with 5-10 small replicas,
the rejoin toleration, and no service-critical role. Existing app candidates
like `default/echo` or `bakery-site/bakery-server` can be used later only if
patched explicitly; they are not the first cohort by default.

## Topology/anti-affinity review

Current hard taint is the primary protection. Existing high-churn/stateful
workloads should not be allowed to tolerate `anton.io/rejoin` during Stage A/B.

Observed state from `kubectl get deploy,sts -A -o wide` and targeted pod lists:

| Area | Current finding | Stage gate |
|---|---|---|
| Harbor | most chart pods are currently on k8s-1; no plan-0010 toleration | keep excluded until Stage C |
| Harbor Postgres | one instance currently on k8s-2 from the 04-23 recovery | do not add toleration; do not run Harbor drain drill |
| Dragonfly | 3-replica statefulset currently all on k8s-1 | keep excluded; revisit anti-affinity before normal scheduling |
| SeaweedFS volume | volume anti-affinity exists in the Seaweed CR | keep excluded during Stage A/B despite volume spread |
| SeaweedFS master/filer/S3 | replicas exist; spread is imperfect after 04-23 | keep excluded during Stage A/B |
| Longhorn/CSI | controller replicas include k8s-2 today because DaemonSets/static controllers run there | do not use Longhorn scheduling as Stage A signal; keep Longhorn node scheduling disabled |
| Observability | Prometheus, Alertmanager, Grafana, and Vector sink are on k8s-1 | keep singleton observability off k8s-2 |

## Interpretation

Do not spend time broadening topology spread before Stage A. The hard taint
already prevents accidental placement of existing workloads unless a workload
is explicitly granted a toleration. Topology spread/anti-affinity is a Stage C
or full-rejoin requirement, when we consider relaxing the taint and allowing
normal workloads back onto k8s-2.
