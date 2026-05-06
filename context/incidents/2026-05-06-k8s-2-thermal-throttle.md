---
status: Active
opened: 2026-05-06T14:20Z
detected-at: 2026-05-06T13:40Z
event-at: 2026-05-06T12:27Z
severity: SEV-3 (single-node thermal/package throttle; cluster serving)
related-plans: [0013, 0015]
related-postmortem: null
---

# 2026-05-06 - k8s-2 thermal/package throttle after idle mitigation rollout

## Summary

k8s-2 (`192.168.1.99:9100`) started incrementing CPU throttle counters after
the `idle-mitigations` DaemonSet rolled out from commit `de801143`. The counters
are unique to k8s-2; k8s-1 and k8s-3 remain at zero.

The leading mechanism is that the DaemonSet wrote a `0 us` PM-QoS request to
`/dev/cpu_dma_latency`. On the MS-01 this admits only `POLL`, not C1. That
removed deep C-states as intended for plan 0013, but also removed the shallow
C1 escape valve and pushed k8s-2 into a sustained thermal/package-throttle
zone. The hot Longhorn SN7100 in `nvme1` is a secondary risk surface.

## Impact

- k8s-2 package/core throttle counters active and sustained.
- k8s-2 CPU package reached about 90 C during the incident window.
- k8s-2 `nvme1` Sensor 1 reached about 93.85 C.
- No node reboot observed; k8s-2 boot time remains `2026-05-04T01:47Z`.
- Cluster services remain available.

## Detection

Betty/vmsingle showed:

- `increase(node_cpu_package_throttles_total{instance="192.168.1.99:9100"}[8h])`
  around 13k while k8s-1/k8s-3 were zero.
- `increase(node_cpu_core_throttles_total{instance="192.168.1.99:9100"}[8h])`
  around 13k while k8s-1/k8s-3 were zero.
- First nonzero two-minute throttle bucket at `2026-05-06T12:27Z`.
- Current package throttle rate before mitigation around 4-5/sec.

## Relevant Findings

- Plan ownership: plan 0009 is abandoned and superseded by plan 0013; plan 0015
  owns the BIOS/runtime power-profile mitigation track.
- `idle-mitigations` successfully holds PM-QoS and disables NVMe APST/HMB. ASPM
  write currently warns and does not apply.
- k8s-2 `nvme1n1` is `WD_BLACK SN7100 1TB`, Longhorn disk `longhorn-1`, with
  several scheduled replicas.
- Longhorn SMART data for k8s-2 `longhorn-1` showed `CriticalWarning=0`,
  `WarningTempTime=0`, `CriticalCompTime=0`, `MediaErrors=0`, and
  `NumErrLogEntries=0`.
- RAPL package limits are identical across nodes: PL1 60 W, PL2 80 W. A quick
  package-energy sample put k8s-2 around 35 W, so sustained PL1 saturation is
  not the primary explanation.
- k8s-2 fan1 has intermittent zero-RPM samples while peer nodes do not show the
  same fan1 zero pattern. This may be tach sampling noise or a cooling asymmetry;
  it needs physical inspection later, but it is not required for the software
  mitigation.

## Mitigation In Progress

Canary k8s-2 only:

- Change PM-QoS from `0 us` to `1 us` on k8s-2.
- Keep k8s-1 and k8s-3 at `0 us`.
- Keep HMB disabled.
- Keep NVMe APST disabled.
- Do not re-enable deep idle states.

Expected result: k8s-2 can enter `C1_ACPI` / `MWAIT 0x0` while `C2_ACPI` and
`C3_ACPI` / `MWAIT 0x60` remain blocked. Throttle rate and CPU/NVMe temps
should drop without reopening the plan 0013 deep-idle failure surface.

## Watch Criteria

Mitigated if, after the canary rollout:

- `rate(node_cpu_package_throttles_total{instance="192.168.1.99:9100"}[5m])`
  falls to zero or near-zero and stays there.
- `rate(node_cpu_core_throttles_total{instance="192.168.1.99:9100"}[5m])`
  falls to zero or near-zero and stays there.
- CPU package temperature drops materially from the 80-90 C band.
- `nvme_nvme1` Sensor 1 trends down from the high-80s/low-90s C band.
- k8s-2 remains Ready with no reboot.

## Follow-Ups

- If the canary works, update plan 0013 and write a postmortem.
- Consider expanding `1 us` to all nodes only after the k8s-2 watch is clean.
- Inspect k8s-2 fan/tach and chassis airflow physically when convenient.
- Continue plan 0015 BIOS/power-profile work as the durable hardware baseline.
