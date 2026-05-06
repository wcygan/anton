# Evidence: cpufreq config is uniform-default; ACPI SCI/GPE counters are zero — no SMI storm, no cpufreq asymmetry

**Date:** 2026-05-06 (loop iteration #10, opus 4.7)
**Source:** `talosctl read /sys/devices/system/cpu/cpu0/cpufreq/*`, `/sys/firmware/acpi/interrupts/*`, `/sys/class/thermal/thermal_zone0/*`.
**Status:** Diminishing-returns iteration. Three more rule-outs, one minor configuration note. No new candidate hypothesis.

## What's clean

### cpufreq state — uniform across all three nodes

```
scaling_driver                = intel_pstate
scaling_governor              = powersave
energy_performance_preference = balance_performance
scaling_min_freq              = 400 MHz
scaling_max_freq              = 5200 MHz
scaling_cur_freq              = ~480-530 MHz (idle)
intel_pstate/no_turbo         = 0
intel_pstate/status           = active
```

**Everything is at Linux defaults.** No node has an aberrant frequency cap, no node is missing intel_pstate, no node has turbo disabled. The min frequency (400 MHz) and EPP (`balance_performance`) are the standard defaults that the kernel ships when intel_pstate takes ownership.

**Worth flagging:** `energy_performance_preference = balance_performance` allows the CPU to enter deep C-states aggressively. Setting it to `performance` (via runtime write to each cpu's `energy_performance_preference` file) would *reduce* the depth of idle states the CPU prefers, but **PM-QoS via `/dev/cpu_dma_latency` already overrides EPP** — once a 0-µs latency tolerance is registered, EPP becomes effectively moot for idle-state selection. So this is a redundant lever, not an additional one. Iter #3's DaemonSet remains the right knob.

### ACPI SCI / SMI activity — zero across all nodes

```
acpi/sci      = 0
acpi/error    = 0
acpi/gpe_all  = 0
```

System Control Interrupts and ACPI General-Purpose Events are not firing in measurable counts. SMI storms (where BIOS-level SMM handlers freeze the kernel for tens of milliseconds at a time) typically show up as elevated `sci` or per-GPE counters — not the case here.

This rules out **SMI-induced silent stalls** as a contributor. Some Raptor Lake systems with buggy BIOS SMI handlers see kernel pauses of 10-50 ms during routine SMI servicing; persistent SMI storms can cause kubelet/etcd timeouts that look like silent failures. Not happening here.

### Thermal trip points — uniform and reasonable

```
trip0: critical     @ 105°C   (i9-13900H Tjmax ≈ 100°C)
trip1: active       @ 100°C
trip2..5: active    @ 55, 50, 45, 40°C (fan ramp curves)
```

Identical on every node. The critical-throttle threshold is 105°C, well above the 64-69°C peaks measured in iter #7. No node has a custom thermal envelope.

## What's left to ask

After 10 iterations, the surviving hypothesis stack and recommended landings haven't changed since iter #8. The remaining open questions are operational, not analytical:

1. **Will the iter #3 / #5 / #6 / #8 three-landings PR actually be applied?** The investigation has identified the changes; nothing has landed.
2. **Will those landings reduce silent-reboot frequency in the watch window?** Open until empirically validated.
3. **Is there a non-trivial NVMe / DDR5 / firmware-side issue that would only show up under DIMM-swap or a custom Talos kernel build?** Possible but high-effort to test, and the case for testing is weak after iter #7+#9's clean rule-outs.

## Honest summary

This iteration looked, found nothing actionable beyond what was already known. **The investigation has reached a credible convergence point.** Continuing to iterate at a 10-minute cadence will mostly produce more rule-outs of progressively less likely mechanisms, not new hypotheses.

The recommended action is to **stop generating fresh angles and start landing the recommendations** — specifically the three changes from iter #5 + #6 + #8:

1. `SysctlConfig` patch with the three NMI-panic sysctls
2. `WatchdogTimerConfig` feeding `/dev/watchdog0` at 5m
3. PM-QoS / ASPM / NVMe-APST DaemonSet

These would land in a single small PR (two Talos config files + one Flux app folder), are reversible (`talosctl apply` rollback + `kubectl delete ds`), and **directly address all three surviving candidate hypotheses** (Vmin/C8, i226-V/ASPM, iTCO-unfed).

After they land, the watch window starts. If silent reboots continue, the hypothesis space re-opens (DIMM, custom kernel, BIOS deeper investigation). If they stop, plan 0013 reaches terminal state (a) — localized fix.

## Cross-references

- `evidence-2026-05-06-c-states-active.md` (iter #6)
- `evidence-2026-05-06-itco-unfed-and-nmi-panic-sysctls.md` (iter #5)
- `evidence-2026-05-06-i226-v-irq-dominance.md` (iter #8)
- `evidence-2026-05-06-kernel-args-not-applied.md` (iter #3)
- Plan 0013 — single PR closes acceptance criteria 1 + advances toward terminal state (a)
