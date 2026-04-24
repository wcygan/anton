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

---

## Addendum — 2026-04-24 measurement-source correction

**The "cilium cgroup" numbers in this file are node-level, not cilium-specific.**

The pre-reboot and post-reboot figures throughout this document (e.g.
"k8s-2 WSS 2048→2334 MiB in 10 min, Cache +593 MiB"; the post-reboot
table showing k8s-2 WSS=2042 / Cache=2828 and k8s-3 WSS=2391 /
Cache=2442) were gathered by the session `/loop` monitor via:

```
kubectl exec <cilium-agent-pod> -- cat /sys/fs/cgroup/memory.stat
```

Cilium bind-mounts `/sys/fs/cgroup` from the host for BPF and cgroup
operations, so reads against `/sys/fs/cgroup/memory.stat` inside
`cilium-agent` return the **host root cgroup stats, not cilium's
container cgroup**. Confirmed 2026-04-24 14:24Z by observing
`/proc/self/cgroup` return `0::/` and `memory.max` being absent at
that path.

Container-scoped measurements at 2026-04-24 14:24Z (uncorrupted source
— `kubectl top pod -n kube-system -l k8s-app=cilium --containers`,
which reads through metrics-server from the container's own cgroup on
the host):

| Node  | cilium-agent actual memory | % of 3584 Mi limit |
|-------|----------------------------|--------------------|
| k8s-1 | **213 MiB**                | 6 %                |
| k8s-2 | **174 MiB**                | 5 %                |
| k8s-3 | **172 MiB**                | 5 %                |

### What changes about the 04-23 analysis

1. The "pre-reboot cilium WSS+cache spike on k8s-2" was a node-level
   memory rise during pod churn (cilium-operator + 4 CSI pods +
   seaweedfs-volume-1 landing at ~20:36Z; reboot at 20:47Z). 2334 MiB
   anon on a 96 GB node is 2.4% utilization — not memory pressure.
2. The cilium `/proc/.../memory.stat`-based oscillation band "1640-1894
   MiB over 33h" captured by the 2026-04-22 monitoring run was also
   node-level. Treat it as a node-level baseline, not a cilium
   runtime-state signal.
3. **The pod-churn ↔ reboot correlation is still real** — node anon
   memory *did* rise +500 MiB in 10 min and two nodes *did* reboot —
   but the correlation is mediated by **something else the pod churn
   triggered** (CSI registration, Multus/whereabouts IPAM, Longhorn
   engine attach, seaweedfs volume registration, kernel subsystem
   load), not by cilium cgroup pressure.
4. The cilium/cilium #42007 upstream bug (near-limit + churn → BPF
   entry corruption) remains a real upstream issue. ADR 0021 is a
   sensible preventive measure on its own merit, but we do **not**
   have evidence it was the 04-23 trigger. If Phase 4's controlled
   re-admission experiment repeats the cascade with cilium cgroup
   memory flat, #42007 is falsified as the 04-23 mechanism.
5. ADR 0020 stands — the 04-20 cilium-agent exit-137 OOMKill on the
   old 1536 Mi limit was measured via Prometheus `container_memory_*`
   (container-scoped), which is correct. That OOM loop was real and
   the 1536 → 2560 Mi bump did close it.

### What to do with this document

Keep the body as-is for historical fidelity. **Treat every "WSS=" and
"Cache=" figure above as node-level unless explicitly labelled
`container_memory_*` from Prometheus.** Re-do future monitoring via
Prometheus container-scoped metrics or `kubectl top pod --containers`.

### Monitoring approach going forward

Phase 3 of plan 0009 (PrometheusRule + Grafana panel) already uses
`container_memory_working_set_bytes{container="cilium-agent"}`, which
is correct. No change needed there. For ad-hoc inspection, use
`kubectl top pod -n kube-system -l k8s-app=cilium --containers`.
The in-container `memory.stat` method is forbidden for cilium
specifically, and suspect for any DaemonSet that bind-mounts
`/sys/fs/cgroup` from the host (almost all CNI agents, node-exporter,
kubelet-adjacent pods).

---

## Addendum #2 — 2026-04-24 (later) cascade framing retracted

**The two-node cascade described in this document did not happen.**
Peer-agent review on 2026-04-24 verified plan 0006 Log line 115:

> 2026-04-23: Controlled-reboot acceptance test — passed. [...] Reboot
> issued via `talosctl -e 100.100.217.100 -n 100.100.217.100 reboot`
> at 20:44:37Z; k8s-3 back to Ready,SchedulingDisabled by 20:49:42Z.

**k8s-3's 20:45Z reboot was an operator-initiated Harbor controlled-
reboot acceptance test under plan 0006, not a silent crash.**
This investigation's monitor detected it as "uptime decrease" but
had no way to distinguish intentional reboots from silent ones,
so the original incident report treated them as a cascade.

### What actually happened on 2026-04-23

- 20:35:41Z — operator cordoned k8s-3 for Harbor drain test (plan 0006)
- 20:35:57Z — drain started; Harbor pods rescheduled onto k8s-1 and k8s-2
- ~20:36:18-41:00Z — Multus OOMKilled 4× on k8s-1 under pod-creation
  burst (documented in plan 0006 Log, NOT this document's body)
- 20:37:50Z — CNPG promoted `harbor-postgres-2`; former primary
  `harbor-postgres-1` accepted by k8s-2 as last-resort placement
  despite the `PreferNoSchedule` taint (soft)
- 20:44:37Z — operator issued `talosctl reboot` against k8s-3
- 20:45Z — k8s-3 kernel boot (normal reboot, ~5 min total)
- **20:47Z — k8s-2 silent reboot (exit 255) — THIS is the only
  unexplained event on 2026-04-23**
- 20:49:42Z — k8s-3 back Ready per the operator's plan 0006 monitoring
- 20:52:01Z — operator uncordoned k8s-3

### What this changes

1. **k8s-3 has never silently rebooted during the investigation.**
   The "k8s-3 is now involved, single-unit hardware defect weakened"
   conclusion in the body of this document is void. Hardware defect
   hypothesis stays live.
2. **Total silent-reboot count is 2, not 3**: 2026-04-21 20:34Z and
   2026-04-23 20:47Z. Both on k8s-2. Both unexplained.
3. **Pre-reboot memory trajectory on k8s-2 was dominated by
   kube-apiserver, not the re-admission cohort.** Peer review of
   Prometheus `topk(10, sum by (pod,container) (container_memory_
   working_set_bytes{node="k8s-2"}))` shows kube-apiserver WSS rose
   from ~1.70 GiB at 20:30Z to ~2.65 GiB at 20:46Z (+950 MiB). The
   re-admission cohort (cilium-operator + CSI + harbor-postgres-1)
   contributed only ~500-600 MiB aggregate. The mechanism that drove
   kube-apiserver's +950 MiB growth is a new, untested thread — could
   be list-watch storm from the Harbor drain, audit log volume, or
   an etcd-interaction effect.
4. **BIOS split k8s-1 (1.26) vs k8s-2/k8s-3 (1.22) is confirmed** but
   **runtime microcode is identical on all three nodes (0x00006134)**,
   so the specific "Intel 0x12B Vmin-shift mitigation is present on
   k8s-1 but not k8s-2/k8s-3" claim is wrong. The BIOS version
   difference may still matter (C-state defaults, IRQ routing, power
   management firmware) but not via microcode content. Phase 5 BIOS
   flash still reasonable as generic firmware-currency hardening.

### What the body of this document still gets right

- The silent-reboot signature on k8s-2 (exit 255, ~30s network silence
  via etcd peer timeouts, clean cold boot with no kernel trace) is
  accurate and this is the primary feature to watch for in future
  events
- Phase 1 netconsole activation is still the right diagnostic for the
  next silent event
- Kernel-config-induced silent hang (hypothesis #2) is still live and
  now relatively stronger by elimination

### What this document's body gets wrong (do NOT act on these)

- "Two-node cascade" framing (everywhere)
- "k8s-3 first, then k8s-2" timeline — k8s-3 was intentional
- "single-unit hardware defect weakened by k8s-3 involvement" —
  hardware defect re-strengthened by k8s-3 NOT being involved
- Cilium/Multus WSS figures measured via in-container `memory.stat`
  (already corrected in Addendum #1 above)
- The "strongest recommendation: netconsole + 3584 Mi cilium + BIOS
  flash" — netconsole and BIOS flash still reasonable; 3584 Mi cilium
  bump (ADR 0021) was deployed but not demonstrated as the 04-23 fix

Plan 0009 and the README hypothesis ranking are being updated in the
same pass that produced this addendum.
