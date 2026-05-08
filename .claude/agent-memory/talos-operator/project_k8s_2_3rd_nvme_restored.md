---
name: k8s-2 third NVMe (WD_BLACK) is back as of 2026-05-06
description: k8s-2 now has 3 NVMe drives present again — supersedes earlier "missing WD_BLACK since 2026-03-06" note in project_k8s_2_hardware_state.md
type: project
---

As of 2026-05-06 (during plan-0013 nvme APST schematic rollout) `talosctl get disks -n k8s-2` shows 3 NVMe disks present:
- `nvme0n1` — WD_BLACK SN7100 1TB, serial `251021802221`
- `nvme1n1` — WD_BLACK SN7100 1TB, serial `251021801877`
- `nvme2n1` — CT500P3SSD8 500 GB (OS disk), serial `24304A23D2F0`

All three reported `pm_qos_latency_tolerance_us = 0` after the schematic boot.

**Why:** earlier memory `project_k8s_2_hardware_state.md` says the 2nd WD_BLACK NVMe disappeared on 2026-03-06 and the node was running with 2 disks since. That note appears stale — the drive is back. Check whether it was reseated/replaced or if the disappearance was transient firmware/PCIe link state.

**How to apply:** when working on k8s-2 disk topology, query `talosctl get disks -n k8s-2` for ground truth rather than trusting the older 2-disk memory. If you find only 2 disks, treat the older memory as current; if you find 3, update accordingly. Either way, never assume disk inventory from memory alone — re-verify before any disk-routing or Longhorn replica work.
