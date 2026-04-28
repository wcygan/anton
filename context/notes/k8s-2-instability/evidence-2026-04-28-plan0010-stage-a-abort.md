# 2026-04-28 — plan 0010 Stage A abort

Stage A of plan 0010 ("stage k8s-2 software rejoin") was launched at
2026-04-24T18:31:52Z with the `k8s-2-rejoin-smoke` Deployment pinned to k8s-2.
The 24 h watch window closed at 2026-04-25T18:31:52Z. Within ~1 h of the
window closing, k8s-2 began rebooting silently and continued doing so over
the following ~3 days.

This note records the abort decision, the evidence that triggered it, and
the immediate state-preservation steps taken so a follow-up plan can pick
up without re-running the abort detection.

## Abort decision

Trigger: `K8s2UnexpectedReboot` (PrometheusRule `k8s-2-rejoin-abort`,
group `k8s-2-rejoin-abort`).

`changes(node_boot_time_seconds[3d])` per node at 2026-04-28T~14:59Z:

| node                 | changes_3d |
|----------------------|------------|
| 192.168.1.98 (k8s-1) | 0          |
| 192.168.1.99 (k8s-2) | 6          |
| 192.168.1.100 (k8s-3)| 0          |

The 6 reboots are k8s-2-only. k8s-1 and k8s-3 are stable.

## k8s-2 reboot timeline (last 3 days)

Reconstructed from `node_boot_time_seconds{instance="192.168.1.99:9100"}`
range query (5 min step). `boot_at` is the kernel boot epoch; `first_observed`
is the first scrape that saw that epoch.

| boot_at (UTC)        | first_observed (UTC) | notes                                                 |
|----------------------|----------------------|-------------------------------------------------------|
| 2026-04-23T20:47:11Z | 2026-04-25T15:00:00Z | Pre-Stage-A boot, retained throughout 04-24 hardening |
| 2026-04-25T19:32:04Z | 2026-04-25T19:35:00Z | First reboot, ~60 min after Stage A 24 h close        |
| 2026-04-25T21:04:19Z | 2026-04-25T21:05:00Z | Second reboot ~1.5 h later                            |
| 2026-04-27T04:56:08Z | 2026-04-27T05:00:00Z |                                                       |
| 2026-04-27T21:42:29Z | 2026-04-27T21:45:00Z |                                                       |
| 2026-04-28T04:39:48Z | 2026-04-28T04:45:00Z |                                                       |
| 2026-04-28T10:37:33Z | 2026-04-28T10:40:00Z | Most recent reboot, ~4.4 h before abort               |

Six post-Stage-A boots in ~63 hours; mean inter-reboot interval ~10.5 h.

## Workload-side fingerprint

Smoke pods (`k8s-2-rejoin-smoke-559b6b5d4b-*`, 8 replicas pinned to k8s-2,
ages 3d20h):

- restarts: 6 each (matches the post-Stage-A reboot count exactly)
- last termination: 2026-04-28T10:37:40Z (matches the 7th boot epoch within
  ~7 s — pods were killed by the host going down, then re-created on the
  fresh boot)
- termination reason: `Unknown` (signature of kernel-died-out-from-under
  the runtime, identical to pre-plan-0010 silent-reboot pattern)

CNI pods on k8s-2:

| pod                  | restarts |
|----------------------|----------|
| kube-multus-ds-cvvnt | 6        |
| storage-vxlan-hkjhm  | 6        |
| whereabouts-w9m2h    | 12       |

CNI pods on k8s-1 and k8s-3 are at 0 restarts each.

## Abort-state on k8s-2 just before cordon

| metric                              | value           |
|-------------------------------------|-----------------|
| uptime                              | 4.35 h          |
| `boot_changes[10m]`                 | 0               |
| apiserver WSS 20 m delta            | −31.5 MiB       |
| apiserver WSS absolute              | 862 MiB         |
| apiserver `watch_events_total` rate | 3.35 /s         |
| apiserver APF queued                | 0               |
| apiserver `longrunning_requests`    | 42              |
| Longhorn degraded volumes           | 0               |
| Vector pod                          | 4d18h, 0 restart|

The instantaneous abort criteria the rule set checks for (WSS 20 m delta,
watch burst, APF queue, longrunning jump) were quiet at observation time.
The reboot pattern itself is the abort signal.

## Action taken

Cordon applied at 2026-04-28T14:59:37Z:

```
$ kubectl cordon k8s-2
node/k8s-2 cordoned
```

`k8s-2` taints after cordon:

```
[
  {"effect":"NoSchedule","key":"anton.io/rejoin","value":"k8s-2"},
  {"effect":"NoSchedule","key":"node.kubernetes.io/unschedulable",
   "timeAdded":"2026-04-28T14:59:37Z"}
]
```

The Flux-managed `k8s-2-rejoin-smoke` Deployment is **left in place**
deliberately, per the plan-0010 abort instructions ("preserve evidence,
do not unwire the smoke app"). Pods remain on k8s-2 for forensic review;
re-running the rejoin will require an explicit unwire.

`talos-log-sink-vector` is still receiving from 192.168.1.99 (4d18h pod,
0 restarts), so kernel-stream evidence for the seven boots is captured
in the Vector sink and can be mined per-reboot.

## Open follow-ups

- Determine whether this recurrence belongs in plan 0009 (silent-reboot
  root cause) or warrants a new physical-access plan, per plan 0010's
  Phase 5 closing bullet.
- Mine Vector logs around each of the 7 reboot timestamps for
  netconsole / kernel-panic / oops markers; correlate with cilium-agent
  memory and apiserver WSS at each event.
- Decide whether to keep the smoke Deployment running on the cordoned
  node or scale it to 0 once enough evidence is captured (evicting it
  is **not** required by the abort itself).
- Record the abort in plan 0010 and tick the relevant Phase 5 bullet.
