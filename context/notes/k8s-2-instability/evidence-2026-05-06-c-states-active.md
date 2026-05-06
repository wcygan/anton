# Evidence: C6 deep-sleep is in heavy use on all three nodes; intel_idle uses ACPI fallback (BIOS-driven C-state selection)

**Date:** 2026-05-06 (loop iteration #6, opus 4.7)
**Source:** `talosctl read /sys/devices/system/cpu/cpu0/cpuidle/state{0..3}/{name,desc,usage,time,disable}` and `/sys/devices/system/cpu/cpuidle/{current_driver,current_governor}` on all three nodes.
**Status:** Direct measurement of the Vmin failure surface in active use. Reinforces iter #3's PM-QoS DaemonSet recommendation; adds nuance about why `intel_idle.max_cstate=1` would not have been the right kernel param.

## Direct measurement of cpuidle state usage

Per-node, on `cpu0` (representative; full per-CPU numbers will scale roughly with thread count):

| Node | uptime | state1 C1_ACPI usage / time | state2 C2_ACPI usage / time | **state3 C3_ACPI (MWAIT 0x60 = Intel C6) usage / time** |
|---|---|---|---|---|
| k8s-1 | 7.7 h | 22.1M / 1.18 h | 12.9M / 3.78 h | **3.93M / 2.37 h (31% of uptime)** |
| k8s-2 | 50.4 h | 146.6M / 7.47 h | 91.1M / 24.1 h | **26.5M / 14.7 h (29% of uptime)** |
| k8s-3 | 9.1 h | 34.9M / 1.85 h | 22.5M / 5.53 h | **1.79M / 0.84 h (9% of uptime)** |

Driver + governor on every node: `intel_idle` driver, `menu` governor. No state has `disable=1`.

## Why the `_ACPI` suffix matters

The state names are `C1_ACPI` / `C2_ACPI` / `C3_ACPI`, not `C1` / `C1E` / `C6` / `C8` / `C10` (the names `intel_idle` uses when it has a native MSR table for the running CPU model). The `_ACPI` suffix specifically indicates **`intel_idle` is using ACPI fallback** — it could not find the running CPU model (RaptorLake-P, family 6, model 186 = 0xBA) in its native state table, so it deferred to BIOS-provided `_CST` tables.

Implication: **BIOS-supplied ACPI `_CST` entries are driving C-state selection**, not Linux's optimized native state definitions. The same BIOS that this investigation has been flashing (1.22 → 1.27) is the source of these C-state hints. This is a real but subtle confound — every BIOS-version change in the investigation was changing the actual idle behavior, not just the microcode/firmware.

A relevant secondary effect: the kernel parameter `intel_idle.max_cstate=N` recommended by `evidence-2026-04-30-web-research.md` **would not be the right knob here**. `intel_idle.max_cstate` only works when `intel_idle` is using its native state table; in ACPI-fallback mode, the equivalent knob is `processor.max_cstate=N` (which the same web-research note also recommended — both should be set together).

## What the MWAIT hint 0x60 actually does on Raptor Lake-P

The hint values in `desc` (`MWAIT 0x0`, `MWAIT 0x21`, `MWAIT 0x60`) are sub-state codes passed to the `MWAIT` instruction. Per Intel's MWAIT extension documentation for Sandy Bridge through Raptor Lake:

| Hint | Sub-state | Description |
|---|---|---|
| `0x00` | C1 | HALT — clock gated, voltage retained |
| `0x10` | C1E | Enhanced HALT — clock gated, voltage reduced |
| `0x20` | C3 | Core deep sleep — caches flushed, voltage reduced more |
| `0x30` | C6 | Core power-gated — full state save, **VR drops to Vmin** |
| `0x40` | C7 | Package C7 (LLC flushed) |
| **`0x60`** | **C8 / package C8** | **Voltage to C-state minimum across package** |

Hint `0x60` is **deeper than C6 on Raptor Lake-P** — it engages package-level C-state which lowers voltage across the whole CPU socket. **This is the deepest C-state the platform is configured to enter** and it is exactly the failure surface predicted by the Vmin shift theory. The `evidence-2026-04-30-web-research.md` "passes stress, fails at idle" signature is a textbook description of MWAIT 0x60 entry triggering a Vmin-induced kernel hang.

Worth flagging: there is no explicit `0x40 / C7` state in the per-CPU table here. The platform is going from C2_ACPI (hint 0x21) **directly to C8 (hint 0x60)** when the menu governor predicts long idle. There's no intermediate C6 stop. That's a real escalation cliff — every long-idle-predicted entry goes to the deepest available state, and the deepest available state happens to be the Vmin failure state.

## Per-CPU entry rates (CPU0 only — multiply by core count for cluster-wide rate)

| Node | C8-equivalent (state3) entries/sec | C8-equivalent (state3) entries since boot |
|---|---|---|
| k8s-1 | 510 / s | 3.93M |
| k8s-2 | 146 / s | 26.5M |
| k8s-3 | 55 / s | 1.79M |

i9-13900H has 6 P-cores + 8 E-cores = 14 physical cores (20 threads with HT on the P-cores). Cluster-wide entries per second is roughly cpu0 × ~14:

- k8s-1: ~7,000 entries/sec into the Vmin failure surface, cluster-cpu-wide
- k8s-2: ~2,000 entries/sec
- k8s-3: ~770 entries/sec

If even 1 in 10⁹ MWAIT 0x60 entries lands in a Vmin-degraded silicon corner, k8s-1 sees a candidate failure event roughly every ~40 hours and k8s-2 every ~140 hours. The R-series intervals (R3 → R4 = 16.8 h, R4 → R5 = 7 h, R5 → R6 = 6 h, etc.) don't fit a flat-prior 1-in-10⁹ — they're too short. But a higher per-entry failure rate (say, 1 in 10⁷ on a degraded core), combined with degradation that progresses over time, would fit. This is consistent with Vmin shift being a degradation-over-time mechanism, not a fixed-rate failure.

These numbers don't prove the Vmin hypothesis. They establish that **the failure surface predicted by the Vmin hypothesis is in active, heavy use** — every node is entering MWAIT 0x60 hundreds of times per second, every second.

## What this means for plan 0013

Iter #3's PM-QoS DaemonSet recommendation now has direct supporting data:

- A DaemonSet that holds `/dev/cpu_dma_latency` open with a value of `0` µs signals to the PM-QoS subsystem that no idle state with exit latency > 0 µs is acceptable. The kernel will skip every state past C1 (which has near-zero exit latency).
- This **deterministically removes MWAIT 0x60 entry** across the cluster.
- It works regardless of whether intel_idle uses native or ACPI-fallback state tables. PM-QoS sits above both.
- It is reversible (`kubectl delete ds`) and observable (cpuidle/state3/usage will stop incrementing within seconds).

Concrete experiment, ~14-day window:

1. Deploy the DaemonSet to all three nodes.
2. Verify on each node that `state3/usage` stops incrementing within 30 seconds.
3. Watch for ≥14 d. If silent reboots stop, Vmin/deep-C-state hypothesis is supported. If they continue, hypothesis is materially weakened.

Trade-off: power consumption rises (CPUs hold C0/C1 instead of dropping to C8) and idle CPU temperatures rise a few °C. On a 6-P-core + 8-E-core mobile chip in a small chassis, this is non-trivial — package power may rise from ~10 W idle to ~25 W idle. Worth doing as a diagnostic; long-term acceptance would need a thermal check.

## Connection to iter #5's `WatchdogTimerConfig` / `panic_on_*_nmi` recommendations

If a Vmin event traps in C8 entry/exit, the resulting kernel state is one of:
- **Hard CPU wedge** (no kernel response, no NMI dispatched): only iTCO (Finding 1 of iter #5) catches this with a deterministic timeout
- **Machine Check Exception broadcast as NMI**: `panic_on_unrecovered_nmi=1` (Finding 2 of iter #5) converts this into a panic with traceback shipped via the kernel sink

So iter #5's two Talos config patches and iter #6's PM-QoS DaemonSet are **complementary** — one prevents the failure (PM-QoS C-state cap), one bounds the worst-case time-to-reset if it still happens (iTCO feed), one converts the silent failure into a logged failure (NMI panic). All three should land together for the next watch window.

## Verification trail

```
$ for n in k8s-1 k8s-2 k8s-3; do
    echo === $n ===
    talosctl --endpoints $n -n $n read /sys/devices/system/cpu/cpuidle/current_driver
    talosctl --endpoints $n -n $n read /sys/devices/system/cpu/cpuidle/current_governor
    for i in 0 1 2 3; do
      n_=$(talosctl --endpoints $n -n $n read /sys/devices/system/cpu/cpu0/cpuidle/state$i/name 2>/dev/null | tr -d '\n')
      d_=$(talosctl --endpoints $n -n $n read /sys/devices/system/cpu/cpu0/cpuidle/state$i/desc 2>/dev/null | tr -d '\n')
      u_=$(talosctl --endpoints $n -n $n read /sys/devices/system/cpu/cpu0/cpuidle/state$i/usage 2>/dev/null | tr -d '\n')
      t_=$(talosctl --endpoints $n -n $n read /sys/devices/system/cpu/cpu0/cpuidle/state$i/time 2>/dev/null | tr -d '\n')
      x_=$(talosctl --endpoints $n -n $n read /sys/devices/system/cpu/cpu0/cpuidle/state$i/disable 2>/dev/null | tr -d '\n')
      printf "  state%d %-10s %-30s usage=%s time=%s disable=%s\n" "$i" "$n_" "$d_" "$u_" "$t_" "$x_"
    done
  done
```

(See conversation context for raw output.)

## Cross-references

- `evidence-2026-04-30-web-research.md` — first proposed C-state limiting; `intel_idle.max_cstate=1` was wrong knob for ACPI-fallback path, `processor.max_cstate=1` was right; both were blocked by iter #3 (UKI seal); /dev/cpu_dma_latency is the right runtime-writable equivalent
- `evidence-2026-05-06-kernel-args-not-applied.md` (iter #3) — the runtime PM-QoS DaemonSet path; this evidence note adds the direct measurement justifying it
- `evidence-2026-05-06-itco-unfed-and-nmi-panic-sysctls.md` (iter #5) — complementary forensic levers; iTCO bounds time-to-reset on a hard wedge, NMI-panic converts MCE-like silent failures to logged failures
- Plan 0013 — Phase 3 cascade-reproduction test costs more and tests less; iter #3 + iter #5 + iter #6 changes make a stronger Phase 3-equivalent
