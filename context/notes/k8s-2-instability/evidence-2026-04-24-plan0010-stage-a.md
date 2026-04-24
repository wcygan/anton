# evidence 2026-04-24 — plan 0010 Stage A execution

k8s-2 re-admitted to scheduling via the staged `anton.io/rejoin` gate. 8-pod smoke cohort landed cleanly, no CNI restart spike, no silent reboot, no abort alert fired.

## Commits

- `f69f6507` — Stage A wire: add `./k8s-2-rejoin-smoke/ks.yaml` to `kubernetes/apps/playground/kustomization.yaml`.
- `d8ae298d` — fix: add `namespace: playground` directive to the namespace kustomization; cluster-apps rejected the unqualified Flux Kustomization with "namespace not specified" until this was in place.

## Timeline (UTC)

| Time | Event |
|---|---|
| 18:28:00Z | Pre-state snapshot captured (k8s-2 boot 1776977231, 22 pods Running, CNI restarts 0, no abort alerts) |
| 18:29:00Z | `cluster-apps` observed `d8ae298d` after first reconcile (had previously failed on `f69f6507`) |
| ~18:31Z | `playground/k8s-2-rejoin-smoke` Kustomization Ready=True, 8 Pending pods |
| 18:31:~Z | `kubectl uncordon k8s-2` — cordon taint dropped, `anton.io/rejoin=k8s-2:NoSchedule` retained |
| 18:31:52–53Z | All 8 pods transitioned Pending → ContainerCreating → Running within seconds; first heartbeat lines emitted |

## Pre/post comparison

| Metric | Pre | Post |
|---|---|---|
| k8s-2 `node_boot_time_seconds` | 1776977231 | 1776977231 (unchanged — no silent reboot) |
| k8s-2 `unschedulable` | true | false |
| k8s-2 taints | `node.kubernetes.io/unschedulable:NoSchedule` + `anton.io/rejoin=k8s-2:NoSchedule` | `anton.io/rejoin=k8s-2:NoSchedule` only |
| Pods on k8s-2 | 22 Running | 30 Running (+8 smoke cohort) |
| Multus restarts (per-node) | 0 / 0 / 0 | 0 / 0 / 0 |
| Whereabouts restarts (per-node) | 0 / 0 / 0 | 0 / 0 / 0 |
| storage-vxlan restarts (per-node) | 0 / 0 / 0 | 0 / 0 / 0 |
| Active abort-relevant alerts | 0 | 0 |

## Smoke cohort details

- `playground/k8s-2-rejoin-smoke` Deployment, 8 replicas
- Image: `docker.io/library/busybox:1.37.0`
- Each pod emits `heartbeat <ISO8601> pod=<name> node=k8s-2` every 60s
- Resource footprint: `5m/16Mi` req, `32Mi` memory limit per pod; total 40m / 128Mi req, 256Mi limit
- All pods carry toleration for `anton.io/rejoin=k8s-2:NoSchedule` and required nodeAffinity `kubernetes.io/hostname=k8s-2`

First 8 heartbeat lines confirmed at 18:31:52–18:31:53Z, one per pod, all tagging `node=k8s-2`. Cilium assigned pod IPs from the 10.42.2.0/24 range specific to k8s-2.

## Abort triggers (armed via PrometheusRule `k8s-2-rejoin-abort` + `cni-plumbing`)

- `node_boot_time_seconds{instance="192.168.1.99:9100"}` change (silent reboot on k8s-2)
- CNI restart spike or OOMKilled reason on multus / whereabouts / storage-vxlan
- kube-apiserver WSS growth > 384 MiB / 20 min
- apiserver longrunning_requests jump, watch-event burst, or APF queue growth
- Longhorn degraded/failed replica storm tied to k8s-2
- Vector/Talos kernel stream goes silent for k8s-2

## Abort action

1. `mise exec -- kubectl cordon k8s-2` — restores the cordon taint; the smoke pods lose k8s-2-required affinity and go Pending (but stay owned by the Deployment).
2. Preserve evidence: do NOT unwire the smoke app. Leave it ingested so any residual pods/state on k8s-2 remain inspectable.
3. Raise handoff to plan 0009 (silent-reboot) or a new physical-access plan depending on which abort fired.

## 24 h watch window

Starts at first-heartbeat timestamp **2026-04-24T18:31:52Z**. If no abort trigger fires, Stage A passes on 2026-04-25T18:31:52Z and plan 0010 Phase 5 Stage B (broader tolerated workloads for 48h) becomes the next gate.
