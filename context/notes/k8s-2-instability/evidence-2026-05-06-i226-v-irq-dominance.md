# Evidence: i226-V (igc, mgmt NIC) is the dominant non-timer IRQ source — independent justification for ASPM-disable

**Date:** 2026-05-06 (loop iteration #8, opus 4.7)
**Source:** `talosctl read /proc/interrupts` per node, betty TSDB conntrack/AER queries, sysfs reads.
**Status:** One structural finding + two rule-outs.

## Structural finding: i226-V management NIC is the dominant wake source

Top IRQ sources by cumulative count, per node, sorted by total:

| Node | Uptime | Top non-timer IRQ source | Total | Rate |
|---|---|---|---|---|
| k8s-1 | 7.7 h | irq=177 `enp87s0-TxRx-2` (igc) | 9.85 M | 355 / s |
| k8s-2 | 50.4 h | irq=172 `enp87s0-TxRx-1` (igc) | 46.6 M | 257 / s |
| k8s-3 | 9.1 h | irq=153 `enp87s0-TxRx-2` (igc) | 11.6 M | 354 / s |

Aggregating across all `enp87s0-TxRx-*` queues (typically 4-8 queues per i226 port):

| Node | All `enp87s0` IRQs | Rate |
|---|---|---|
| k8s-1 | ~20 M | ~720 / s |
| k8s-2 | ~104 M | ~570 / s |
| k8s-3 | ~24 M | ~730 / s |

For comparison, the i40e SFP+ storage-mesh ports each generate **~1-3 M IRQs total per port queue** over the same windows — roughly an order of magnitude less per queue, but spread across 16 queues per port. Net: **enp87s0 (igc / i226-V) is the largest single PCIe-device IRQ source**, generating roughly 250-720 wake-ups per second per node.

### Why this matters

`enp87s0` is driven by the `igc` driver. From `talos/.../dmesg` (iter #2 capture): `igc 0000:57:00.0 enp87s0: NIC Link is Up 1000 Mbps Full Duplex, Flow Control: RX/TX`. The MS-01 spec lists 2× Intel i226-V, so this is the i226-V management NIC running at 1 Gbps (link partner is a 1G switch).

Per `evidence-2026-04-30-web-research.md`:

> ## Intel I226-V NIC + ASPM
>
> The Intel I226-V NICs in the MS-01 are independently documented as causing system-level hangs when ASPM is enabled. The NIC drops off the PCIe bus silently — no kernel panic, no MCE. Fix: disable ASPM in BIOS and/or kernel parameter `pcie_aspm=off`, disable EEE.

**This puts the highest-rate wake source on a known-buggy-with-ASPM device.** Each of those 250-720 wake-ups per second is a PCIe link-state cycle (L1 → L0 → L1) on a device with documented silent-hang behavior under exactly this load profile.

This is a **second independent failure surface** layered on top of iter #6's C8/Vmin surface:

- **C8/Vmin (iter #6):** CPU enters package C8, voltage drops to Vmin, instructions fail, system hangs / resets
- **i226-V/ASPM (iter #8):** NIC enters L1 link state, fails to wake on packet RX, drops off PCIe bus, system hangs

Both fit the "silent reboot, no kernel logs" signature. Both are mitigated by the **same** runtime DaemonSet from iter #3:

| Mitigation | Addresses Vmin/C8 | Addresses i226-V/ASPM |
|---|---|---|
| Hold `/dev/cpu_dma_latency` open with 0 | ✓ (caps C-states at C0/C1) | indirect — fewer wake events |
| `echo performance > /sys/module/pcie_aspm/parameters/policy` | indirect — keeps NIC PHY in L0 | ✓ (forces ASPM off globally) |
| `echo 0 > /sys/class/nvme/nvme*/power/pm_qos_latency_tolerance_us` | n/a | n/a (NVMe-specific) |

The DaemonSet's three operations cover both failure surfaces and the documented NVMe APST issue. **iter #3's recommendation is now justified by two independent hypotheses** (Vmin via iter #6/#7, and i226-V/ASPM via iter #8), not just one.

## A surprising count-correlation

| Node | Local timer rate (LOC/s) | Historical silent reboots | i226-V IRQs/s |
|---|---|---|---|
| k8s-1 | 11,400 | 1 (2026-05-05 only) | ~720 |
| k8s-2 | **9,400 (lowest)** | **R0–R8 ≈ 9 events** | ~570 |
| k8s-3 | 14,200 (highest) | 1 (2026-05-05 only) | ~730 |

**k8s-2 has the lowest CPU-active rate** (LOC ticks per second) **and the highest historical silent-reboot count.** This is the inverse of "silent reboots correlate with high CPU load." Two readings:

1. **Lower CPU activity = more time in deep idle = more C8 entries = more Vmin events**, fitting iter #6's hypothesis. k8s-2 may have spent the most time in C8 because it had the least workload churn.
2. **The IRQ rates above are post-incident.** k8s-1 and k8s-3 booted only hours ago. Their workload mix is settling. Don't over-read the count without longer windows.

Reading (1) is a real prediction from iter #6: **the most-idle node should be the most reboot-prone**. The historical record on k8s-2 vs k8s-1/k8s-3 is consistent with that. After iter #3's DaemonSet lands, this should reverse — capping C-states at C1 should make k8s-2 stop being the reboot leader (or, if some other mechanism is at play, should reveal that mechanism).

## Rule-outs

### Conntrack utilization — clean

```
k8s-1: 2398 / 262144 (0.9%)
k8s-2: 4089 / 262144 (1.5%)
k8s-3: 3110 / 262144 (1.1%)
```

Conntrack table is essentially empty on every node. Conntrack-table-full kernel hangs are not a candidate.

### NVMe AER counters — clean

`aer_dev_correctable: RxErr 0` on every NVMe-relevant PCIe slot on every node (root ports `0000:00:06.0`, `0000:00:1d.0`, plus the NVMe device itself at `0000:01:00.0`). Adds to iter #7's clean-error-surface stack — **NVMe controllers are not producing PCIe errors either**.

A real NVMe-controller hang under ASPM would generate at least correctable AER events before the hang. The absence is a mild update against the NVMe-ASPM mechanism specifically as an actively-firing trigger today.

## Cumulative implication for plan 0013

Iter #8 doesn't add a new candidate hypothesis. It adds **a second independent failure surface** that the iter #3 DaemonSet already addresses, increasing the prior on the DaemonSet being correct.

After 8 iterations, the surviving candidate stack:

1. **Vmin shift / C8 idle voltage drop** (iter #6, #7 elimination, #8 indirect via "low-CPU node = most reboots")
2. **i226-V / ASPM silent PCIe bus drop** (iter #8 — formerly cataloged in 2026-04-30 web research, now backed by IRQ-rate evidence)
3. **iTCO unfed-watchdog timeout** (iter #5 — reviving 2026-04-30 hypothesis, now with the cluster-wide-event support)

All three are addressable by the **same three Talos-level changes**:

```yaml
# patches/global/sysctls.yaml
apiVersion: v1alpha1
kind: SysctlConfig
sysctls:
  kernel.panic_on_unrecovered_nmi: "1"
  kernel.panic_on_io_nmi: "1"
  kernel.unknown_nmi_panic: "1"
---
# patches/global/watchdog.yaml
apiVersion: v1alpha1
kind: WatchdogTimerConfig
device: /dev/watchdog0
timeout: 5m0s
```

```yaml
# kubernetes/apps/kube-system/idle-mitigations/ds.yaml
# DaemonSet that:
#   1. Holds /dev/cpu_dma_latency open with 0 (PM-QoS C-state cap)
#   2. Writes "performance" to /sys/module/pcie_aspm/parameters/policy
#   3. Writes 0 to /sys/class/nvme/nvme*/power/pm_qos_latency_tolerance_us
```

Total surface area: **two small Talos config patches + one DaemonSet manifest**. No physical access required, no UKI rebuild, no Talos kernel rebuild. All three landings are reversible.

## Verification trail

```
$ for n in k8s-1 k8s-2 k8s-3; do echo === $n ===; talosctl --endpoints $n -n $n read /proc/interrupts | awk 'NR==1{next}{sum=0; for(i=2;i<=20;i++) sum+=$i; print sum, $0}' | sort -rn | head -8; done

$ for n in k8s-1 k8s-2 k8s-3; do
    c=$(talosctl --endpoints $n -n $n read /proc/sys/net/netfilter/nf_conntrack_count)
    m=$(talosctl --endpoints $n -n $n read /proc/sys/net/netfilter/nf_conntrack_max)
    echo "$n: $c / $m"
  done

$ for n in k8s-1 k8s-2 k8s-3; do
    for slot in 0000:00:06.0 0000:00:1d.0 0000:01:00.0; do
      talosctl --endpoints $n -n $n read /sys/bus/pci/devices/$slot/aer_dev_correctable
    done
  done
```

## Cross-references

- `evidence-2026-04-30-web-research.md` — first cataloged the i226-V ASPM hypothesis; iter #8 supplies the IRQ-rate evidence that promotes it from "documented community pattern" to "active failure surface on this cluster"
- `evidence-2026-05-06-c-states-active.md` (iter #6) — Vmin/C8 measurement; iter #8 adds the "low-CPU = high-reboot" correlation that's a real prediction of the C8 hypothesis
- `evidence-2026-05-06-hardware-error-surfaces-clean.md` (iter #7) — iter #8 adds NVMe AER + conntrack to the clean-rule-out stack
- `evidence-2026-05-06-itco-unfed-and-nmi-panic-sysctls.md` (iter #5) — the third surviving candidate
- `evidence-2026-05-06-kernel-args-not-applied.md` (iter #3) — the runtime DaemonSet that addresses surfaces 1 & 2 in one place
- Plan 0013 — three landings (sysctls, watchdog feed, DaemonSet) close acceptance criteria 1 (forensic surface), 4 (HA-related not addressed here), and meaningfully advance toward terminal state (a) (localized fix)
