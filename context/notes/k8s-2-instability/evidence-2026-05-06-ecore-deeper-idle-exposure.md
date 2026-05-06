# Evidence: TSC clocksource stable; E-cores spend ~1.5× more time in C8 than P-cores — Vmin exposure is hybrid-asymmetric

**Date:** 2026-05-06 (loop iteration #14, opus 4.7)
**Source:** `talosctl read /sys/devices/system/clocksource/clocksource0/*` and per-CPU `/sys/devices/system/cpu/cpu{0,6,13,19}/cpuidle/state*/{name,desc,usage,time}` per node.
**Status:** One rule-out (TSC stable, not a Vmin-induced clock drift) + one structural finding (E-core deep-idle dominance) that adds nuance to the iter #6/#7 Vmin reading.

## Finding 1 — TSC clocksource is stable

```
current_clocksource    = tsc           (on all three nodes)
available_clocksource  = tsc acpi_pm   (TSC + ACPI PM as fallback)
```

`dmesg | grep -iE 'tsc|clocksource|clockevents|timekeeping'` returns **zero matches** on every node. No TSC instability events. The kernel has not switched to `acpi_pm` fallback at runtime, no timekeeping warnings, no clocksource-watchdog complaints.

**Rules out:** TSC drift / non-invariance under deep C-state entry as a contributor. Some Raptor Lake CPUs have shipped with TSC instability under deep idle (a documented Vmin-adjacent quirk that produces clock skew → kubelet → apiserver heartbeat misses → cascade). Not happening here. The TSC remains invariant across C8 entry/exit on these specific CPUs.

This is a small additional reassurance for the iter #3 / #6 PM-QoS DaemonSet plan — capping C-states at C0/C1 won't break TSC behavior because TSC is already invariant. (The reverse — if TSC were unstable — would have meant capping C-states is *necessary* not just helpful.)

## Finding 2 — E-cores spend ~1.5× more time in C8 than P-cores

Per-CPU `state3` (C8 / MWAIT 0x60) cumulative time, normalized by uptime, for representative P-core (cpu0, cpu6) and E-core (cpu13, cpu19) samples:

| Node | uptime | cpu0 (P-core) C8 time | cpu6 (P-core) C8 time | cpu13 (E-core) C8 time | cpu19 (E-core) C8 time |
|---|---|---|---|---|---|
| k8s-1 | 7.7 h | 35% | 23% | **49%** | **63%** |
| k8s-2 | 50.4 h | 29% | 32% | **49%** | **54%** |
| k8s-3 | 9.1 h | 10% | 20% | **35%** | **40%** |

**E-cores are in C8 (the Vmin failure surface) about 1.5× longer than P-cores** on every node. Pattern is consistent across all three.

### Why this happens

The i9-13900H is a hybrid CPU (Gracemont E-cores + Golden Cove P-cores). Linux's CFS scheduler with EAS (Energy Aware Scheduling) is **biased toward loading P-cores first** when work arrives, leaving E-cores idle longer. Combined with `energy_performance_preference = balance_performance` (iter #10), the scheduler aggressively keeps E-cores in deep idle to save power.

### Why this matters for Vmin

The Vmin shift literature is dominated by desktop Raptor Lake reports — i9-13900K, i9-14900K — where the failure mode is on **P-cores** (Golden Cove cores, the ones in their high-power high-Vmin envelope). Mobile Raptor Lake i9-13900H has **both architectures**. The E-cores (Gracemont) have a different VR rail, a different process node corner, and a different Vmin envelope. Whether they're equally susceptible to Vmin shift is **not well-documented** — Intel's official "mobile not affected" position predates community testing on hybrid mobile chips.

**But this measurement establishes that the E-core exposure is dominant.** Whichever Vmin behavior the silicon has, the E-cores are in the failure window 1.5× more often than the P-cores. If E-cores are *more* susceptible (because Gracemont is a smaller / newer process node corner), this is a multiplicative concern. If E-cores are *less* susceptible, the cluster-wide failure rate is dominated by the P-core minority. We can't tell which without controlled probing.

### Implication for the recommendation stack

The iter #3 / iter #6 PM-QoS DaemonSet (`/dev/cpu_dma_latency = 0`) **caps C-states on every CPU regardless of core type** — both P-cores and E-cores held at C0/C1. So the existing recommendation correctly addresses both populations. **No change to the recommendation stack.**

**However**, this measurement opens a more targeted alternative if the cluster-wide PM-QoS approach has unacceptable power-consumption side effects:

- **Per-core-type EPP override:** Linux's hybrid-aware `intel_pstate` driver supports separate EPP settings for P-cores and E-cores via `/sys/devices/system/cpu/cpu*/cpufreq/energy_performance_preference`. Setting **only E-cores** to `performance` (which limits idle depth) while leaving P-cores at `balance_performance` would reduce E-core deep-idle exposure specifically while still allowing P-cores to deep-idle for power savings.

This is a smaller hammer than `/dev/cpu_dma_latency = 0` which prevents *all* C-state entry past C1. If the hypothesis holds, **EPP=performance on E-cores only might be sufficient** — a useful fallback if the cluster-wide PM-QoS approach causes thermal or power problems.

Trade-off ranking, smallest hammer first:

1. **EPP=performance on E-cores only** (~8 cores affected, 1.5× exposure reduction on the worst-affected core type, P-core power saving preserved)
2. **EPP=performance cluster-wide** (all cores, somewhat broader)
3. **`/dev/cpu_dma_latency = 0`** (caps C-states at C0/C1 regardless of EPP — strongest hammer)

If empirically (1) or (2) prevents silent reboots, prefer (1) for power efficiency. If neither is sufficient, escalate to (3).

The iter #3 plan was to start at (3). This iter suggests (1) is worth trying first, with (3) as the fallback. The DaemonSet manifest is essentially the same regardless — just a different write per CPU.

## What this iter does not change

- The cumulative recommendation stack from iter #5 + #6 + #8 still holds. Sysctls (`panic_on_*_nmi=1`) and watchdog feed (`WatchdogTimerConfig`) are unaffected.
- The Vmin/C-state hypothesis itself is unchanged — refined toward E-core dominance, not falsified.
- Workload placement asymmetry from iter #12 (k8s-2 hosts the observability stack) is still the dominant explanation for k8s-2's historical reboot bias.

## Honest assessment of iter #14

This is a **structural refinement** of iter #6, not a new candidate hypothesis. It's worth recording because:

1. It identifies which core type carries the dominant exposure (E-cores)
2. It opens a smaller-hammer mitigation option (per-core-type EPP)
3. It rules out one specific Raptor Lake quirk (TSC drift) by direct measurement

But it does not change the recommended next action — **land the iter #5/#6/#8 PR; the empirical signal from a watch window is more informative than further analytical iterations**.

## Verification trail

```
$ for n in k8s-1 k8s-2 k8s-3; do
    echo === $n ===
    talosctl --endpoints $n -n $n read /sys/devices/system/clocksource/clocksource0/current_clocksource
    talosctl --endpoints $n -n $n read /sys/devices/system/clocksource/clocksource0/available_clocksource
  done
tsc
tsc acpi_pm
... (same on all three)

$ for n in k8s-1 k8s-2 k8s-3; do
    for cpu in 0 6 13 19; do
      for i in 1 2 3; do
        talosctl --endpoints $n -n $n read /sys/devices/system/cpu/cpu$cpu/cpuidle/state$i/{name,usage,time}
      done
    done
  done
```

(Aggregated values in the table above; raw values in conversation context.)

## Cross-references

- `evidence-2026-05-06-c-states-active.md` (iter #6) — measured C8 entry rate on cpu0 only; iter #14 extends to E-cores and reveals the asymmetry
- `evidence-2026-05-06-cpufreq-and-smi-clean.md` (iter #10) — noted EPP = balance_performance and called it redundant with PM-QoS; iter #14 reverses this somewhat: per-core-type EPP is a smaller-hammer alternative worth trying before PM-QoS
- `evidence-2026-05-06-kernel-args-not-applied.md` (iter #3) — DaemonSet remains the right mitigation; iter #14 suggests it could be done with EPP writes instead of (or in addition to) PM-QoS
- Plan 0013 — small refinement to the eventual mitigation manifest, no plan-level change
