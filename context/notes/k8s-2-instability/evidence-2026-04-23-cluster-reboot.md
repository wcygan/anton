# 2026-04-23 — Two-node reboot (k8s-3 + k8s-2) cascade

## One-line

k8s-3 rebooted at ~20:45Z, k8s-2 at ~20:47Z (2 min later); k8s-1 stayed up
7d+; same silent-hang signature as the 2026-04-21 20:34Z k8s-2 reboot
(exit 255, ~30s network silence, no kernel panic / oops / oom captured
in the Vector sink before the reboot). **Falsifies "k8s-2-specific
hardware defect" framing.**

## Detection

Monitoring cron `ba4b7418` (10-min cadence, deleted on reboot per the
"ON REBOOT" protocol) caught the uptime decrease on k8s-2 at tick 243
(20:54:06Z). Manual follow-up revealed k8s-3 also rebooted 2 min earlier.

| Node  | Tailscale IP     | Uptime at 21:14Z | Reboot at    | Reboots during investigation |
|-------|------------------|------------------|--------------|------------------------------|
| k8s-1 | 100.75.61.79     | **609906s (7.1d)** | —            | 0 (baseline stable)        |
| k8s-2 | 100.87.89.3      | 1646s (27m)      | ~2026-04-23 20:47Z | ~13 (pre-ADR-0020 at 3-4h cadence; 1 at 20:34Z on 04-21; this one) |
| k8s-3 | 100.100.217.100  | 1748s (29m)      | ~2026-04-23 20:45Z | **1 — first reboot of k8s-3 in the entire investigation** |

## Timeline — 2026-04-23 20:30Z → 21:15Z

| UTC              | Event                                                                                                           | Source                          |
|------------------|-----------------------------------------------------------------------------------------------------------------|---------------------------------|
| 18:42Z           | k8s-2 re-admitted (uncordon + `PreferNoSchedule` taint), per plan 0007 Phase 4 re-admit + rotate decision       | plan 0007 Log                   |
| ~20:36Z          | cilium-operator, csi-attacher/resizer/snapshotter/provisioner, seaweedfs-volume-1 scheduled to k8s-2            | `kubectl get pods --watch`      |
| 20:33Z (T231)    | Monitoring tick: k8s-2 cilium WSS=2048 MiB, first breach of 2 GiB                                               | monitor cron `ba4b7418`         |
| 20:43:50Z (T242) | Monitoring tick: k8s-2 cilium WSS=**2334** MiB (+286 in 10m), Cache=**3224** MiB (+593 in 10m) — CRITICAL       | monitor cron `ba4b7418`         |
| ~20:45:00Z       | k8s-3 rebooted                                                                                                  | `/proc/uptime` back-calc        |
| 20:46:44Z        | k8s-1, k8s-2 peers log `dial tcp 192.168.1.99:2380: i/o timeout` — k8s-2 etcd peer went silent                  | etcd logs via Vector sink       |
| ~20:47:00Z       | k8s-2 rebooted (~16s silent gap)                                                                                | Vector sink + kernel boot       |
| 20:47:12Z        | k8s-2 kernel boot messages resume (6.18.18-talos, normal EDAC / igen6 / NVMe init, no warnings)                 | dmesg post-boot                 |
| 20:54:06Z (T243) | Monitor cron detected uptime decrease on k8s-2 → ALERT, cron deleted                                            | monitor cron `ba4b7418`         |
| 21:14Z           | Post-reboot state check — both rebooted nodes already re-accumulating cilium cgroup cache                        | manual                          |

## Signature comparison — 3 unexplained reboots so far

| # | Date                     | Node(s) | Exit | Kernel trace | cilium-cgroup spike pre-reboot | Trigger correlate                            |
|---|--------------------------|---------|------|--------------|--------------------------------|----------------------------------------------|
| 1 | ≤ 2026-04-20 (∼12 prior) | k8s-2   | —    | not captured (no sink) | not measured                  | pre-ADR-0020, cilium-agent WSS hitting 1536 Mi limit → OOMKill loop |
| 2 | 2026-04-21 20:34Z        | k8s-2   | 255  | not captured in Vector | not captured (Phase 3 activated 04-22) | unknown — ~18h after memory bump           |
| 3 | 2026-04-23 20:47Z        | k8s-2   | 255  | none in Vector         | YES — WSS 2048→2334 in 10 min, Cache +593 MiB | ~11 min after re-admission pod churn landed on k8s-2 |
| 4 | 2026-04-23 20:45Z        | k8s-3   | 255* | none         | not captured (not under close watch) | same minute as k8s-2 churn reaching steady-state |

\* exit code for k8s-3 inferred from containerStatus pattern; not directly
captured. cilium-zj724 on k8s-3 was created at 20:45:39Z (fresh pod, not
a container restart inside an existing pod — i.e., a full node reboot).

## Post-reboot cilium cgroup state (T+26-29 min, measured 21:14Z)

| Node  | cilium pod    | Pod age | anon (WSS) | file (Cache) |
|-------|---------------|---------|-----------:|-------------:|
| k8s-1 | cilium-d6rtj  | 2d18h   | (very high — see note below) | (very high — see note below) |
| k8s-2 | cilium-22f9m  | 2d18h (pod persists, agent container restarted) | 2042 MiB | 2828 MiB |
| k8s-3 | cilium-zj724  | 29m (fresh pod) | 2391 MiB | 2442 MiB |

k8s-1's cgroup readout was anomalously high (> 7 GiB anon, > 20 GiB
file) at 21:14Z. Two possible explanations worth checking before
drawing conclusions: (a) on long-uptime k8s-1 the memory.stat inside
the container reflects accumulated state that would otherwise have been
reset by a reboot; or (b) some reading-path quirk with the agent-container
cgroup view on this pod. Needs a cross-check against Prometheus
`container_memory_working_set_bytes{container="cilium-agent"}` before
being interpreted as a hardware-level fact.

What IS clear: on the two just-rebooted nodes, the anomaly is present
within 30 minutes of a fresh boot, and on k8s-3 the cache is climbing
fast from zero — **the restart-cycle page-cache-accumulation mechanism
from `evidence-2026-04-21-cilium-memory-rca.md` is alive under a new
load profile (re-admission pod churn on k8s-2 + whatever propagated to
k8s-3 via cilium control plane).**

## What we do and don't have from the Vector sink

Captured:
- Full service-log stream from k8s-2 up to 20:46:44Z (then silence)
- Full service-log stream from k8s-1, k8s-3 continuously
- etcd peer timeouts from k8s-1 and k8s-3 observing k8s-2 drop off
- Post-reboot boot sequence from k8s-2 (clean cold boot at 20:47:12Z)

NOT captured, all three reasons structural:
- Kernel panic or oops on k8s-2 or k8s-3 before the reboot (kernel
  `CONFIG_HARDLOCKUP_DETECTOR` / `CONFIG_SOFTLOCKUP_DETECTOR` absent;
  `kernel.panic_on_oops=1` is live but only fires on an explicit oops
  the kernel has already detected — pure silent CPU-wedge is invisible
  to this path)
- Kernel ring buffer from the crashed boots (no netconsole / kdump on
  Talos; kmsg is gone at reboot unless the sink was receiving it, and
  the `talos.logging.kernel` kernel cmdline is blocked by UKI immutable
  cmdline — see plan 0007 Phase 2 log 2026-04-20)
- Per-pod container_memory_* on k8s-3 leading up to the spike
  (Prometheus scrape interval is 1 min, and the monitoring cron was
  only watching k8s-2's cgroup)

## Hypothesis state after this event

| # | Hypothesis                                     | State after 04-23                                       |
|---|------------------------------------------------|---------------------------------------------------------|
| 1 | Longhorn unmount cascade                       | **Refuted** (plan 0007 Phase 1 verdict confirmed — k8s-3 wasn't Longhorn-drained and it also rebooted) |
| 2 | Single-unit hardware defect on k8s-2           | **Weakened** — k8s-3 now shares the signature; can't be a k8s-2-only chassis issue unless two nodes have concurrent defects (unlikely) |
| 3 | Kernel-config-induced silent hang               | **Alive** — Talos kernel cannot detect CPU lockups by design; the silent-gap signature (network drop → ~30s silence → clean cold boot) is exactly what this looks like |
| 4 | cilium-agent cgroup memory pressure / OOM loop | **Upgraded: primary suspect again under revised model.** Pre-reboot telemetry on k8s-2 caught the WSS+cache spike; k8s-3 was under the same pod-churn but not instrumented closely. Open question: does cilium-agent memory pressure *cause* the node reboot, or is it a symptom of whatever else is about to crash the node? |

New candidate:
- **(5) Distributed trigger on re-admission pod churn** — scheduling a
  large cohort of pods onto a node that had been idle for 24h+ may
  exercise a code path (CSI registration, Multus/whereabouts IPAM,
  seaweedfs volume registration, Longhorn engine attach) that induces
  memory pressure or a kernel-subsystem wedge across multiple nodes
  simultaneously. Two data points (04-21 20:34Z k8s-2 solo; 04-23
  20:47Z k8s-2+k8s-3 cascade) both happen during cilium-agent upward
  memory trajectories; 04-23 has the additional signature of happening
  ~11 min after the re-admission pod cohort reached steady-state.

## What to do next — recommendations (ranked)

1. **Re-cordon k8s-2 and remove the `PreferNoSchedule` taint immediately.**
   Re-admission is the only variable we changed between "stable for
   45h+" and "two-node reboot cascade," so the cheapest information-preserving
   rollback is to revert that variable while we think. Cost: capacity
   on k8s-2 re-lost. Value: restores the state that gave us 45h of
   clean uptime.
2. **Instrument k8s-3 the same way k8s-2 was being watched.** Existing
   monitoring only polled cilium cgroup on k8s-2. If the mechanism is
   cluster-wide we must poll all three. The Vector sink already has all
   three node streams; add a Prometheus recording rule (or a simple
   `watch` loop in the operator shell) that checks `anon` and `file`
   cgroup stats on all three cilium-agent containers every 1-2 minutes.
3. **Open successor plan 0008 (or whatever number is next) covering:**
   - Supersede ADR 0020 to raise cilium-agent memory limit to 3072 MiB
     or 3584 MiB (revised based on the post-reboot re-accumulation rate
     observed on k8s-3)
   - OR move cilium-agent out of the cgroup-limited container and into
     a host-level systemd service (breaks the feedback loop entirely
     but bigger change)
   - Add a deliberately-triggered re-admission test: drain k8s-2 fully,
     then re-schedule a known cohort onto it, measure what happens to
     all three nodes. Do this only after root cause is understood.
4. **Keep the Vector sink active and rotating.** The rotation CronJob
   landed today; without it the PVC would have filled in 11 days. The
   sink gave us the etcd-peer timeout + kernel-boot signature we have
   on this event — it is earning its keep and should stay up until the
   next plan's Phase 5 teardown.
5. **Do NOT remove plan 0007 Phase 5 from scope.** The teardown steps
   still apply eventually, but they are premature now — acceptance
   criterion #1 ("root cause is localized") is not met.
6. **Reconsider the ADR 0020 durable-fix claim** in the durability log.
   It was written after 45h+ of stability; the two-node cascade shows
   the memory bump *extended* stability but did not eliminate the
   failure mode. Add a correction note to ADR 0020.
