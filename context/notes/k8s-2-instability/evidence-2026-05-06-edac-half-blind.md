# Evidence: EDAC reports only 48 GiB of the 94 GiB physical memory — partial weakening of iter #7's "ECC clean" rule-out

**Date:** 2026-05-06 (loop iteration #21, opus 4.7)
**Source:** `talosctl read /sys/devices/system/edac/mc/mc{0,1}/dimm0/{dimm_label,size,dimm_mem_type,dimm_dev_type,dimm_location}` per node, plus `/proc/meminfo`.
**Status:** One concrete EDAC limitation that weakens (not reverses) a prior rule-out, plus uniform DIMM-side data.

## Finding — EDAC sees half the memory

Per node, EDAC reports:

```
mc0/dimm0: label='MC#0_Chan#0_DIMM#0' size=24576 MiB  type=Unbuffered-DDR3 (sic)  loc='channel 0 slot 0'
mc1/dimm0: label='MC#1_Chan#0_DIMM#0' size=24576 MiB  type=Unbuffered-DDR3 (sic)  loc='channel 0 slot 0'
```

**Two memory controllers, one 24 GiB DIMM each = 48 GiB ECC-visible.**

But `/proc/meminfo` shows:

```
k8s-1 MemTotal: 94.1 GiB
k8s-2 MemTotal: 94.0 GiB
k8s-3 MemTotal: 94.0 GiB
```

**The kernel actually uses ~94 GiB on every node**, but EDAC's view covers only ~48 GiB. **EDAC is blind to roughly half the physical memory.**

Two contributing reasons:

1. **EDAC reports `dimm_mem_type=Unbuffered-DDR3`** when this is actually DDR5 SODIMM. The `igen6` EDAC driver (the in-tree driver for 12th/13th-gen Intel client platforms) doesn't fully support i9-13900H Raptor Lake-P at the kernel-version level Talos ships. The DDR3 misidentification is a known kernel limitation — Intel's IBECC (In-Band ECC) on these chips uses different MMIO registers than older platforms.
2. **EDAC reports 1 DIMM per controller × 2 controllers = 48 GiB**, but the system has 2× 48GB DDR5 SODIMMs (Mushkin 96GB kit per the prior investigation). The igen6 driver may be reporting one rank per channel rather than the full DIMM, or grouping the two physical SODIMMs in a way that halves the visible size.

### Why this matters for the prior investigation

**Iter #7 reported `node_edac_correctable_errors_total = 0`** on every controller and every csrow on every node, and concluded "live operational ECC errors are not the mechanism." That conclusion is **partially weakened**:

- EDAC counters cover ~48 of 94 GiB
- ECC errors on the EDAC-invisible ~46 GiB are not counted by these counters
- A memory error in the invisible half would not appear in `node_edac_*` metrics

This **doesn't make memory errors a leading hypothesis** — there are still no MCE events in dmesg (iter #2 sweep), no kernel taint bit 4 set (iter #9), no reported memory-related kernel oopses, and no PSI memory-pressure full-stalls (iter #9). But the strict reading of iter #7 was: "EDAC=0 across all controllers proves no memory errors." The strict reading should be relaxed to: "EDAC=0 across the half of memory EDAC can see proves no memory errors *in that half*."

### What surfaces *would* see memory errors on the invisible half

- **Kernel MCE delivery via dmesg.** When a memory error escalates to an MCE, the kernel's MCE handler logs to dmesg regardless of EDAC visibility. Iter #2's dmesg sweep was clean — so any errors that escalated to MCE would have shown there. **Doesn't fully cover correctable-only errors.**
- **`kernel.tainted` bit 4** (machine-check). Iter #9 confirmed this is 0 on every node. Bit 4 is set on any MCE, including correctable ones. **Strong negative evidence on the MCE path.**

So the integrated rule-out is: **MCE-class memory errors are confidently zero (kernel.tainted + dmesg both clean), but sub-MCE correctable ECC events on the EDAC-invisible half could be occurring without detection.** That's a smaller residual than I implied in iter #7.

### Implication for plan 0013

It's a small but real gap in the forensic surface. Two ways to close it:

1. **Custom Talos kernel build with updated `igen6` driver.** May come with newer Talos / Linux kernel — Talos 6.18.24 is already recent. If a kernel update lands that improves igen6 support for Raptor Lake-P, this gap closes automatically.
2. **Out-of-tree EDAC driver or `mcelog` / `rasdaemon`.** Significant complexity. Probably not worth it for the marginal gain — the surviving Vmin/C8 hypothesis is well-supported by the other 19 iterations' evidence.

**Recommendation:** add a small note to plan 0013 acknowledging that ECC visibility is partial. Don't change the recommendation stack.

## Supporting findings

### Memory layout uniform across nodes

```
k8s-1: MemTotal 94.1 GiB, MemAvailable 87.4 GiB (93%)
k8s-2: MemTotal 94.0 GiB, MemAvailable 84.7 GiB (90%)
k8s-3: MemTotal 94.0 GiB, MemAvailable 86.6 GiB (92%)
```

k8s-2 has slightly less MemAvailable than the others (consistent with hosting Prometheus + Alertmanager + Grafana per iter #12). All three are well below pressure.

### SMBIOS Type 17 entries: 0 via this sysfs path

`/sys/firmware/dmi/entries/17-N/` returns no entries on any node. Either Talos restricts that path, or this kernel build exposes DMI differently. **Not a finding** — just a limitation. If we wanted detailed per-DIMM SMBIOS info (vendor, model, speed), `dmidecode` would need to run, which requires root in a privileged container. Not worth the effort for marginal value.

## Honest assessment of iter #21

| Probe | Result |
|---|---|
| EDAC DIMM topology | Uniform across nodes (2 controllers × 1 DIMM × 24 GiB) |
| EDAC vs meminfo coverage | **EDAC visible = ~48 GiB; actual = ~94 GiB** — half-blind |
| SMBIOS Type 17 via sysfs | Not exposed in this Talos build |
| MemAvailable | k8s-2 slightly lower (consistent with workload, not pressure) |

**Net contribution:** mild correction to iter #7 (ECC rule-out covers only half the memory). MCE path is still confidently clean. Surviving recommendation stack is unchanged.

After 21 iterations, the analytical surface is genuinely exhausted. **The diminishing-returns curve has flattened — iter #21 is a refinement of iter #7, not a new candidate.**

## Cross-references

- `evidence-2026-05-06-hardware-error-surfaces-clean.md` (iter #7) — original "ECC clean" reading, partially weakened by iter #21
- `evidence-2026-05-06-kernel-taint-and-psi-clean.md` (iter #9) — `kernel.tainted` bit 4 = 0 on every node; **this is the stronger negative-evidence anchor for memory-error rule-out** since taint is not EDAC-dependent
- `evidence-2026-05-06-itco-unfed-and-nmi-panic-sysctls.md` (iter #5) — MCE bank counters not exposed in sysfs on this kernel; complements iter #21's igen6 limitation in a similar way
- `evidence-2026-04-30-web-research.md` — flagged Mushkin DDR5 SKU as k8s-2-specific risk; iter #21 establishes that EDAC can't differentiate DIMM SKU on this hardware regardless of vendor
- Plan 0013 — small note worth adding to acceptance criterion text about partial ECC visibility
