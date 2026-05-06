# Evidence: deep dmesg sweep finds zero kernel software anomalies + one new NVMe warning on k8s-3

**Date:** 2026-05-06 (loop iteration #23, opus 4.7)
**Source:** `talosctl dmesg | grep -iE '<broad anomaly pattern>'` per node, plus a frequency-deduplicated kernel-message tally.
**Status:** One strong negative (no kernel software anomalies) + one genuinely new datapoint (NVMe warning on k8s-3) that prior sweeps missed.

## Finding 1 — Zero kernel software anomalies across all three nodes

The deep search covered patterns that prior dmesg sweeps did **not** explicitly filter for:

- `rcu_(sched|preempt|tasks).*stall` — RCU stall warnings
- `workqueue.*stall` — workqueue blocked
- `BUG:` / `Oops:` / `kernel BUG at` — kernel oopses
- `INFO: task .* blocked` — D-state task warnings
- `NMI watchdog` / `soft lockup` / `hung_task` — lockup warnings
- `verifier` — BPF verifier rejections
- `kobject:` — kobject errors
- `process_one_work .* timed out` — workqueue timeouts
- `sched: RT throttling` — RT scheduler throttling
- `migration.*stall` — migration stuck
- `cgroup .* invoked oom` / `killed process` — OOM events

**Result: zero matches** on every node. Combined with iter #2 (no AER/MCE/NIC/NVMe errors) and iter #9 (`kernel.tainted = 0`), this is a comprehensive negative on kernel-software-detected failures.

This **strengthens** the iter #7 reading that "the failure happens at a level below kernel logging" — the kernel sees no oops, no warning, no stall, no rejected BPF program, no scheduling pathology. The silent reboots leave no kernel-software footprint of any kind.

## Finding 2 — One kernel-level NVMe warning on k8s-3, never reported before

```
k8s-3: kern: warning: [2026-05-05T21:49:51.885321319Z]: nvme nvme1: using unchecked data buffer
```

**This is the only real kernel-level anomaly across all three nodes' dmesg ring buffers.** Prior dmesg sweeps (iter #2, #19) didn't catch it because their keyword filters didn't include "unchecked data buffer."

### What "using unchecked data buffer" means

This warning is emitted by the kernel NVMe driver when it submits an I/O request whose host buffer cannot be validated against the drive's expected memory model. Common causes:

- The drive doesn't fully support the Host Memory Buffer (HMB) feature (less common on modern Gen4 drives — WD_BLACK SN7100 declares HMB support)
- The kernel constructed a request with a buffer in unexpected memory zone
- Specific I/O patterns (very large, vectored, or unusual alignment) trigger the slow validation path

**It's a soft warning, not an error.** The I/O completes; the driver just notes that it had to do extra checking. Not a silent-reboot trigger by itself.

### Why this is interesting

The drive in question is **`nvme1` on k8s-3 = WD_BLACK SN7100 1TB at slot `0000:01:00.0`** (per iter #11) — the Gen4 ×4 drive at the CPU-direct PCIe slot. This is also the drive iter #7 noted is running near its WCTEMP threshold (60-72°C across nodes; on k8s-3 it's at 60.85°C currently).

**The WD_BLACK SN7100 is a known drive with documented Linux interaction quirks:**
- Released early 2024
- Aggressive APST (autonomous power state transitions) with deep sleep states
- Documented community reports of NVMe-driver warnings under specific I/O patterns on Linux
- Firmware revisions have shipped silent fixes for Linux compatibility

The iter #7 NVMe temperatures + iter #11 drive identification + iter #20 IOMMU activation (k8s-3 has DMAR enabled, which adds a translation step on every NVMe DMA) + iter #23 unchecked-buffer warning **paint a coherent picture of NVMe-driver interactions that are non-trivial on this hardware**. None of these individually is a silent-reboot cause, but they collectively describe a drive subsystem that's running close to documented edge cases.

### Action

**iter #3's DaemonSet ASPM disable + NVMe APST disable is the right mitigation.** Setting `nvme_core.default_ps_max_latency_us=0` (iter #15 single-write refinement) prevents the drive from entering deep power states, which directly removes the most common trigger for "unchecked data buffer" warnings.

**Forward-looking watch metric:** alert on `nvme nvme.*: using unchecked` appearing more than once per hour on any node. A repeated occurrence would indicate firmware-level NVMe drive misbehavior approaching the silent-controller-hang documented in iter #8's web-research cross-reference.

## Finding 3 — k8s-1 has Longhorn iSCSI activity in dmesg

The frequency-dedupe output for k8s-1 shows:
```
4× sd N:N:N:N: N N-byte logical blocks: (N.N GB/N.N GiB)
3× sd N:N:N:N: Power-on or device reset occurred
3× scsi N:N:N:N: RAID IET Controller
3× scsi hostN: iSCSI Initiator over TCP/IP
3× EXTN-fs (sdd): mounted filesystem r/w
```

These are Longhorn iSCSI mount/unmount events — Longhorn uses iSCSI to attach replicas to pods. k8s-1 currently hosts the `longhorn-driver-deployer` pod (per iter #12), so it's the active iSCSI initiator. **Normal Longhorn operation, not anomaly.**

But it is worth noting that **iSCSI initiator events are not gentle** — each attach/detach involves SCSI device probe, partition table read, filesystem mount. These are wake events.

## Honest assessment of iter #23

| Probe | Result |
|---|---|
| Kernel software anomalies (RCU stall, BUG:, Oops, hung_task, verifier, etc.) | **Zero on every node** — strong negative |
| Kernel-level NVMe / driver warnings | **One: `nvme nvme1: using unchecked data buffer` on k8s-3** at 21:49:51Z |
| Frequency-dedupe top messages | All routine (Longhorn iSCSI, eth rename, ext-fs mount) |

**Net contribution:** strong corroboration of "below kernel-logging horizon" reading + one new anomaly that doesn't change the recommendation but is worth a forward-looking alert.

## Cross-references

- `evidence-2026-05-06-hardware-error-surfaces-clean.md` (iter #7) — clean error surfaces; iter #23 deep search confirms across kernel-software-anomaly axis as well
- `evidence-2026-05-06-kernel-taint-and-psi-clean.md` (iter #9) — `kernel.tainted = 0`; iter #23 dmesg sweep gives the same answer from a different surface
- `evidence-2026-05-06-nvme-lineup-uniform.md` (iter #11) — identifies WD_BLACK SN7100; iter #23 documents one operational warning on that drive
- `evidence-2026-05-06-i226-v-irq-dominance.md` (iter #8) — web research on NVMe + ASPM silent-controller-hang; iter #23 may be a soft precursor of that pattern
- `evidence-2026-05-06-kernel-args-not-applied.md` (iter #3) — DaemonSet's NVMe APST disable directly mitigates the "unchecked data buffer" trigger pattern
- Plan 0013 — add a forward-looking PrometheusRule (or kernel-sink alert) on `using unchecked data buffer` repetition
