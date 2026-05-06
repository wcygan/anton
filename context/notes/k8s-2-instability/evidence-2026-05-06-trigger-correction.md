# Evidence: iter #35's "1 in 100,000" trigger-attribution claim corrected — `/Processes` is structurally last in every cycle, not statistically anomalous

**Date:** 2026-05-06 (loop iteration #36, opus 4.7)
**Source:** Vector sink query for normal-operation k8s-2 machined gRPC call ordering, 2026-04-27T12:00:00-12:01:00Z window.
**Status:** **Honest correction of iter #35.** The trigger reading is refined, not reversed.

## What iter #35 claimed

iter #35 found that **5 of 5** historical k8s-2 silent reboots had `/machine.MachineService/Processes` as the LAST gRPC call before silence, and computed the probability as **(1/10)^5 = 1 in 100,000**. The claim assumed that any of the 10 endpoints had equal probability of being last in any cycle.

## What iter #36 measured

Sampling normal-operation traffic from the sink shows the cycle structure:

```
12:00:02 cycle: ServiceList → Version → LoadAvg → Memory → DiskStats → NetworkDeviceStats → SystemStat → CPUInfo → CPUFreqStats → Processes
12:00:07 cycle: Version → ServiceList → LoadAvg → Memory → NetworkDeviceStats → CPUInfo → DiskStats → SystemStat → CPUFreqStats → Processes
12:00:12 cycle: Version → Memory → ServiceList → LoadAvg → DiskStats → ...
```

**The early calls (ServiceList, Version, LoadAvg, Memory) are randomly interleaved**, but **CPUFreqStats is consistently second-to-last and Processes is consistently last** in each cycle. The reason isn't policy ordering — it's **call duration**:

| Endpoint | Typical duration |
|---|---|
| Version, LoadAvg, Memory, ServiceList | ~0.2 ms |
| DiskStats, NetworkDeviceStats, SystemStat | 0.3-1 ms |
| CPUInfo | 1-2 ms |
| CPUFreqStats | 3-4 ms |
| **Processes** | **11-17 ms** |

**The dashboard fires all 10 calls roughly in parallel; their RESPONSES log in order of completion, with Processes always last because it's the slowest.**

Counting "what was the last-logged call in each ~5s cycle" in a 1-minute normal-operation window of 13 cycles: ~8 cycles ended with Processes, ~4 with ServiceList, ~1 with Memory. **So Processes is last in roughly 60-80% of cycles, not 10%.**

## Corrected statistical claim

With p ≈ 0.7 for "Processes is last in any given cycle," the probability of 5/5 events ending with Processes by chance is **0.7⁵ ≈ 17%**. **Not "1 in 100,000". Not statistically remarkable.**

## What's still true (iter #35's reading is refined, not reversed)

1. **Processes IS the longest-duration call**, hence the most kernel-mode time per cycle — still likely the heaviest trigger surface.
2. **5/5 events ending with Processes is consistent with a 70% per-cycle probability** — slightly elevated above expectation but well within sampling noise.
3. **The trigger is "the C-state entry/exit at the end of each 5-second cycle"**, not specifically Processes. Processes happens to be the call that bookends each cycle, but the actual wedge is in the brief idle window that follows.

This is **the same mechanism iter #6 already identified** — Vmin/C8 idle-wake voltage glitch — operationalized:

- Each 5s scrape cycle wakes all 14 cores (E-cores from C8) to service ~10 calls
- Calls finish (~12-20ms total burst)
- All cores drop back to C8
- During the next idle window OR the wake into the next cycle, occasionally a Vmin failure occurs
- The failure is binary (iter #31), kernel goes silent, ~40s later iTCO fires (iter #29-30)

## What this changes for the recommendation stack

**Nothing material.** The mitigations addressing iter #6's Vmin/C8 mechanism (PM-QoS DaemonSet) directly remove the failure window regardless of whether the trigger is "Processes specifically" or "any cycle-ending C8 transition."

But iter #35's "free experiment of closing talosctl dashboard" still has expected value:
- Eliminates the deterministic 5-second poll cycle entirely
- If any reboots were specifically tied to that cycle's wake events, those go away
- Remaining wake events (workload activity, etc.) are non-periodic — Vmin failures still possible but at lower rate
- **PM-QoS DaemonSet still needed as the durable fix**

## Honest pattern across iterations

iter #25 corrected iter #24's RX-drop rate (cumulative ÷ uptime ≠ rate). 
iter #36 corrects iter #35's per-event probability (single-pass count without baseline check).

**Both are the same class of error**: aggregating data without verifying the baseline distribution. **The Vector sink and betty TSDB respectively caught both errors in the next iteration.** That's the intended forensic value of having multiple independent data sources — a wrong reading on one surface can be checked against another.

After 36 iterations, the cumulative finding is **robust to two self-corrections**:

- The Vmin/C8 mechanism is supported by direct measurement (iter #6), elimination of all other failure surfaces (iter #7+#9), the precursor signature in 5/5 verifiable events (iter #29-30), the binary-wedge characteristic (iter #31), and the workload-placement asymmetry that explains k8s-2 bias (iter #12).

- The trigger surface is the C-state cycle that follows scraper bursts. The scraper is most likely operator-running `talosctl dashboard` (iter #34), generating periodic 5-second wake bursts. **Closing it is a free experiment**; the PM-QoS DaemonSet (iter #6) is the durable mitigation regardless.

## Cross-references

- `evidence-2026-05-06-precursor-signature-found.md` (iter #29) — the cumulative signature; iter #36 doesn't change it, just refines the trigger attribution
- iter #35 conversation — original trigger claim; iter #36 corrects the statistical argument
- `evidence-2026-05-06-rx-drops-correction.md` (iter #25) — same class of statistical error; iter #36 is the second instance
- `evidence-2026-05-06-c-states-active.md` (iter #6) — the underlying mechanism; iter #36 confirms the trigger surface fits this mechanism
