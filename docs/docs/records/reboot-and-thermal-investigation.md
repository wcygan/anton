---
title: Reboot and thermal investigations
record_type: historical-investigation
period: 2026-04 to 2026-05
---

# Reboot and thermal investigations

The 2026 investigations did not find one cause for the silent reboots. They did correct the timeline, find a harmful side effect of a mitigation, and separate node failures from slow service recovery.

## Corrected timeline

Checking boot identity and uptime showed that two nodes rebooted one after another, about 26 minutes apart, not at the same time. One timestamp is still an estimate, because a later graceful reboot overwrote the best evidence. Do not repeat the original "simultaneous reboot" claim.

## Leading hypothesis

The strongest hypothesis for the historically unstable node was low-voltage behavior at deep idle. The evidence stayed indirect. BIOS, firmware, memory, PCI, NVMe, C-states, IOMMU, NIC, and kernel were all examined, and some diagnostic surfaces were incomplete.

## A mitigation with a side effect

A mitigation meant to limit deep idle states set a PM-QoS latency request of zero microseconds. On this platform, zero allows only polling, so it also disabled the shallow C1 state. The result was sustained CPU throttling and high temperatures on the nearby NVMe drive.

A canary at one microsecond restored C1, kept the intended restriction on deeper states, and cleared the throttling. This proved the side effect; it did not prove the original cause of the reboots.

## Slow recovery after reboots

A separate pair of reboots left accumulated ghost pods that blocked replacement ingress workloads, which extended the public outage.

**Lesson:** treat the node event and the service-recovery failure as two problems. Check event times against independent boot evidence before correlating symptoms. These findings describe past node conditions only.
