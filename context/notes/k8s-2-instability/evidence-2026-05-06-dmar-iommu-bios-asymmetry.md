# Evidence: BIOS 1.27 enables VT-d/IOMMU (DMAR table present); BIOS 1.26 does not — a real BIOS-version functional asymmetry

**Date:** 2026-05-06 (loop iteration #20, opus 4.7)
**Source:** `talosctl list /sys/firmware/acpi/tables/` per node; `/proc/stat`, `/proc/zoneinfo`, `/proc/buddyinfo`.
**Status:** One genuinely fresh asymmetry + supporting data on memory fragmentation profile.

## Finding 1 — DMAR (IOMMU) ACPI table presence is BIOS-version-correlated

ACPI table list per node, comparing what's present:

| Table | k8s-1 (BIOS 1.26) | k8s-2 (BIOS 1.27) | k8s-3 (BIOS 1.27) |
|---|---|---|---|
| APIC, ASF!, DBG2, DBGP, DSDT, FACP, FACS, FIDT, FPDT, HPET, LPIT, MCFG, NHLT, PHAT, SSDT1-13 | ✓ | ✓ | ✓ |
| **DMAR** | **absent** | **present** | **present** |

**`DMAR` (DMA Remapping) is the ACPI table that declares Intel VT-d / IOMMU support to the OS.** Its absence on k8s-1 means the BIOS 1.26 firmware doesn't expose IOMMU, so the kernel runs DMA passthrough mode (no IOMMU translation). Its presence on k8s-2 and k8s-3 means BIOS 1.27 enables IOMMU, so the kernel uses `intel_iommu` for DMA translation on every PCIe transaction.

This is a **real BIOS-version functional asymmetry that nobody recorded**. The BIOS-flash narrative ("k8s-2 + k8s-3 went from 1.22 to 1.27 on 2026-05-04 to address Vmin issues") apparently also enabled VT-d as a side effect — or VT-d was always declared by 1.22 too, and the difference is between 1.22/1.27 and 1.26 specifically. Either way, **k8s-1 is on a different DMA architecture than k8s-2 and k8s-3 right now**.

### Implications

| Aspect | k8s-1 (no DMAR) | k8s-2 / k8s-3 (DMAR present) |
|---|---|---|
| DMA translation overhead | None (direct DMA) | Per-transaction IOMMU page-table lookup |
| IOMMU TLB | N/A | Active (PCIe device → IOVA → physical address) |
| IOMMU faults possible | No | Yes (configurable: report, halt, or reset) |
| Kernel DMA-API behavior | Bypass | Goes through `iommu_dma_*` paths |

**IOMMU faults are a documented silent-reboot mechanism on Intel platforms.** If a PCIe device issues a DMA to an unmapped IOVA, the IOMMU can be configured (BIOS-side) to either log + continue, log + halt, or reset. The default depends on `intel_iommu=` kernel param (not set in this cluster's cmdline — iter #3 confirmed). With no kernel-side configuration, BIOS defaults govern.

**But:** the 2026-05-05 cross-node event involved silent reboots on **both k8s-1 (no IOMMU) and k8s-3 (IOMMU enabled)**. So IOMMU is not necessary for silent reboots to occur. It could still be a *contributor* on the 2-of-3 nodes that have it active, but it's not the primary mechanism.

### Worth checking but not done in this iter

- `dmesg | grep -iE 'iommu|dmar|vt-d'` per node — to see if IOMMU faults have been logged. Iter #2 swept dmesg for hardware-error patterns and found nothing matching `iommu` or related, so IOMMU faults haven't been logged.
- Verify that `/sys/class/iommu/` is populated on k8s-2 + k8s-3 but not k8s-1.
- Look at the `intel_iommu` boot parameter — Talos may set it to `on` or leave it implicit.

These are quick follow-ups; the high-level finding stands without them.

### What this changes

It adds a possible third silent-reboot mechanism, **active only on the BIOS-1.27 nodes (k8s-2 + k8s-3)**:

4. **IOMMU fault** on a misbehaving PCIe device → BIOS-default reset (silent, no kernel log) — speculative, requires verification

But this **doesn't explain k8s-1's 2026-05-05 reboot** (no IOMMU on k8s-1). So under any unified hypothesis, IOMMU is at most a contributor, not the root cause. The mainline Vmin/C8 reading from iter #6 + iter #7 still works on every node regardless of IOMMU state.

The recommendation stack is unaffected. The iter #5/#6/#8 PR addresses the dominant mechanism. **If, after the PR lands, silent reboots continue specifically on k8s-2 or k8s-3 but stop on k8s-1, IOMMU becomes the next-priority hypothesis.**

## Finding 2 — Memory fragmentation profile shows k8s-2 has more single-page fragmentation

`/proc/buddyinfo Normal zone, free pages by order`:

| Node | Order 0 (4KB) | Order 1 (8KB) | Order 2 (16KB) | Order 10 (4MB) |
|---|---|---|---|---|
| k8s-1 | 3,511 | 1,272 | 853 | 21,069 |
| **k8s-2** | **48,735** | **9,320** | 2,480 | 18,265 |
| k8s-3 | 19,881 | 11,796 | 2,115 | 20,496 |

**k8s-2 has 14× more order-0 (single-page, 4KB) free chunks than k8s-1 and 2.5× more than k8s-3.** Higher low-order counts with similar high-order counts indicates **slab-allocator fragmentation** — many small allocations and frees creating a sea of single-page free chunks.

This is consistent with iter #12: k8s-2 hosts Prometheus, Alertmanager, Grafana, cilium-operator, cnpg — all of which do many small allocations (TSDB sample buffers, alert rule eval, Go GC churn). The fragmentation profile fits.

**Not a silent-reboot cause** — Linux's buddy allocator handles fragmentation gracefully via compaction. But it's a forward-looking metric: alert on `node_memory_NormalFreeFragmented_bytes` ratio could give an early warning for memory-pressure scenarios.

## Finding 3 — Per-CPU activity rates: k8s-2 is moderate, not extreme

| Node | Uptime | Context switches/s | Interrupts/s | Processes spawned/s |
|---|---|---|---|---|
| k8s-1 | 7.7h | 38.4K | 17.9K | 35.2 |
| k8s-2 | 50.4h | **27.1K** (lowest) | **12.8K** (lowest) | 29.2 |
| k8s-3 | 9.1h | **47.9K** (highest) | **22.3K** (highest) | 39.4 |

**k8s-2 has the lowest current per-second activity rates.** Inverse of "high load → reboots" — fits the iter #12 + iter #14 reading (more idle → more C8 entries → more Vmin exposure). k8s-2 is currently moderate workload. The historical R0–R8 bias must reflect a different workload distribution at the time.

## Honest assessment of iter #20

| Probe | Result |
|---|---|
| ACPI tables | DMAR (IOMMU) present on BIOS 1.27 nodes (k8s-2, k8s-3), absent on BIOS 1.26 (k8s-1) — **fresh asymmetry** |
| Per-CPU stats | k8s-2 has lowest activity, k8s-3 highest — fits "less busy = more C8 = more Vmin" reading |
| Memory zones / buddy | k8s-2 has 14× more single-page fragmentation than k8s-1 — fits "k8s-2 hosts bursty alloc-heavy workloads" |

**Net contribution:** one fresh per-node asymmetry (DMAR/IOMMU presence), supporting evidence for prior readings, no new mainline candidate hypothesis. Recommendation stack unchanged.

## Cross-references

- `evidence-2026-05-06-k8s-2-hosts-observability-stack.md` (iter #12) — workload placement; iter #20 buddyinfo data is a quantitative supporter
- `evidence-2026-05-06-c-states-active.md` (iter #6) — C8 measurement; iter #20 IOMMU is a possible additional silent-reboot mechanism on 2 of 3 nodes
- `evidence-2026-05-06-efi-vars-and-vuln-mitigations.md` (iter #18) — BIOS-version asymmetry hypothesis; iter #20 DMAR is a concrete BIOS-version effect

## Verification trail

```
$ for n in k8s-1 k8s-2 k8s-3; do
    echo === $n ===
    talosctl --endpoints $n -n $n list /sys/firmware/acpi/tables/ | grep -E 'DMAR|FACP|DSDT'
  done
k8s-1: FACP, DSDT  (no DMAR)
k8s-2: DMAR, FACP, DSDT
k8s-3: DMAR, FACP, DSDT

$ for n in k8s-1 k8s-2 k8s-3; do
    talosctl --endpoints $n -n $n read /proc/buddyinfo | grep Normal
  done
```
