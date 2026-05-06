---
date: 2026-05-06
severity: low
component: kube-system/idle-mitigations, k8s-2 thermal envelope
detected: 2026-05-06 13:40 UTC
mitigated: 2026-05-06 14:13 UTC
resolved: 2026-05-06 14:20 UTC
duration-from-trigger: ~1h 53m
related-plans: [0013, 0015]
related-commits: [de801143, f7b8cafc]
---

# 2026-05-06 - k8s-2 thermal/package throttle after idle mitigation rollout

> A plan 0013 runtime mitigation removed more idle behavior than intended on
> the MS-01 platform. k8s-2 entered sustained CPU package/core throttling and
> heated a nearby SN7100 NVMe slot. Relaxing k8s-2's PM-QoS request from `0 us`
> to `1 us` restored C1 idle while keeping the risky deep-idle state blocked.

## Summary

Commit `de801143` deployed the `idle-mitigations` DaemonSet to suppress the
suspected deep-idle/Vmin silent-reboot path. The DaemonSet held
`/dev/cpu_dma_latency` open with a `0 us` PM-QoS request. The intent was
"C0/C1 only", but direct cpuidle counters on k8s-2 showed that `0 us` admitted
only `POLL`; `C1_ACPI` did not increment.

That POLL-only behavior raised idle package heat enough that k8s-2, which has
less thermal headroom than the peer nodes, started incrementing
`node_cpu_package_throttles_total` and `node_cpu_core_throttles_total`. k8s-1
and k8s-3 remained at zero.

The fix was a k8s-2-only canary: write `1 us` instead of `0 us` to
`/dev/cpu_dma_latency`. On the MS-01, `1 us` allows `C1_ACPI` / `MWAIT 0x0` but
still blocks `C2_ACPI` and `C3_ACPI` / `MWAIT 0x60`, preserving the plan 0013
deep-idle mitigation.

## Impact

- Single-node thermal/package-throttle condition on k8s-2.
- No user-facing outage.
- No node reboot.
- CPU package temperature peaked around 90 C.
- k8s-2 `nvme1` Sensor 1 peaked around 93.85 C.
- Longhorn SMART data for the hot SN7100 showed no critical warning, media
  errors, warning temperature time, or critical composite temperature time.

## Timeline (UTC)

| Time | Event |
|---|---|
| 12:15 | Commit `de801143` authored with the plan 0013 mitigation stack. |
| 12:17-12:20 | Flux rolled out `idle-mitigations` cluster-wide. CPU frequency pinned near base clock and package temperatures rose. |
| 12:27 | First nonzero package/core throttle bucket on k8s-2. k8s-1/k8s-3 stayed at zero. |
| 13:40 | k8s-2-specific throttle spike investigated as active incident. |
| 14:08 | Patched DaemonSet applied live: k8s-2 PM-QoS changed to `1 us`; k8s-1/k8s-3 kept at `0 us`. |
| 14:10 | Commit `f7b8cafc` pushed with the GitOps version of the canary and incident file. |
| 14:11 | Flux reconciled `f7b8cafc`; live and desired state converged. |
| 14:13 | Five-minute package/core throttle rates on k8s-2 reached zero. |
| 14:20 | Ten-minute watch completed cleanly; incident marked mitigated. |

## Root Cause

The root cause was an incorrect platform assumption in the mitigation: `0 us`
PM-QoS did not mean "C0/C1 only" on the MS-01. It meant POLL-only. That removed
even shallow C1 idle residency, which materially increased package heat.

k8s-2 then crossed its thermal/package-throttle threshold because it had less
thermal margin than the other nodes. The exact chassis reason is not fully
localized, but supporting evidence includes:

- k8s-2's hot `nvme1` slot reached the high-80s/low-90s C band.
- k8s-2 fan1 had intermittent zero-RPM samples not seen on peer fan1 series.
- k8s-2 was the only node with throttle counters despite identical RAPL PL1/PL2
  limits across all three nodes.

## Resolution

Commit `f7b8cafc` changed the DaemonSet to:

- inject `NODE_NAME` from `spec.nodeName`;
- keep the PM-QoS request at `0 us` on k8s-1 and k8s-3;
- write `1 us` only on k8s-2.

Direct verification after rollout:

- k8s-2 pod log: `/dev/cpu_dma_latency = 1 us`.
- k8s-1/k8s-3 pod logs: `/dev/cpu_dma_latency = 0 us`.
- k8s-2 cpuidle sample: `C1_ACPI` increments while `C2_ACPI` and `C3_ACPI`
  remain flat.
- Package/core throttle rates fell to zero.
- k8s-2 remained Ready.

## What Went Well

- Off-cluster betty metrics made the throttle onset and node scope easy to
  prove.
- The mitigation was reversible remotely and did not require a reboot.
- The PM-QoS canary preserved the plan 0013 deep-idle protection rather than
  rolling it back.

## What Went Poorly

- The original DaemonSet comment overstated the behavior as "C0/C1 only" without
  checking cpuidle counters after rollout.
- The trade-off note underestimated thermal impact because it assumed C1 was
  still available.
- The incident exposed a k8s-2-specific cooling margin problem that still needs
  physical inspection.

## Post-Mitigation False Alarm

After mitigation, Grafana's `Node CPU %` panel briefly showed all nodes around
50-75% CPU. This was not real host load. It was caused by rolling
`node-exporter` during the RAPL/NVMe telemetry rollout: in-cluster Prometheus
had old and new pod-labeled `node_cpu_seconds_total` series for the same
`instance` inside the panel's 5-minute `rate()` window, so idle time was
undercounted and CPU percent was inflated.

Cross-checks:

- `kubectl top nodes` stayed low: roughly k8s-1 1%, k8s-2 13%, k8s-3 3%.
- Betty's stable off-cluster scrape never showed the >50% spike.
- The exact Grafana query normalized once the 5-minute rate window filled.

Actionable lesson: after node-exporter restarts, treat short CPU panel spikes
with suspicion and cross-check against `kubectl top nodes` or betty before
assuming workload CPU is actually high.

## Prevention

- [ ] Add a post-rollout verification step for any CPU idle/power mitigation:
  sample `cpuidle/state*/usage` before and after the change and record which
  states still increment.
- [ ] Keep k8s-2 at `1 us` while the 24-hour watch continues. Do not expand the
  canary to k8s-1/k8s-3 until k8s-2 remains clean.
- [ ] Add the throttle counters to the plan 0013 precursor observability set:
  `node_cpu_package_throttles_total` and `node_cpu_core_throttles_total`,
  grouped by node.
- [ ] Physically inspect k8s-2 fan/tach behavior and NVMe slot airflow during the
  next on-site window.
- [ ] Continue plan 0015's conservative BIOS/power profile work as the durable
  hardware baseline.

## Should this become an ADR?

Not yet. This is currently an implementation correction inside plan 0013 rather
than a durable architectural decision. If the cluster standardizes on a specific
PM-QoS value or BIOS power profile across all MS-01 nodes, capture that in the
plan 0015 close-out ADR.
