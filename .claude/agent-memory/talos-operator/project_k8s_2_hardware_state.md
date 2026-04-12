---
name: k8s-2 hardware state
description: k8s-2 lost one of two WD_BLACK SN7100 NVMes around 2026-03-06 and has been spontaneously rebooting every 1-3 days since; OS disk is the CT500P3, surviving WD_BLACK is at PCIe 0000:58:00.0 nvme0n1
type: project
---
k8s-2 has degraded NVMe topology and a chronic reboot pattern that the other two control planes do not exhibit. **The drive went missing on 2026-03-06; the reboots correlate with that date.** Treat k8s-2 as unstable until the missing drive is physically reseated/replaced or the slot is proven dead.

## Hardware inventory (current)

- **OS install disk** — Crucial CT500P3SSD8 500GB, serial `24304A23D2F0`, EUI `eui.000000000000000100a075244a23d2f0`
  - PCIe addr `0000:59:00.0`, currently `nvme1n1` (renumbered from `nvme2n1` after the third drive vanished)
  - PCIe link runs **8.0 GT/s x2** of an x4-capable slot. **This is normal for this slot on these motherboards** — k8s-1 and k8s-3 also run their CT500 at x2 in the `0000:59:00.0` slot. Not a degradation, just slot wiring. Do not chase it.
  - Pinned in `talos/talconfig.yaml` via `installDiskSelector: serial: 24304A23D2F0`
- **Surviving WD_BLACK** — SN7100 1TB, serial `251021802221`, EUI `eui.e8238fa6bf530001001b448b4d7a7f78`, firmware `7615M0WD`
  - PCIe addr `0000:58:00.0`, currently `nvme0n1`
  - PCIe link `8.0 GT/s x4` (Gen3 x4), max `16.0 GT/s x4`. Healthy. Drive is Gen4-capable but the slot is Gen3.
  - sysfs `/sys/class/nvme/nvme0/state` reports `live`. PCIe AER counters all zero since current boot.
- **MISSING WD_BLACK** — should be the second SN7100 1TB at PCIe addr `0000:01:00.0` (CPU-side root port `00:06.0`, bus 01)
  - Both k8s-1 and k8s-3 enumerate `pci 0000:01:00.0: [15b7:5045] type 00 class 0x010802 PCIe Endpoint` here. k8s-2 enumerates the parent root port (`pci 0000:00:06.0 PCIe Root Port, PCI bridge to [bus 01]`) but **no endpoint and no bridge window allocated** — BIOS sees nothing on the other end. The drive is electrically absent at POST, not link-failed mid-flight.
  - Kernel root complex reports `_OSC: platform does not support [AER]`, so PCIe link errors would NOT show up in dmesg even if they happened. Absence of kernel errors is not proof of absence of errors on the missing drive.

## Disappearance timeline (verified from `/var/log/syslogd.log`)

A leftover smartctl-exporter cron from the prior Rook install runs daily at ~00:04 UTC and scans every NVMe by name. This gives a daily ground-truth log of what drives were enumerated:

- **2026-03-06 00:07:13Z** — last successful smartctl scan of `/dev/nvme2n1` (the missing WD_BLACK was still present)
- **2026-03-06** — early-startup.log shows two reboots later that day: 16:16 and 18:56 UTC. The drive disappeared in this window.
- **2026-03-07 00:07:18Z onward** — only `nvme0n1` and `nvme1n1` are scanned. The third NVMe never reappears.
- 2026-04-12 — still missing. 32nd boot since Feb 11, latest reboot 2026-04-12 02:40 UTC.

## Reboot pattern (verified from `/var/log/early-startup.log`, persistent across boots)

`/var/log/early-startup.log` accumulates one `platform information` line per boot and survives reboots. As of 2026-04-12:

- **k8s-2: 32 boots** since 2026-02-11 (61 days). Spaced 1-3 days apart, never clustered, no manual-maintenance signature. **This is the alarming one.** Rebooted again 2026-04-12 02:40 UTC — ~45 hours after the previous boot on 2026-04-10 05:55 UTC.
- **k8s-1: 17 boots** since 2026-01-02. 5 cluster-install boots in early Jan, then a clean 90-day uptime, then 12 boots clustered within ~30 minutes on 2026-04-04 (clearly a manual `task talos:apply-node` / `upgrade-node` sequence). Healthy pattern.
- **k8s-3: 6 boots** since 2026-01-02, all on cluster install day. Has been up for ~98+ days continuously. Healthy.

k8s-2's `early-startup.log` starts on 2026-02-11 (the others start ~Jan 2-3), suggesting **k8s-2's OS disk was wiped and reinstalled on 2026-02-11**, ~6 weeks after the original cluster bootstrap. Whatever happened on Feb 11 reset k8s-2 from a clean state. The reboot thrashing started immediately after.

Most recent k8s-2 reboots:
- 2026-03-27 20:19 UTC
- 2026-04-03 16:45 UTC
- 2026-04-07 08:11 UTC
- 2026-04-10 05:55 UTC
- 2026-04-12 02:40 UTC (current boot)

**The user's "~twice recently" perception was correct — and that's just the latest in a 2-month pattern.**

## Why this is currently non-impacting

- No `rook-ceph` namespace exists; no StorageClass exists. `kubectl get sc` is empty. The `bluestore` labels on the surviving WD_BLACK and `/var/lib/rook` directory contents (`exporter`, `mon-c`, `storage`) are dormant residue from a prior Rook install. Nothing on the cluster currently writes to the WD_BLACKs.
- etcd lives on the OS install disk (`/var/lib/etcd` ~497MB inside `/var/lib` ~20GB of 500GB available), so the missing drive does not affect cluster state.
- The leftover `smartctl-exporter` cron still runs (logged daily in syslogd at midnight UTC), but it's harmless — just SMART reads via sudo. **Not a Rook pod**, just a leftover container; investigate which workload still ships it before re-enabling Rook.

## Why future-Rook will care

When the user reintroduces Rook/Ceph (mentioned in repo CLAUDE.md as planned), k8s-2 will have **only one OSD slot** instead of two, breaking symmetry with k8s-1/k8s-3. Plan accordingly: either physically replace the drive first, or accept asymmetric OSD placement and adjust failure-domain rules.

## What couldn't be determined read-only

- Whether the slot at PCIe `0000:01:00.0` is dead, the M.2 socket has a bad solder joint, or the drive itself has failed cold. Distinguishing these requires either physical reseat (does it come back?) or swapping the surviving WD_BLACK into the dead slot (does THAT come back?).
- Why k8s-2 reboots every 1-3 days. dmesg ring buffer resets each boot and rotated `/var/log/*.log.1` files rotate by SIZE not by boot, so there is **no preserved kernel log of the reboot moment itself**. No OOM, MCE, or panic markers in the current boot's dmesg. AER is disabled by ACPI so PCIe link errors would be silent.
- Whether the Feb 11 wipe was a deliberate maintenance event or a recovery from an earlier failure (no project-memory record found).

**Why:** Future sessions will be tempted to chase the WD_BLACK as the urgent issue — but the **reboot pattern is the bigger story** and is hardware-suggesting (consistent timing, no software trigger, started immediately after the OS reinstall). The slot topology gotcha (CT500 at x2 is normal, missing drive is at `01:00.0`) is easy to misread without comparing across nodes.

**How to apply:** When asked to "fix k8s-2" or to plan node replacement: lead with the reboot history, not the missing drive — the reboots are the actual stability problem and the drive is one possible cause. Cite the syslogd cron timestamps as the disappearance evidence; cite `/var/log/early-startup.log` boot counts as the reboot evidence. Don't waste time on the CT500 PCIe x2 link — verified normal across all 3 nodes. When Rook is reintroduced, k8s-2 will be asymmetric (1 OSD vs 2 on the others) until the missing drive is replaced.
