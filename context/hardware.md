# Hardware inventory

Node hardware reference for anton's three control planes.

**Chassis:** Minisforum MS-01 workstation — <https://store.minisforum.com/products/minisforum-ms-01-workstation>

**CPU:** Intel® Core™ i9-13900H (13th Gen, 14 cores / 20 threads, 5.4 GHz max) — same on all three nodes.

**OS:** Talos Linux (immutable, API-driven; machine configs in `talos/`).

**Last verified:** 2026-04-15

## RAM

All nodes ship 2× 48 GiB DDR5 SODIMMs (one per memory controller) for 96 GiB total. k8s-2 runs at a lower speed (Mushkin vs Crucial on the other two).

| Node (tailnet IP) | Used / Total (MiB) | Modules | Manufacturer | Part | Speed |
|---|---|---|---|---|---|
| k8s-1-1 (100.90.7.128) | 4,345 / 96,260 | 2× 48 GiB | Crucial Technology | CT48G56C46S5.M16B1 | 5600 MT/s |
| k8s-2-3 (100.123.134.70) | 3,642 / 96,224 | 2× 48 GiB | Mushkin | MRA5S520HHHD48G | 5200 MT/s |
| k8s-3-1 (100.89.247.4) | 3,090 / 96,221 | 2× 48 GiB | Crucial Technology | CT48G56C46S5.M16B1 | 5600 MT/s |

## Storage

All nodes install Talos to the Crucial P3 500 GB. Each node has 2× WD_BLACK SN7100 1 TB data NVMes reserved for replicated block storage (Longhorn, ADR 0005).

| Node | System disk (500 GB) | Data NVMe #1 (1 TB) | Data NVMe #2 (1 TB) |
|---|---|---|---|
| k8s-1-1 | Crucial CT500P3 — `24304A343650` | WD_BLACK SN7100 — `251021802190` | WD_BLACK SN7100 — `251021802186` |
| k8s-2-3 | Crucial CT500P3 — `24304A23D2F0` | WD_BLACK SN7100 — `251021802221` | WD_BLACK SN7100 (second slot) |
| k8s-3-1 | Crucial CT500P3 — `24304A23705F` | WD_BLACK SN7100 — `251021801882` | WD_BLACK SN7100 — `251021800405` |

System disks are pinned by serial in `talos/talconfig.yaml` via `installDiskSelector`.

> **Note on k8s-2:** the second data NVMe is currently not enumerated at POST (PCIe `0000:01:00.0` endpoint absent). See `.claude/agent-memory/talos-operator/project_k8s_2_hardware_state.md` for the disappearance timeline and reboot correlation. This document records the intended/nominal topology; restore k8s-2 to 2× WD_BLACK before depending on symmetric OSD/replica placement.
