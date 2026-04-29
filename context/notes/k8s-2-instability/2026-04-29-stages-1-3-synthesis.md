# 2026-04-29 — Synthesis after Stages 1-3, with next steps

After completing the three in-OS diagnostic stages (Stage 1 — 8 GiB
memtester / Stage 2 — 32 GiB memtester / Stage 3 — multicore stress-ng) on
k8s-2 and observing ~14 h of post-Stage-3 idle/smoke load, this note
consolidates what's been learned, how the line-143 hypothesis ranking has
moved, and what's worth trying next. It is the bridge document between the
three per-stage evidence notes and whatever happens at the
operator-access window (~2026-05-04 per plan 0009 Phase 5).

Sister notes this synthesizes:

- [`evidence-2026-04-29-memtester-stage2.md`](evidence-2026-04-29-memtester-stage2.md) — Stage 2 (32 GiB locked, 92 min, clean)
- [`evidence-2026-04-29-stress-stage3.md`](evidence-2026-04-29-stress-stage3.md) — Stage 3 (20 cpu + 8 vm, 90 min, clean)
- [`evidence-2026-04-28-plan0010-four-agent-synthesis.md`](evidence-2026-04-28-plan0010-four-agent-synthesis.md) — multi-agent synthesis whose hypothesis #1 the in-OS stages were designed to test
- [`evidence-2026-04-28-plan0010-stage-a-abort.md`](evidence-2026-04-28-plan0010-stage-a-abort.md) — the 6-reboot post-Stage-A timeline (mean inter-reboot 10.5 h) that motivated the in-OS escalation

## Three findings stack up

### 1. The reboot mode is below the kernel-logging horizon by construction

Stage 3 ran the chip flat-out for 90 min and emitted **zero** kernel fault
precursors on k8s-2: no panic, no oops, no `BUG:`, no MCE, no EDAC counter,
no thermal throttle message, no soft-lockup, no RCU stall, no hung-task
warning, no NMI watchdog, no machine-check exception. The Vector kernel
sink received 4198 records from k8s-2 today across both TCP and UDP paths;
the only "anomalies" matching the broad regex are the pre-existing
cosmetic Talos `KernelParamSpecController` retry loops (KSPP override warns
plus the `printk_devkmsg: invalid argument` controller noise documented
in plan 0009 Log entries 2026-04-28). Both pre-date Stage 3 and are unrelated
to the silent-reboot mode.

This matches what the multi-agent synthesis already found across 5 of 6
prior reboots: zero pre-reboot last words. We can now state it more strongly:
**this kernel does not produce fault signatures from userland-driven stress
even at maximum load**. There is no in-OS kernel-fault path to catch.

### 2. The userland-reachable trigger surface is exhausted

Stages 1, 2, and 3 collectively cover:

| axis                                | covered by         | result   |
|-------------------------------------|--------------------|----------|
| DRAM capacity (mlock'd)             | Stage 2 (32 GiB)   | clean    |
| DRAM bandwidth                      | Stage 3 (vm × 8)   | clean    |
| Page-allocator pressure             | Stage 2 + 3        | clean    |
| Cache coherency / interconnect      | Stage 3 (matrixprod × 20) | clean    |
| Multi-core thermal envelope (powersave) | Stage 3 (~70% pin × 20 cores × 90 min) | clean |
| Combined CPU + memory + bandwidth   | Stage 3            | clean    |

The "load-pressure on RAM/CPU/cache/bandwidth from userspace" hypothesis
subspace is closed. To keep #1 alive we have to commit to one of: firmware /
POST / DIMM-training-time faults (out of reach from in-OS), max-power thermal
events (powersave governor caps the achievable thermal load — a `performance`
governor delta of ~10-15°C remains), cold-boot transients (out of reach from
a running OS), or non-load-gated intermittent glitches.

### 3. The 19.6 h post-reboot uptime is *not yet* significant

Inter-reboot mean across the 6 post-Stage-A events was 10.5 h. We are at
~1.87× MTBF — in the right tail but not unusually so for N=6. Do not read
"Stage 2/3 fixed it" into this stretch. Threshold for unusual:

| uptime since 04-28T21:41Z | quantile-style read on the prior 6-reboot distribution      |
|---------------------------|-------------------------------------------------------------|
| 19.6 h (now)              | 1.87× MTBF — tail but unremarkable                         |
| 30 h                      | 2.86× MTBF — uncommon, weakly suggests a regime change     |
| 40 h                      | 3.81× MTBF — strongly suggests something changed           |
| 60 h                      | 5.7× MTBF — distribution materially different              |

The "something changed" candidates if we cross those thresholds: cordon
posture stable, smoke pods unchanged from before Stage 3, no new Talos /
Cilium / kernel rollout — there is no obvious independent variable in the
last 24 h apart from "we ran Stage 1 + 2 + 3". A long stretch from here
would be confusing more than confirming.

## Hypothesis ranking — deltas vs line 143

| rank | hypothesis                                              | post-Stage-3 movement                                                                                                                                           |
|------|---------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| 1    | single-unit k8s-2 hardware defect (DDR5 + BIOS hook)    | **rank unchanged, absolute confidence narrowed.** The "load/thermal-gated under achievable userspace load" subspace is gone. Remaining: firmware/POST/DIMM-training, performance-governor max-power thermals, cold-boot transients, intermittent. Stage 4 is the decisive test for the largest remaining subspace. |
| 2    | kernel silent-hang exposed by environmental stimulus    | **moderately weakened.** ~3 h cumulative max userland load did not perturb the kernel. If a stimulus exists, it is not CPU/memory/cache/bandwidth pressure.                                                                                          |
| 3    | kube-apiserver memory pressure                          | **mildly stronger relative to others** by elimination. `K8s2ApiserverWatchEventBurst` is firing right now (since boot+5.5min on 04-28T21:41Z) — a known post-reboot watch-cache rebuild but a real elevated stress signal we have never directly tested.                       |
| 4    | CNI OOM / pod-admission cascade                         | **further weakened.** Zero CNI restarts on k8s-2 across the entire 19.6 h uptime including peak Stage 3 contention. cilium-agent WSS plateaus at ~796 MiB (22% of the 3584 MiB ADR-0022 limit). Could arguably drop off the active list.                       |

## Tests worth running, by signal-per-cost

| ID  | test                                                                                                       | cost                                            | signal                                                                                                                                                         |
|-----|------------------------------------------------------------------------------------------------------------|-------------------------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| A   | Stage 4: boot-time memtest86+ + DIMM swap with k8s-3                                                       | gated on operator-access window (~2026-05-04)   | **decisive** — only test that reaches firmware/POST/DIMM-training; promotes or refutes hypothesis #1's last unfalsified subspace                              |
| B   | Netconsole pipeline validation via deliberate `sysrq c` panic on k8s-2                                     | one deliberate reboot of an already-cordoned node | **high** — proves the Vector UDP path actually captures a panic. Right now we are *betting* it works for the next real event; without B we may walk into Stage 4 with the same "TCP cliff at boot−35s, then nothing" gap |
| C   | Long-duration moderate stress (`--cpu 4 --vm 2 --vm-bytes 2G` + light kernel-syscall stressors, 4 h)        | one window of 4-12 h                            | **medium-high** — directly tests "trigger needs cumulative time at moderate load", the regime Stage A's 10.5 h MTBF hints at. Stages 1-3 maxed magnitude, this trades magnitude for duration                       |
| D   | Kernel-syscall-path stress (`--vfork`, `--switch`, `--mmap`, `--brk`, ~60 min)                             | low — same scaffold as Stage 3                  | **medium** — exercises kernel paths Stage 3's arithmetic/bandwidth focus did not reach. Complementary, not redundant                                          |
| E   | Storage-fabric stress (Longhorn replica pinned to k8s-2 + `dd` write loop + iperf3 over storage VXLAN)     | medium — needs cordon carve-out                 | **medium** — exercises NVMe controller, NIC firmware, storage VXLAN. Hypothesis-1-adjacent. But contradicts current cordon strategy                           |
| F   | Stage 3.1: `performance`-governor re-run                                                                   | medium — privileged pod or Talos KernelParam    | **low** — diagnostically marginal vs Stage 3, governor ceiling delta is small                                                                                  |

## Recommended sequence

A reasonable order, from highest signal-per-cost first:

1. **Stage 3.5 (Test C)** — long-duration moderate stress, 4 h. Probes the
   only userland-reachable axis Stages 1-3 did not: cumulative time at
   sub-max load. Fits AFK windows. **First action of this turn (4 h
   operator-AFK window).**
2. **Test B** — controlled `sysrq c` netconsole pipeline validation on the
   cordoned k8s-2. One deliberate reboot, validates we will actually catch
   the next real event. Pair with operator-attended supervision to confirm
   UDP path delivers pre-panic last words.
3. **Stage 4 (Test A)** — physical-access window. Decisive. Gated on
   ~2026-05-04. Includes BIOS posture normalization (1.22 → 1.27),
   memtest86+ ≥4 passes, optional DIMM swap with k8s-3.
4. **Tests D/E/F** — only if 1-3 leave open questions.

## Active monitoring posture during this AFK window

A 4 h continuous-stress probe (Stage 3.5) is launching this turn with a
15-min cron monitoring loop. Stop conditions on the loop:

- **Reboot detected** (bootID changes OR `last_over_time(node_boot_time_seconds[30m])` advances past `1777412482`) → CronDelete, alert, capture pod state + last 30 stress-ng log lines + cluster events + Vector kernel-sink window before/after the reboot, prepare a fresh evidence note. **Do not commit auto-summary; the reboot framing is too important to ship without operator review.**
- **Job succeeded** → write a Stage 3.5 evidence note mirroring the Stage 3 structure, plan log entry, commit, push, CronDelete.
- **Job failed** (`OOMKilled` / `activeDeadlineExceeded` / stress-ng error) → report failure reason, do not commit, CronDelete.

This synthesis will be the canonical "where we are" doc when the operator
returns from the AFK window. If a reboot fires during the 4 h, the next
note will supersede this one's recommended sequence (because B's value
goes way up if our pre-reboot capture is empty *again*, or way down if it
finally has data).

## Cross-references

- plan 0009, Log entries 2026-04-28 (Stage 1, R7, review hardening, UDP kmsg, plan-0010 abort) and 2026-04-29 (Stage 2, Stage 3)
- [`README.md`](README.md) — current-status block at the top reflects the pre-Stage-2 picture; due for an update once Stage 4 lands or the AFK probe completes
