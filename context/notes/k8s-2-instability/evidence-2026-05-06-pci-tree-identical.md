# Evidence: PCI device tree is bit-for-bit identical across all three nodes — final hardware-asymmetry rule-out

**Date:** 2026-05-06 (loop iteration #22, opus 4.7)
**Source:** `talosctl read /sys/bus/pci/devices/<addr>/{vendor,device,revision,class}` for all 30 PCI devices on all three nodes; three-way diff.
**Status:** Clean hardware rule-out. Closes the hardware-asymmetry investigation surface.

## Observation

```
$ for n in k8s-1 k8s-2 k8s-3; do
    count=$(talosctl --endpoints $n -n $n list /sys/bus/pci/devices/ | wc -l)
    echo "$n: $count PCI devices"
  done
k8s-1: 31 PCI devices
k8s-2: 31 PCI devices
k8s-3: 31 PCI devices

$ diff /tmp/pci-list/k8s-1.txt /tmp/pci-list/k8s-2.txt
(empty — bit-for-bit identical)

$ diff /tmp/pci-list/k8s-2.txt /tmp/pci-list/k8s-3.txt
(empty — bit-for-bit identical)
```

Per device, the comparison covered:
- **PCI address** (slot:bus:device.function)
- **`vendor:device` IDs** (silicon identification)
- **`revision`** (silicon stepping)
- **`class`** (PCI class code)

All 30 collected devices match across all three nodes on every field.

## What this rules out

**There is no PCI-silicon asymmetry between k8s-1, k8s-2, and k8s-3.** Every NIC, NVMe controller, USB controller, audio codec, PCIe bridge, chipset PCH device — same vendor ID, same device ID, same stepping. The MS-01 boards in the cluster are silicon-identical.

This **closes the hardware-asymmetry investigation surface**. Combined with prior rule-outs:

| Iteration | Surface checked | Result |
|---|---|---|
| #11 | NVMe drives (model + firmware + serial slot) | Identical |
| #13 | BIOS vendor / board version / product family | Identical |
| #15 | Kernel module parameters (intel_idle, pcie_aspm, nvme_core, etc.) | Identical |
| #17 | IRQ affinity | Identical (`cpus=0-19` everywhere) |
| #17 | Talos machineconfig content | Identical (modulo per-node identifiers) |
| #18 | CPU vulnerability mitigations | Identical |
| #21 | EDAC DIMM topology | Identical (modulo igen6 driver limitation) |
| **#22** | **Full PCI device tree** | **Bit-for-bit identical** |

**Every dimension of hardware identity that the investigation can probe from inside the running OS is uniform across nodes.** The only hardware-side differential is BIOS version (1.26 on k8s-1 vs 1.27 on k8s-2/k8s-3), and that drives the IOMMU asymmetry from iter #20 and (per iter #18) the EFI variable count differential.

## What remains as legitimate per-node asymmetry

After 22 iterations, the asymmetries between nodes that are real and possibly load-bearing are:

| Asymmetry | Source | Possibly load-bearing? |
|---|---|---|
| BIOS version (1.26 vs 1.27) | k8s-1 was not flashed on 2026-05-04 | Yes — IOMMU activation, EFI var differential, possible Vmin handling |
| **Workload placement** | Scheduler-induced + StatefulSet stickiness | **Yes — dominant explanation** (iter #12) |
| machineconfig version count (3 vs 1) | Apply history during plan 0007/0009/0010 | No — content uniform (iter #17) |
| EFI variable count (70/79/88) | BIOS flash history | Probably not — passive storage |
| Cilium BPF program count | Reflects pod density | No — proxy for workload |
| Memory fragmentation profile | Reflects bursty alloc workload | No — proxy for workload |

**The dominant explanation for k8s-2's historical reboot bias is workload placement (iter #12) on identical hardware.** The mechanism is cluster-wide Vmin/C8 (iter #6 + #7 + #9 + #14), with E-core dominance (iter #14), amplified by RFDS register-clear cost (iter #18), with IRQ delivery preferentially landing on the most-idle (E-)cores (iter #17).

## What this changes

**Nothing.** The recommendation stack from iter #5/#6/#8 with iter #14/#15/#17 manifest refinements is unchanged. iter #22 is a strong corroborator of the existing reading; it doesn't open or close any candidate.

Worth recording because it's a **definitive negative** on a class of hypothesis that the investigation has been asymmetrically confident about — "is there some k8s-2-specific hardware quirk?" — and the answer at the OS-visible PCI layer is **provably no**.

The only remaining hardware-level question that this can't fully answer is **silicon-internal corner damage** (Vmin shift on a specific core), which is per-die degradation and wouldn't show up in PCI IDs. That's the surviving "k8s-2 silicon got the worst luck on Vmin shift" sub-hypothesis. **Iter #12's workload-placement reading subsumes it cleanly** — k8s-2 hosting the bursty observability stack means k8s-2 sees the most C-state transitions, regardless of silicon corner.

## Honest assessment of iter #22

Strong negative evidence, recommendation unchanged. After 22 iterations:

- Hardware asymmetry: comprehensively ruled out (this iter is the final one)
- Kernel/OS asymmetry: ruled out across many surfaces (iter #5, #9, #15, #17)
- Talos-config asymmetry: only procedural (apply count), not content (iter #17)
- BIOS-version asymmetry: real but converging on k8s-2/k8s-3 (iter #18, #20)
- Workload-placement asymmetry: real and dominant (iter #12)

**The case for the iter #5/#6/#8 PR is now as strong as analytical work can make it.** Empirical signal from a watch window is the only meaningfully informative next data point.

## Cross-references

- All 21 prior iterations
- `evidence-2026-05-06-k8s-2-hosts-observability-stack.md` (iter #12) — the dominant explanation that survives hardware rule-out
- `evidence-2026-05-06-dmar-iommu-bios-asymmetry.md` (iter #20) — the only surviving non-workload asymmetry (BIOS-version-induced IOMMU activation)
- Plan 0013 — investigation-as-investigation is essentially complete; the next move is operational
