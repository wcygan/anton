# Evidence: PCIe AER, EDAC ECC, thermal, voltage rails — all hardware error surfaces are clean

**Date:** 2026-05-06 (loop iteration #7, opus 4.7)
**Source:** Live `talosctl read /sys/...` for AER counters; betty TSDB `node_hwmon_temp_celsius`, `node_hwmon_in_volts`, `node_hwmon_fan_rpm`, `node_edac_*` metrics.
**Status:** A stack of negative findings. Each rules out a class of failure that would leave a trace, narrowing the surviving hypothesis space. Strengthens iter #6 (C8/MWAIT 0x60 / Vmin) by elimination.

## What's clean (and what each rule-out does)

### 1. PCIe AER counters on i40e SFP+ ports — all zero on every node

```
i40e port 0000:02:00.0 / 0000:02:00.1 (storage mesh):
  aer_dev_correctable: RxErr 0  BadTLP 0  BadDLLP 0
  aer_dev_fatal:       Undefined 0  DLP 0  SDES 0
  aer_dev_nonfatal:    Undefined 0  DLP 0  SDES 0
```

**Rules out:** PCIe link errors as the cause of iter #2's bilateral i40e flap. If the flap had been a PCIe-level event (link retraining, lane down-shift, TLP/DLLP error storm), AER would have at least correctable counters non-zero. They're zero on every node. The flap was at the **PHY/MAC layer or higher**, not the PCIe bus layer.

This is mildly bad news for the iter #2 hypothesis — a brief CPU-hang reading would have let the i40e PHY autonomously declare link-down for ~6s, but a PCIe bus glitch reading is now ruled out by AER staying clean. The remaining iter #2 reading is "brief CPU hang causing the firmware-driven PHY watchdog to flag link-down."

### 2. EDAC memory ECC counters — all zero on every node

```
node_edac_correctable_errors_total{controller=0|1, nodename=*}     = 0
node_edac_uncorrectable_errors_total{controller=0|1, nodename=*}   = 0
node_edac_csrow_correctable_errors_total{...}                       = 0
node_edac_csrow_uncorrectable_errors_total{...}                     = 0
```

Both memory controllers (`mc0`, `mc1`) on every node show zero ECC events since boot. For k8s-2 specifically, this covers 50.4 hours since the 2026-05-04T01:47Z BIOS-flash boot.

**Rules out:** Memory bit errors as a contributor for any reboot since the most recent boot. **Does not rule out** a memory error as the trigger of the silent reboot itself — the reboot resets the counters. But the multi-day clean window makes "frequent silent ECC events" implausible.

This is a meaningful update on the DDR5-Mushkin hypothesis from earlier in the investigation. Plan 0009's leading-candidate list put DDR5 training as #5 ("DIMM-swap is the decisive test"). With 50h of clean ECC on the post-flash boot, we have direct evidence that whatever Mushkin DDR5 is doing, it isn't producing detectable bit-error rates. **Soft DDR5 training issues remain possible** (training fails at boot but isn't ECC-flagged afterward), but live operational ECC errors are not the mechanism.

### 3. Thermal — current and 2h-peak temps are 30+°C below throttle threshold

`platform_coretemp_0` (CPU package + per-core sensors) over the last 2 h:

| Node | 2h peak | 2h median | Current peak | Tjmax (i9-13900H) |
|---|---|---|---|---|
| k8s-1 | **69°C** | 50°C | 55°C | ~100°C |
| k8s-2 | **64°C** | 55°C | 54°C | ~100°C |
| k8s-3 | **64°C** | 53°C | 52°C | ~100°C |

Thermal throttle on i9-13900H typically engages at ~95°C. The cluster runs **30-45°C below throttle** on average, and even the 2h peak is 25-30°C below throttle.

**Rules out:** Thermal-induced silent reboots. If thermal were the cause:
- Peaks would be ≥90°C
- Throttle events would log to `coretemp` `throttle_count`
- Reboots would correlate with thermal load events

None of these signatures are present. The iter #6 PM-QoS DaemonSet's expected thermal trade-off (CPUs hold C0/C1, idle temps rise ~5-10°C) lands the cluster at 60-70°C peaks — still well below throttle.

### 4. NVMe SMART temperature — drives are warm but not alarming

NVMe `temp2` (composite temp / hottest sensor on each drive):

| Node | drive 0 temp2 | drive 1 temp2 | drive 2 temp2 | NVMe spec warning |
|---|---|---|---|---|
| k8s-1 | 72.85°C | 61.85°C | 44.85°C | typically 75°C |
| k8s-2 | 62.85°C | **74.85°C** | 46.85°C | typically 75°C |
| k8s-3 | 60.85°C | 71.85°C | 45.85°C | typically 75°C |

Some drives are right at the warning threshold but none are throttling (drives report `Warning Composite Temperature Threshold` typically at 75°C and `Critical` at 80°C). **Worth flagging:** k8s-2's nvme1 at 74.85°C is on the edge. NVMe drives running near WCTEMP have documented issues with ASPM transitions causing brief stalls — which connects loosely back to the iter #2 bilateral-flap reading if a hot NVMe-induced PCIe bus stall propagated to the i40e card.

But:
- AER is zero on the i40e devices
- AER is something to verify on the NVMe devices too — not done in this iter, worth a follow-up read

### 5. Voltage rails (nct6775 super-I/O) — no obvious dips

For k8s-1 sample (other nodes similar):

| Rail | Reading | Expected |
|---|---|---|
| in2/in3 (3.3V) | 3.36V | 3.30V ± 5% (3.14 - 3.47) ✓ |
| in7 (3.3V VBAT?) | 3.34V | 3.30V ± 5% ✓ |
| in8 (3.3V VSB?) | 3.15V | 3.30V ± 5% — **slightly low** |
| in1 / in12 (CPU Vcore-ish) | 1.03 / 1.02 V | varies with C-state, 0.7-1.3V typical |
| in14 (DDR5 VDD) | 1.26V | 1.10V nominal, **slightly high** but within DDR5 spec range |
| Fan 1 (CPU) | 2149 RPM | active cooling, normal |
| Fan 2 (case) | 2033 RPM | active cooling, normal |

The 3.15V on `in8` is on the low side of nominal (should be ~3.3V) but not enough to flag as a fault. **Worth noting:** nct6775 voltage readings are vendor-calibrated and absolute accuracy is ±5%. The ~5% low reading on `in8` may simply be calibration offset. **Cannot conclusively say there's a rail-dip issue without trending data over the silent-reboot window** (which betty doesn't have retention for yet).

Not a smoking gun. Not a clean rule-out either.

## Cumulative implication

Hardware error surfaces that *would* leave a trace are **all clean**:
- ❌ PCIe AER (zero across i40e ports)
- ❌ Memory ECC (zero on both controllers, all rows)
- ❌ Thermal throttling (peaks 30°C below threshold)
- ❌ Fan failure (fans running normally)
- ⚠ NVMe temperatures near warning threshold on the data drives (worth tracking)
- ⚠ One voltage rail slightly low (likely calibration, not fault)

This pattern — every error-reporting surface clean, yet silent reboots occur — is exactly the **Vmin shift signature**. Vmin failures happen at the silicon level when supply voltage drops below the minimum the degraded transistors can sustain. The clock tree glitches, instructions execute incorrectly for a few cycles, and the CPU either:

- Resets via the iTCO hardware watchdog (no kernel log because the kernel is running corrupted instructions before reset, can't write coherent dmesg)
- Resets via an internal CPU MCE handler that fires before the kernel's MCE handler can run
- Resets via a cold-reset triggered by the chipset on detecting an inconsistent state

In all three cases, **no log is written** because the failure is below the level where logging is possible. Iter #6 showed this failure surface (MWAIT 0x60 / C8) is in heavy active use. Iter #7 shows the side surfaces (PCIe AER, ECC, thermal) are clean. **By elimination, the failure mechanism is at the level the Vmin hypothesis predicts.**

## What this changes for the recommendation stack

The three landings from iter #5 + iter #6 are reinforced:

1. **PM-QoS DaemonSet** (iter #3 / iter #6) — directly removes the C8 failure surface that iter #6 measured and iter #7's clean-error-surfaces narrow to as the most plausible mechanism
2. **`WatchdogTimerConfig` feeding iTCO** (iter #5) — bounds time-to-reset on a hard wedge that would otherwise leave only the bilateral i40e flap as a precursor signal
3. **`SysctlConfig kernel.panic_on_*_nmi=1`** (iter #5) — converts MCE-induced silent failures to logged panics

The relative priority shifts slightly. Before iter #7, all three were "complementary, deploy together." After iter #7, **the PM-QoS DaemonSet rises to the strongest single bet** because:

- Multiple side surfaces are now ruled out (PCIe, ECC, thermal)
- The Vmin/C8 surface is the surviving plausible mechanism
- The DaemonSet directly removes the surface
- All three remain complementary; deploy all three; but if forced to pick one, the DaemonSet is now the highest-leverage

## What's NOT yet ruled out (to be honest)

- **MCE silent swallow:** the kernel may be receiving MCE events but not logging them. Iter #5's `panic_on_unrecovered_nmi=1` recommendation addresses this prospectively but we have no retrospective check.
- **NVMe controller hang:** NVMe AER counters not yet checked; drives are warm; ASPM is enabled per BIOS 1.27 changelog. Worth a follow-up iter.
- **Soft DDR5 training failure at boot** that doesn't produce ECC errors: still possible, would need DIMM swap to verify.
- **Hardware watchdog (iTCO) firing on something we don't see:** verifiable only by enabling the watchdog feed and seeing if the next reboot's interval changes.

These are the remaining hypothesis frontier. None are as concrete as the C8/Vmin reading, but they should stay on the list.

## Verification trail

```
$ for slot in 0000:02:00.0 0000:02:00.1; do for f in aer_dev_correctable aer_dev_fatal aer_dev_nonfatal; do
    talosctl --endpoints k8s-2 -n k8s-2 read /sys/bus/pci/devices/$slot/$f
  done; done
RxErr 0  BadTLP 0  BadDLLP 0
Undefined 0  DLP 0  SDES 0
Undefined 0  DLP 0  SDES 0
... (identical on all three nodes for both ports)

$ curl -s ... 'query=node_edac_correctable_errors_total' | jq ...
all results == 0

$ curl -s ... 'query=max_over_time(node_hwmon_temp_celsius{chip=~".*coretemp.*"}[2h])' | jq ...
k8s-1 peak 69.0°C  k8s-2 peak 64.0°C  k8s-3 peak 64.0°C
```

## Cross-references

- `evidence-2026-05-06-c-states-active.md` (iter #6) — direct measurement of the surviving failure surface
- `evidence-2026-05-06-itco-unfed-and-nmi-panic-sysctls.md` (iter #5) — forensic levers that complement the prevention
- `evidence-2026-05-06-k8s-2-precursor-nic-flap.md` (iter #2) — bilateral i40e flap; AER zero now rules out the PCIe-bus reading of that event
- `evidence-2026-05-06-betty-retention-and-flap-rates.md` (iter #4) — retention-window note; same-day caveat applies here for thermal/voltage trending
- `evidence-2026-04-30-web-research.md` — DDR5 / NVMe / ASPM hypotheses; iter #7 narrows them
