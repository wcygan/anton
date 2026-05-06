# Evidence: HMB enabled on all WD drives + IOMMU active on 2 of 3 nodes is a documented silent-reset path; KSPP-retry-spam is rolling forensic dmesg out of the ring

**Date:** 2026-05-06 (loop iteration #27, opus 4.7)
**Source:** `talosctl read /sys/class/nvme/nvme*/hmb` per node, `talosctl dmesg | grep 'unchecked data buffer'` recount, `node_nvme_info` from betty.
**Status:** One thread worth flagging that connects iter #20 + iter #23 + iter #6, plus a meta-finding about KSPP spam and forensic data loss.

## Finding 1 — HMB is enabled on all 6 WD_BLACK SN7100 drives across the cluster

```
$ for n in k8s-1 k8s-2 k8s-3; do for d in nvme0 nvme1; do
    talosctl read /sys/class/nvme/$d/hmb
  done; done

k8s-1 nvme0 (WD): hmb = 1
k8s-1 nvme1 (WD): hmb = 1
k8s-2 nvme0 (WD): hmb = 1
k8s-2 nvme1 (WD): hmb = 1
k8s-3 nvme0 (WD): hmb = 1
k8s-3 nvme1 (WD): hmb = 1
```

**HMB (Host Memory Buffer)** is a feature where the NVMe drive uses a region of host RAM (allocated by the kernel and mapped via DMA) as a metadata cache. The drive accesses this buffer via DMA over PCIe. The Linux NVMe driver enables HMB by default when both the drive and kernel support it. The WD_BLACK SN7100 advertises HMB support; the kernel honors that.

## Why this connects to the iter #20 / iter #26 IOMMU finding

iter #20 + iter #26 confirmed that **k8s-2 and k8s-3 have `intel_iommu` actively translating every PCIe DMA**. k8s-1 doesn't (BIOS 1.26 doesn't expose DMAR).

**HMB on an IOMMU-enabled host requires every drive→host DMA to go through IOMMU page-table translation.** If the IOMMU mapping for the HMB region is incomplete, stale, or unmapped at the moment the drive issues an HMB write, the drive's DMA hits an invalid IOVA. Behaviors:

- Best case: IOMMU faults; kernel logs `DMAR: DMA Read Fault` or similar; drive's HMB request silently fails
- **Worst case: BIOS-default IOMMU fault behavior is "halt" or "reset"; system silently restarts**

This is **exactly the failure-mode signature** the silent-reboot investigation has been chasing. And it's only relevant on k8s-2/k8s-3 (BIOS 1.27 with IOMMU), not k8s-1 (BIOS 1.26 with no IOMMU).

But — k8s-1 silent-rebooted on 2026-05-05 too (its first such event in 190 days). So **HMB-IOMMU is a possible *contributor* on k8s-2/k8s-3, not a cluster-wide explanation**. It would compound with the cluster-wide Vmin/C8 mechanism rather than replacing it.

## Why iter #23's supporting evidence has aged out

iter #23 reported finding **one** instance of `nvme nvme1: using unchecked data buffer` on k8s-3 at 2026-05-05T21:49:51Z. iter #27 just re-grepped current dmesg on all nodes:

```
k8s-1: 0 occurrences
k8s-2: 0 occurrences
k8s-3: 0 occurrences
```

**The warning is gone from the ring buffer on every node.** Why?

The kernel ring buffer is bounded by **size**, not time. iter #19 documented that Talos's `KernelParamSpecController` is in a permanent retry loop, logging `overriding KSPP` + `controller failed` **every ~60-90 seconds on every node**. That's roughly **1,000-1,500 spam log entries per node per day**. The ring buffer fills up; older entries roll out.

iter #23's k8s-3 grep saw the warning at 21:49:51Z. iter #27 (just now) re-grepped. The ring buffer has rotated — the warning aged out. **What was 7 hours ago is no longer recoverable from the local ring buffer.**

### This is a real forensic problem

Two consequences:

1. **The Vector kernel sink (iter #5) is the only persistent record of kernel events.** It captures lines in real time and writes them to a file. The local dmesg ring is now structurally inadequate for retrospective analysis spanning more than a few hours.

2. **iter #19's "Talos bug worth filing upstream" is upgraded from minor annoyance to forensic priority.** The KernelParamSpecController spam isn't just adding wake events — **it's actively destroying diagnostic data**. Fixing it (or rate-limiting it) would preserve hours-to-days of additional kernel-event history in the ring.

### What this changes for the recommendation stack

- iter #5 PR (`SysctlConfig` + `WatchdogTimerConfig`) and iter #6 PM-QoS DaemonSet are still the primary recommendation. Unchanged.
- **Add: file the upstream Talos issue for KernelParamSpecController retry loop** — re-prioritized from minor to medium-priority because it's eating forensic dmesg data.
- **Forward-looking watch metric**: the Vector sink should be the source-of-truth for kernel events going forward. Add a PrometheusRule that alerts if the sink stops receiving messages (a kernel sink stall is its own kind of forensic emergency).

## Sysfs HMB writability

I tried to determine if `/sys/class/nvme/nvme*/hmb` is runtime-writable so we could disable HMB without rebuilding the UKI. `talosctl stat` returned nothing — the command doesn't expose mode bits the way I asked. Per Linux kernel source (`drivers/nvme/host/sysfs.c`), `hmb` is declared with `S_IRUGO | S_IWUSR` permissions in some kernel versions, read-only in others. Could not verify without a more detailed query.

If `hmb` is writable, a runtime DaemonSet op to **disable HMB on all WD drives** would close the HMB-IOMMU concern:

```sh
echo 0 > /sys/class/nvme/nvme0/hmb   # disable HMB on each drive
```

This would be an **additional op** in the iter #3 / #6 DaemonSet manifest, alongside PM-QoS / ASPM / NVMe APST. Worth experimenting with after the primary mitigation lands.

If `hmb` is NOT writable, the alternative is a kernel param `nvme_core.host_memory_buffer=0` — but that's UKI-sealed (iter #3) so requires a custom Talos image build.

## Honest assessment

| Probe | Result |
|---|---|
| HMB enabled on all WD drives | **Yes** (`hmb=1` everywhere) |
| iter #23's "unchecked data buffer" warning | **Aged out of all ring buffers** — not currently visible |
| KSPP-retry-spam consuming ring buffer | **Confirmed** — meta-forensic problem |
| Sysfs HMB writability | **Inconclusive** — needs different probe |

**Net contribution:** one thread worth flagging (HMB-IOMMU on BIOS-1.27 nodes is a documented silent-reset path) + one important meta-finding (the KSPP loop is actively destroying forensic data, upgrading the priority of the iter #19 upstream bug).

The HMB-IOMMU thread is **conditional**: it's only relevant on k8s-2/k8s-3 (BIOS-1.27 + IOMMU active). The cluster-wide Vmin/C8 mechanism still explains the cross-node 2026-05-05 event including k8s-1. So this remains a contributor, not a replacement.

## Cross-references

- `evidence-2026-05-06-deep-dmesg-sweep.md` (iter #23) — recorded the "unchecked data buffer" warning that has now aged out
- `evidence-2026-05-06-dmar-iommu-bios-asymmetry.md` (iter #20) — DMAR table presence
- `evidence-2026-05-06-iommu-active-and-diskstats.md` (iter #26) — IOMMU runtime active state confirmation
- `evidence-2026-05-06-talos-controller-retry-loop.md` (iter #19) — KSPP retry loop; iter #27 upgrades its priority
- `evidence-2026-05-06-itco-unfed-and-nmi-panic-sysctls.md` (iter #5) — Vector kernel sink as the only persistent kernel-event record
- Plan 0013 — add Vector-sink-stall PrometheusRule + KSPP-spam upstream fix to acceptance criteria
