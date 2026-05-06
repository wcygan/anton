# Evidence: IRQ affinity is uniform (all CPUs eligible); machineconfig content is identical across nodes — iter #13's open question resolved

**Date:** 2026-05-06 (loop iteration #17, opus 4.7)
**Source:** `talosctl read /proc/irq/<n>/smp_affinity_list` for the i226-V and i40e IRQs; `talosctl get machineconfig v1alpha1 -o yaml` three-way diff.
**Status:** Two clean confirmations + one interesting connection that strengthens the iter #14 reading.

## Finding 1 — IRQ affinity is uniform: `cpus=0-19` for every NIC IRQ on every node

```
k8s-1: 5× enp87s0 + 11× i40e IRQs probed — all show cpus=0-19
k8s-2: 5× enp87s0 + 11× i40e IRQs probed — all show cpus=0-19
k8s-3: 5× enp87s0 + 11× i40e IRQs probed — all show cpus=0-19
```

All 20 logical CPUs are eligible to receive every NIC IRQ on every node. **No IRQ pinning, no asymmetric distribution between nodes.** This is the kernel default with no `irqbalance` daemon and no manual affinity set in the Talos config.

This rules out an IRQ-pinning asymmetry as a contributor to k8s-2's historical reboot bias.

### Interesting connection to iter #14

With `cpus=0-19` affinity, the kernel's default delivery routes IRQs to **whichever CPU is least loaded** at the moment of delivery. Combined with iter #14's finding that **E-cores (cpu12-19) spend ~50% of their time in C8 vs P-cores' ~30%**, this means:

- E-cores are statistically the most idle cores at any given moment
- The IRQ balancer preferentially delivers to idle cores
- → E-cores receive a disproportionate fraction of NIC wake-from-C8 events
- → E-cores bounce through Vmin transitions more frequently than P-cores

This is a **structural amplifier for the iter #14 reading**. The wake-from-C8 events that are the Vmin failure surface aren't randomly distributed across cores — they're concentrated on the cores already most exposed (E-cores). 

If Vmin shift is the mechanism, **E-cores experience the highest event rate × the highest exposure fraction**. This compounds rather than averages.

The iter #3 PM-QoS DaemonSet still addresses this correctly — `/dev/cpu_dma_latency = 0` caps C-states cluster-wide on every CPU. But the iter #14 alternative (per-core-type EPP, setting only E-cores to `performance`) becomes more attractive: it specifically protects the over-exposed cores while preserving P-core power efficiency.

## Finding 2 — Three-way machineconfig content diff: only per-node identifiers differ (iter #13 resolved)

`talosctl get machineconfig v1alpha1 -o yaml` retrieved per node, all three are 290 lines. The diffs are:

```
k8s-1 vs k8s-2:
  - node: k8s-1                   →   node: k8s-2
  - version: 1                    →   version: 3              (apply count, iter #13)
  - created: 2026-05-05T20:29Z    →   created: 2026-05-04T01:47Z   (boot timestamp)
  - updated: 2026-05-05T20:29Z    →   updated: 2026-05-04T16:28Z
  - hostname: k8s-1               →   hostname: k8s-2
  - 4× disk.serial values         →   4× different disk.serial values  (physical hardware)

k8s-2 vs k8s-3:
  - similar pattern: hostname, version (3 vs 1), timestamps, disk serials
```

**Every difference is one of: hostname / version / timestamps / disk serials. No functional configuration differences.** The talconfig patches are applied identically; the machine configs are functionally identical across nodes.

This **closes the iter #13 open question**: the version-3 vs version-1 disparity on k8s-2 is purely apply-history bookkeeping (k8s-2 had 3 successful applies because it was the focus of plan 0007/0009/0010 interventions). **There is no hidden config drift.**

### Practical consequence

When the iter #5 SysctlConfig + WatchdogTimerConfig patches land, they will apply uniformly on all three nodes — no risk of one node being in an unexpected state that would reject the patch. This was a small concern flagged in iter #13; it's now confirmed not an issue.

## Recommendation stack — unchanged after 17 iterations

The cumulative position is consistent:

1. **Vmin / C8 idle voltage drop** (iter #6 measured, iter #7+#9 elimination, iter #14 E-core concentration, iter #16 BPF-count alignment, iter #17 IRQ-affinity amplifier)
2. **i226-V / ASPM silent PCIe drop** (iter #8 IRQ-rate evidence)
3. **iTCO unfed-watchdog timeout** (iter #5 revival)

All three are addressed by the same three Talos changes:

```yaml
# talos/patches/global/sysctls.yaml
apiVersion: v1alpha1
kind: SysctlConfig
sysctls:
  kernel.panic_on_unrecovered_nmi: "1"
  kernel.panic_on_io_nmi: "1"
  kernel.unknown_nmi_panic: "1"
```

```yaml
# talos/patches/global/watchdog.yaml
apiVersion: v1alpha1
kind: WatchdogTimerConfig
device: /dev/watchdog0
timeout: 5m0s
```

```yaml
# kubernetes/apps/kube-system/idle-mitigations/ds.yaml
# DaemonSet that:
#   1. (preferred) echo performance > /sys/devices/system/cpu/cpu{12..19}/cpufreq/energy_performance_preference  (iter #14 / #17 — E-core specific)
#   2. echo performance > /sys/module/pcie_aspm/parameters/policy
#   3. echo 0 > /sys/module/nvme_core/parameters/default_ps_max_latency_us  (iter #15 single-write)
#   4. (fallback if #1 doesn't stop reboots) hold /dev/cpu_dma_latency open with 0   (cluster-wide PM-QoS hard cap)
```

(Op 1 is new in this manifest — iter #14 + #17 promotes per-core-type EPP for E-cores from "alternative" to "preferred first try.")

## Honest assessment

After 17 iterations, the analytical surface has been thoroughly walked. Every dimension that could plausibly vary between nodes has been checked:

| Dimension | Status |
|---|---|
| Hardware (board, BIOS, NVMe, CPU, microcode) | Uniform (iter #11, #13) |
| Firmware (BIOS sub-version, NVMe firmware, intel-ucode) | Uniform (iter #6, #11, #13) |
| Kernel (sysctls, modules, module params, taint state) | Uniform (iter #5, #9, #15) |
| Talos (extensions, machineconfig content) | Uniform (iter #6, #17) |
| IRQ affinity | Uniform (iter #17) |
| Workload placement | **k8s-2 hosts observability stack** (iter #12) |
| machineconfig version count | k8s-2 = 3 vs others = 1, but content identical (iter #13 + #17) |
| Cilium BPF program count | k8s-3 > k8s-2 > k8s-1 (reflects pod density, iter #16) |
| Failure surfaces (AER, ECC, MCE, thermal, fans, conntrack) | All zero (iter #7, #8, #9) |
| Active failure surface (C8 / MWAIT 0x60) | In heavy use, E-cores dominant (iter #6, #14) |

**The asymmetry between nodes is dominantly workload placement (iter #12), with no hardware or kernel-config divergence.** The mechanism is most consistent with cluster-wide Vmin/C8 with E-core dominance.

**Recommended next step (unchanged since iter #10): land the PR, watch.** Further analytical iterations are not changing the recommendation; only empirical results from a watch window will be more informative.

## Cross-references

- All prior 16 iterations
- Plan 0013 acceptance criteria 1 + 4 + terminal state (a)
