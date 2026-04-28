---
name: k8s-2 DIMM and BIOS hardware split
description: k8s-2 has Mushkin DDR5 at 5200 MT/s and older AHWSA.1.22 BIOS while k8s-1/k8s-3 run Crucial at 5600 MT/s — only confirmed hardware delta tied to the silent-reboot saga
type: project
---

Found 2026-04-28 during the hardware/firmware re-survey for plan 0010 Stage A abort.

**Facts:**
- k8s-1 / k8s-3: Crucial `CT48G56C46S5.M16B1`, 2× 48 GiB, training to **5600 MT/s**, BIOS 1.26 (2024-10-14).
- k8s-2: Mushkin `MRA5S520HHHD48G`, 2× 48 GiB, training to **5200 MT/s**, BIOS AHWSA.1.22 (2024-03-12). DIMM SPD serials report `00000000` (Mushkin SPD trait, not a defect by itself). DMI `Version` and `SKUNumber` are `Default string` (BIOS never re-flashed since assembly).
- k8s-2 dmesg uniquely contains `ENERGY_PERF_BIAS: Set to 'normal', was 'performance'` — kernel resetting a BIOS-default that the other nodes don't ship with.
- k8s-2 boots with `BOOT_IMAGE=/B/vmlinuz` (B partition / grub-style); k8s-1/k8s-3 boot from A side without `BOOT_IMAGE=`.
- CPU SKU, microcode (0x6134), kernel (6.18.18-talos), Talos version (v1.12.6), NIC firmware, NVMe firmware are identical across all three.
- Source: `talosctl get memorymodules -o yaml`, `read /proc/cmdline`, `dmesg | rg 'kern: warn'`, `get systeminformation`.

**Why:** This is the only confirmed k8s-2-only hardware/firmware delta. EDAC/MCE/HardwareCorrupted are zero on all nodes, so any hardware-side failure mode would have to be the kind that resets the platform faster than the kernel can log (DIMM training failure on warm-reset, VRM droop, CPU MCE bypass). Mushkin DDR5 + older BIOS is a plausible carrier.

**How to apply:**
- When triaging future k8s-2 instability, list the DIMM/BIOS split as the standing hardware hypothesis. Don't reset to "no in-band evidence found" — there is now one concrete delta.
- Cheapest decisive in-band probe: pin the `k8s-2-rejoin-smoke` workload to **k8s-1** for a 24 h negative-control window. If k8s-1 reboots, hardware is exonerated.
- Decisive physical probe: swap one Mushkin stick into k8s-1 and one Crucial into k8s-2. Cluster has no BMC so this is the only way to definitively localize.
- If a future BIOS reflash on k8s-2 normalizes BIOS to 1.26, document it here and re-baseline — it removes the EPB-default and BIOS-version legs of the hypothesis in one shot.
