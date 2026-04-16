---
name: k8s-2 reboot root-cause analysis (2026-04-15)
description: Three-agent RCA concluded kernel/microcode regression on Talos 1.12.3–1.12.5 hitting k8s-2's Mushkin DDR5; upgrade to 1.12.6 resolved; watch-and-wait through 2026-04-22 to confirm
type: project
---

## Summary

A 3-agent investigation (forensic, hardware-hypothesis, devils-advocate) on 2026-04-15 concluded that k8s-2's 32-reboot-in-61-day pattern was most likely a **kernel/microcode regression in Talos 1.12.3–1.12.5** interacting with k8s-2's Mushkin DDR5 + RaptorLake-P IMC. The rolling upgrade to Talos v1.12.6 on 2026-04-12 appears to have resolved it.

## Key findings

### Forensic (live Talos pull, all 3 nodes)

- **k8s-2 uptime at investigation time: 94h** — longest stable stretch since the pattern began 2026-02-11.
- All three nodes rebooted simultaneously on 2026-04-12 (k8s-1 02:29Z, k8s-2 02:40Z, k8s-3 02:52Z) — signature of a rolling Talos upgrade, not spontaneous.
- k8s-2 dmesg showed 5× apply-config events at 03:04–03:15Z, consistent with post-upgrade machineconfig reconciliation.
- **No MCE / EDAC / AER / lockup / NMI signal** in preserved dmesg on any node. No hardware-error smoking gun.
- BIOS: k8s-1 is `1.26 10/14/2024`; k8s-2 and k8s-3 are `AHWSA.1.22 03/12/2024`. k8s-1 is the BIOS outlier, not k8s-2.
- Rendered machineconfigs are byte-identical across all three nodes modulo hostname/IP/MAC/install-disk serial. No k8s-2-scoped patches exist.

### Hardware hypothesis (web research)

- **Mushkin MRA5S520HHHD48G is not on the Level1Techs MS-01 compatibility database.** Only Crucial CT48G56C46S5 (5600 MT/s) is community-confirmed.
- RaptorLake-P mobile IMC has documented inconsistency with dual-rank DDR5 SODIMMs (Overclock.net RPL IMC thread).
- Intel confirmed mobile 13th gen is **unaffected** by the Vmin shift / chip degradation issue (13900K/14900K only).
- MS-01 19V DC brick failures produce instant-off (STH thread) — weaker fit since k8s-2 recovers on its own.
- Proxmox MS-A2 thread documented spontaneous reboots on kernels 6.14+ / 6.17+ — same IMC class as MS-01.

### Devils-advocate (software counter-hypothesis)

- **Conceded after rigorous search.** Could not find any config, commit, workload, or Talos-layer asymmetry targeting k8s-2.
- 4 prior Tailscale hostnames (k8s-2, k8s-2-1, k8s-2-2, k8s-2-3) are explained by `TS_STATE_DIR=mem:` re-registration on each reboot — not evidence of multiple reimages.
- Proposed cheapest falsifying test: swap install disks between k8s-2 and k8s-3; if reboots follow the disk it's software, if they stay with the chassis it's hardware.

## Timeline reconstruction

1. **Pre-2026-02-07:** Talos 1.12.2, all nodes stable.
2. **2026-02-07 (commit 11e9c4a1):** Talos 1.12.2 → 1.12.3 rolled out.
3. **2026-02-11:** k8s-2 OS disk wiped and reinstalled. Reboot pattern began immediately.
4. **2026-02-11 → 2026-04-12:** 32 spontaneous reboots, median 29h apart, min 2.4h, max 164h. No cron/time-of-day/day-of-week pattern.
5. **2026-04-11/12 (commits d2686c2, 3211d1e):** Rolling upgrade to Talos v1.12.6 + Kubernetes v1.35.3. New kernel 6.18.18-talos, new intel-ucode.
6. **2026-04-12 onward:** k8s-2 stable, no spontaneous reboots.

## Hypothesis ranking (as of 2026-04-15)

| # | Hypothesis | Confidence |
|---|---|---|
| 1 | Talos 1.12.6 upgrade fixed a kernel/microcode regression that hit k8s-2's Mushkin + RPL-P IMC combo | medium-high |
| 2 | Coincidence — 94h is in the tail of the old distribution | low (becomes implausible past ~240h / 10 days) |
| 3 | Mushkin RAM is fundamentally marginal; 1.12.6 merely masks it | medium (latent; can't falsify by waiting, only confirmed if reboots resume) |

Hypotheses 1 and 3 are not mutually exclusive. The Mushkin kit may be marginal AND the 1.12.6 kernel well-behaved enough to mask it.

## Watch-and-wait plan

- **Threshold:** k8s-2 crosses 2026-04-22 (10 days) without spontaneous reboot → hypothesis #1 effectively confirmed.
- **Do not swap RAM now** — preserve the natural experiment window.
- **Before next Talos minor bump:** k8s-2 is the canary for kernel/microcode regressions on Mushkin. Apply k8s-2 first and observe before rolling to k8s-1/k8s-3.

## Implications for Longhorn (ADR 0005)

- If k8s-2 crosses 10 days stable, the hardware precondition for Longhorn rolling reinstall is met.
- k8s-2 still has only 1 of 2 WD_BLACK SN7100 NVMe drives (missing since 2026-03-06). Asymmetric Longhorn layout (2+1+2 = 5 disks) or drive replacement needed before symmetric talconfig.yaml declarations.
- Enterprise SSD upgrade (Micron 7450 Pro M.2 2280) evaluated but not a precondition — consumer WD_BLACK SN7100s are sufficient per ADR 0005.

## Sources

- [L1T MS-01 Compatibility DB](https://forum.level1techs.com/t/minisforum-ms-01-compatibility-database/208655)
- [Overclock.net RPL IMC dual-rank instability](https://www.overclock.net/threads/raptor-lake-13th-gen-ddr5-ddr4-imc-discussion.1801474/page-9)
- [Intel: mobile 13th gen unaffected by Vmin shift](https://community.intel.com/t5/Mobile-and-Desktop-Processors/Intel-Core-13th-and-14th-Gen-Vmin-Shift-Instabilty-Update-New/m-p/1686948)
- [STH: MS-01 died (PSU)](https://forums.servethehome.com/index.php?threads%2Fminisforum-ms-01-died.44299%2F=)
- [Proxmox: MS-A2 spontaneous reboots on 6.14+/6.17+](https://forum.proxmox.com/threads/spontaneous-reboots-on-minisforum-ms-a2-with-6-17-and-later-6-14.181084/)
- [Proxmox: MS-01 shutdown / microcode](https://forum.proxmox.com/threads/minisforum-ms-01-i9-13th-shutdown-issue.142065/)
